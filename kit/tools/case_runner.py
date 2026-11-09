#!/usr/bin/env python3
"""테스트 케이스(JSON)를 기기에서 돌리고 정답지와 비교한다.

  python3 tools/case_runner.py cases/<suite>.json --platform ios|aos|mac [--case TC-01,TC-02]
                               [--relaunch] [--allow-spend] [--device ID] [--preset NAME] [--out DIR]
  python3 tools/case_runner.py cases/<suite>.json --check      # 케이스 파일 형식만 검사(기기 없음)

판정은 세 층이다. 모델은 쓰지 않는다.
  1. expect(시트의 기대 결과를 트리 조건으로 옮긴 것) — 하나라도 틀리면 FAIL
  2. 정답지(answers/<suite>/<platform>/<case>/<checkpoint>.png·.json, 사람이 승인한 실행) 와 비교
     — 숫자가 든 글자(재화·시간·MID)는 마스크하고, 남은 큰 차이나 글자 차이가 있으면 REVIEW
  3. REVIEW 는 judge-request.md 로 모아 qa-judge(낮은 모델) 서브에이전트에게 넘긴다(tools/judge.py)

결과: runs/<suite>-<platform>-<시각>/results.json, 케이스별 캡처·트리, judge-request.md
exit: 0 전부 PASS/NOT_RUN · 1 FAIL 또는 REVIEW 있음 · 2 사용법·케이스 형식 · 3 ERROR(흐름·연결 실패) 있음
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'device_flows'))

import imgdiff  # noqa: E402
import qa_common as qc  # noqa: E402

SIG_AREA = 0.0025     # 이미지 면적의 0.25% 이상인 차이 덩어리만 의미 있는 차이로 본다(반짝이 등 작은 연출 제외)
MASK_PAD = 4         # 마스크 여백(게임 좌표). 실측: Android 디버그 문구 경계가 0 이면 남고 4 면 사라졌다
SIG_CHANGED = 0.03    # 마스크 뒤 바뀐 픽셀이 3% 를 넘으면 덩어리 크기와 상관없이 REVIEW

STEP_KEYS = {
    'tap': ('target',), 'tap_select': ('select',), 'tap_xy': ('x', 'y'), 'swipe': (), 'wait_scene': ('scene',),
    'wait': ('select',), 'wait_gone': ('select',), 'sleep': ('s',), 'close_popup': (), 'route': ('name',),
    'checkpoint': ('name',), 'back': (), 'state': ('path',), 'server_time': ('to',), 'scroll_find': ('select',),
}
ROUTES = ('to_lobby', 'back_to_lobby', 'lobby_to_gacha', 'refresh_user_info')
START = ('relaunch', 'lobby', 'here')


def coord(v, total):
    """게임 좌표. 숫자 그대로이거나 "50%" 처럼 화면 크기 대비 비율(원점 왼쪽 아래)."""
    if isinstance(v, str) and v.endswith('%'):
        return total * float(v[:-1]) / 100
    return float(v)


# --- 케이스 파일 검사 ----------------------------------------------------------
def validate(suite):
    errs = []
    if not isinstance(suite.get('cases'), list):
        return ['cases 배열이 없다']
    seen = set()
    for c in suite['cases']:
        cid = c.get('id')
        where = f'case {cid}'
        if not cid or cid in seen:
            errs.append(f'{where}: id 가 없거나 중복')
        seen.add(cid)
        if c.get('auto') is False:
            if not c.get('reason'):
                errs.append(f'{where}: auto=false 면 reason(자동화하지 않는 이유)이 필요')
            continue
        if c.get('auto') is None:
            errs.append(f'{where}: auto 가 비어 있다(아직 자동화하지 않은 케이스) — true/false 로 정한다')
            continue
        if c.get('start', 'lobby') not in START:
            errs.append(f'{where}: start 는 {START}')
        steps = c.get('steps') or []
        if not any(s.get('do') == 'checkpoint' for s in steps):
            errs.append(f'{where}: checkpoint 가 하나도 없다(판정할 곳이 없다)')
        names = set()
        for i, s in enumerate(steps):
            do = s.get('do')
            if do not in STEP_KEYS:
                errs.append(f'{where} step {i}: do={do!r} 는 모르는 동작 {sorted(STEP_KEYS)}')
                continue
            for k in STEP_KEYS[do]:
                if k not in s:
                    errs.append(f'{where} step {i} ({do}): {k} 가 필요')
            if do == 'swipe' and s.get('preset') != 'diagonal' and not all(k in s for k in ('x1', 'y1', 'x2', 'y2')):
                errs.append(f'{where} step {i} (swipe): x1·y1·x2·y2 또는 preset=diagonal 이 필요')
            if do == 'state' and s.get('op') != 'remove' and 'value' not in s:
                errs.append(f'{where} step {i} (state): value 가 필요(항목을 빼려면 op: remove)')
            if do in ('state', 'server_time') and not suite.get('server'):
                errs.append(f'{where} step {i} ({do}): 케이스 파일 머리에 server(예: gb-qa-126)가 필요')
            if do == 'server_time' and not suite.get('time_ok'):
                errs.append(f'{where} step {i}: 서버 시간을 바꾸는 케이스 — 케이스 파일 머리에 time_ok: true (서버를 같이 쓰는 사람과 합의한 뒤)')
            if do == 'route' and s.get('name') not in ROUTES:
                errs.append(f'{where} step {i}: route 는 {ROUTES}')
            if do == 'checkpoint':
                if s.get('name') in names:
                    errs.append(f'{where}: checkpoint 이름 중복 {s.get("name")}')
                names.add(s.get('name'))
                exp = s.get('expect') or {}
                try:
                    for key in ('present', 'absent', 'tappable', 'disabled', 'count'):
                        for sel in exp.get(key, []):
                            qc.normalize(sel)
                    for item in exp.get('text', []):
                        qc.normalize(item['select'])
                    for sel in s.get('mask', []):
                        qc.normalize(sel)
                except (ValueError, KeyError, TypeError) as e:
                    errs.append(f'{where} checkpoint {s.get("name")}: {e}')
            for key in ('select',):
                if key in s:
                    try:
                        qc.normalize(s[key])
                    except ValueError as e:
                        errs.append(f'{where} step {i}: {e}')
    return errs


# --- 실행 -------------------------------------------------------------------
class Runner:
    def __init__(self, dev, suite, platform, out, allow_spend=False):
        self.dev = dev
        self.suite = suite
        self.platform = platform
        self.out = out
        self.allow_spend = allow_spend
        self.suite_name = suite.get('suite') or 'suite'
        self.allow_time = False
        self.restores = []

    def nodes(self, tree=None):
        return qc.visible(tree if tree is not None else self.dev.tree())

    def run_case(self, case, relaunch_first=False):
        from flowlib import FlowFailure
        import routes
        res = {'id': case['id'], 'title': case.get('title', ''), 'verdict': None, 'checkpoints': [], 'error': None,
               'reason': '', 'started': time.strftime('%H:%M:%S')}
        if case.get('auto') is not True:
            res['verdict'] = 'NOT_RUN'
            res['reason'] = case.get('reason') or '자동화하지 않은 케이스'
            return res
        if case.get('spends') and not self.allow_spend:
            res['verdict'] = 'NOT_RUN'
            res['reason'] = '재화를 쓰는 케이스 — --allow-spend 로만 돌린다'
            return res
        if any(st.get('do') == 'server_time' for st in case.get('steps', [])) and not self.allow_time:
            res['verdict'] = 'NOT_RUN'
            res['reason'] = '서버 시간을 바꾸는 케이스 — 서버를 같이 쓰는 사람과 합의한 뒤 --allow-time 으로만 돌린다'
            return res
        case_dir = os.path.join(self.out, case['id'])
        self.dev.out_dir = case_dir
        try:
            start = case.get('start', 'lobby')
            if start == 'relaunch' or relaunch_first:
                r = self.dev.call('launch', '--restart')
                if not r.get('ok'):
                    raise FlowFailure('BRIDGE', 'relaunch', r.get('error'))
                self.dev.wait(lambda: self.dev.call('ping').get('ok'), 90, 'relaunch', '브리지 응답')
                routes.to_lobby(self.dev, self.suite.get('preset'))
            elif start == 'lobby':
                try:
                    routes.back_to_lobby(self.dev)
                except FlowFailure:
                    routes.to_lobby(self.dev, self.suite.get('preset'), timeout=120)
            for i, step in enumerate(case.get('steps', [])):
                self.step(case, i, step, res)
        except FlowFailure as e:
            res['error'] = {'kind': e.kind, 'step': e.step, 'detail': e.detail, 'shot': self.dev.shot('failure'),
                            'shotError': getattr(self.dev, 'shot_error', None)}
        except Exception as e:  # noqa: BLE001 — 케이스 하나의 예외로 묶음 전체를 멈추지 않는다
            res['error'] = {'kind': 'RUNNER', 'step': '', 'detail': f'{type(e).__name__}: {e}', 'shot': None}
        finally:
            self.restore_state(res)
        cps = [c['verdict'] for c in res['checkpoints']]
        res['verdict'] = 'ERROR' if res['error'] else qc.worst(cps)
        if case.get('partial') and res['verdict'] == 'PASS':
            # 시트 기대 중 일부만 확인한 케이스 — 통과로 쓰지 않고 사람 확인(Check)으로 남긴다
            res['verdict'] = 'UNSURE'
            res['reason'] = f'일부만 자동 확인: {case["partial"]}'
        return res

    def step(self, case, i, s, res):
        from flowlib import FlowFailure
        import routes
        dev = self.dev
        do = s['do']
        label = s.get('label') or f'{do} #{i}'
        timeout = s.get('timeout', 15)
        if do == 'tap':
            dev.tap(s['target'], label, s.get('index'))
        elif do == 'tap_select':
            hit = qc.select(self.nodes(), s['select'])
            if not hit:
                raise FlowFailure('NAME_MISSING', label, f'{qc.describe(s["select"])} 가 트리에 없다 (scene={dev.scene()})')
            dev.tap_node(hit[s.get('index', -1)], label)
        elif do == 'tap_xy':
            w, h = dev.visible_size()
            dev.tap_xy(coord(s['x'], w), coord(s['y'], h), label)
        elif do == 'back':
            dev.tap('_btnBack', label)
        elif do == 'swipe':
            w, h = dev.visible_size()
            if s.get('preset') == 'diagonal':        # 디버그 콘솔 열기
                dev.swipe(20, 20, w - 20, h - 20, 600)
            else:
                dev.swipe(coord(s['x1'], w), coord(s['y1'], h), coord(s['x2'], w), coord(s['y2'], h), s.get('ms', 600))
        elif do == 'wait_scene':
            dev.wait_scene(s['scene'], timeout, label)
        elif do == 'wait':
            dev.wait(lambda: qc.select(self.nodes(), s['select']), timeout, label, qc.describe(s['select']))
        elif do == 'wait_gone':
            dev.wait(lambda: not qc.select(self.nodes(), s['select']), timeout, label, f'{qc.describe(s["select"])} 사라짐')
        elif do == 'sleep':
            time.sleep(float(s['s']))
        elif do == 'close_popup':
            owner = s.get('owner') or dev.scene()
            if dev.close_popup(owner) is None:
                raise FlowFailure('NOT_REACHED', label, f'{owner} 의 닫기 버튼을 찾지 못했다')
        elif do == 'route':
            fn = getattr(routes, s['name'])
            if s['name'] == 'to_lobby':
                fn(dev, self.suite.get('preset'))
            else:
                fn(dev, *s.get('args', []))
        elif do == 'state':
            self.change_state(s, label, res)
        elif do == 'scroll_find':
            # 목록을 넘기며 select 가 보이는 영역 안에 나올 때까지 찾는다
            w, h = dev.visible_size()
            sw = s.get('swipe', {'x1': '55%', 'y1': '20%', 'x2': '55%', 'y2': '55%'})
            lo, hi = s.get('band', ['5%', '85%'])
            for _ in range(int(s.get('max', 40))):
                hit = [n for n in qc.select(self.nodes(), s['select']) if n.get('rect')
                       and coord(lo, h) <= n['rect'][1] <= coord(hi, h)]
                if hit:
                    break
                dev.swipe(coord(sw['x1'], w), coord(sw['y1'], h), coord(sw['x2'], w), coord(sw['y2'], h), s.get('ms', 400))
                time.sleep(1.2)
            else:
                raise FlowFailure('NOT_REACHED', label, f'목록을 넘겨도 {qc.describe(s["select"])} 가 나오지 않았다')
        elif do == 'server_time':
            import timemachine
            code, info = timemachine.set_time(self.suite['server'], str(s['to']), reason=f'{self.suite_name} {case["id"]}')
            res.setdefault('serverTime', []).append(info)
            if code:
                raise FlowFailure('BRIDGE', label, f'서버 시간 변경 실패: {json.dumps(info, ensure_ascii=False)[:200]}')
            if s.get('relaunch', True):
                # 서버 시간이 바뀌면 앱이 다시 받아야 반영된다
                r = dev.call('launch', '--restart')
                if not r.get('ok'):
                    raise FlowFailure('BRIDGE', label, r.get('error'))
                dev.wait(lambda: dev.call('ping').get('ok'), 90, label, '브리지 응답')
                routes.to_lobby(dev, self.suite.get('preset'))
        elif do == 'checkpoint':
            if s.get('settle', 1.0):
                time.sleep(float(s.get('settle', 1.0)))
            res['checkpoints'].append(self.checkpoint(case, s))
        if s.get('after'):
            time.sleep(float(s['after']))

    def mid(self):
        """디버그 빌드 화면의 「MID : …」 라벨에서 계정 MID 를 읽는다."""
        import re
        from flowlib import FlowFailure
        for n in self.nodes():
            m = re.search(r'MID : (\w+)', n.get('text') or '')
            if m:
                return m.group(1)
        raise FlowFailure('NAME_MISSING', 'read MID', 'MID 라벨이 트리에 없다 — 디버그 설정의 show MID 를 켠다')

    def change_state(self, s, label, res):
        """마카롱으로 계정 필드를 바꾸고 앱에 반영한다. 케이스가 끝나면 restore_state 가 되돌린다."""
        import states
        import routes
        from flowlib import FlowFailure
        mid = self.suite.get('mid') or self.mid()
        out = os.path.join(self.dev.out_dir, 'macaron')
        if s.get('op') == 'remove':
            info = states.remove_item(self.suite['server'], mid, s['path'], out, s.get('max_refs'))
            if info.get('already'):
                res.setdefault('state', []).append({'op': 'remove', 'path': s['path'], 'already': True, 'mid': mid})
                return
            if s.get('restore', self.suite.get('restore_state', False)):
                self.restores.append(('insert', mid, info['path'], info['saved']))
            res.setdefault('state', []).append({'op': 'remove', 'path': info['path'], 'item': info.get('removed'), 'mid': mid})
            if s.get('refresh', True):
                routes.refresh_user_info(self.dev)
            return
        old = states.get_field(self.suite['server'], mid, s['path'], out)
        if old == s['value']:
            # 이미 원하는 상태 — 저장하지 않는다(상태는 되돌리지 않는 것이 기본이라 다음 실행에서 자주 생긴다)
            res.setdefault('state', []).append({'path': s['path'], 'from': old, 'to': s['value'], 'mid': mid, 'already': True})
            if s.get('refresh', True):
                routes.refresh_user_info(self.dev)
            return
        states.set_field(self.suite['server'], mid, s['path'], s['value'], out, expect=old)
        if s.get('restore', self.suite.get('restore_state', False)):
            self.restores.append((mid, s['path'], old, s['value']))
        res.setdefault('state', []).append({'path': s['path'], 'from': old, 'to': s['value'], 'mid': mid})
        if s.get('refresh', True):
            routes.refresh_user_info(self.dev)

    def restore_state(self, res):
        import states
        import routes
        if not self.restores:
            return
        out = os.path.join(self.dev.out_dir or self.out, 'macaron')
        failed = []
        for entry in reversed(self.restores):
            try:
                if entry[0] == 'insert':
                    _, mid, path, saved = entry
                    states.insert_item(self.suite['server'], mid, path, saved, out)
                    continue
                mid, path, old, value = entry
                states.set_field(self.suite['server'], mid, path, old, out, expect=value)
            except Exception as e:  # noqa: BLE001 — 되돌리기 실패는 결과에 남기고 사람에게 알린다
                failed.append(f'{path}: {e}')
        self.restores = []
        res['stateRestored'] = not failed
        if failed:
            res['stateRestoreErrors'] = failed
        try:
            routes.refresh_user_info(self.dev)
        except Exception:  # noqa: BLE001
            pass

    def checkpoint(self, case, s):
        dev = self.dev
        name = s['name']
        tree = dev.tree()
        nodes = self.nodes(tree)
        scene = dev.scene()
        geometry = dev.call('ping').get('result', {})
        shot = dev.shot(name) if s.get('image', True) else None
        cp = {'name': name, 'scene': scene, 'shot': shot, 'checks': qc.check_expect(s.get('expect'), scene, nodes),
              'baseline': None, 'diff': None, 'verdict': None}
        if s.get('image', True) and not shot:
            cp['shotError'] = getattr(dev, 'shot_error', None) or 'unknown'
        dump = {'scene': scene, 'geometry': {k: geometry.get(k) for k in ('visibleOrigin', 'visibleSize', 'frameSize')},
                'imageSize': imgdiff.size_of(shot) if shot else None, 'texts': qc.text_signature(nodes),
                'masks': qc.dynamic_masks(nodes, s.get('mask', [])), 'nodes': nodes}
        tree_path = os.path.join(dev.out_dir, f'{self.platform}-{name}.tree.json')
        qc.save_json(tree_path, dump)
        cp['tree'] = tree_path
        if not all(c['ok'] for c in cp['checks']):
            cp['verdict'] = 'FAIL'
            return cp
        # 시나리오 채점표 지점(scenario_run 이 붙인다): 채점은 조건(expect)으로 하고, 화면 비교는 켠 지점만 한다
        if s.get('scoring'):
            sc = s['scoring']
            if not sc.get('compareImage'):
                cp['baseline'] = 'off'
                cp['verdict'] = 'PASS'
                if sc.get('unconfirmed'):
                    cp['verdict'], cp['human'] = 'HUMAN', '채점 조건이 아직 확정되지 않았다 — 캡처를 보고 판단하고 조건을 확정한다'
                elif sc.get('human'):
                    cp['verdict'], cp['human'] = 'HUMAN', sc['human']
                return cp
        # 시나리오(scenarios/<탭>/<키>.json)는 채점표 정답을 저장소의 scenarios/<탭>/<키>/<플랫폼>/ 에 둔다
        base = os.path.join(case['answersDir'], self.platform) if case.get('answersDir') \
            else os.path.join(qc.ANSWERS, self.suite_name, self.platform, case['id'])
        bpng, bjson = os.path.join(base, f'{name}.png'), os.path.join(base, f'{name}.json')
        if not os.path.exists(bjson):
            cp['verdict'] = 'PASS'
            cp['baseline'] = 'none'
            return cp
        cp['baseline'] = base
        ref = qc.load_json(bjson)
        diff = {}
        # 정답에 저장된 바뀌는 영역(maskSelectors, 채점표 mask)과 단계의 mask 를 함께 적용한다 — 그 영역의 글자·그림은 비교하지 않는다.
        # maskSelectors 가 없는 예전 정답은 글자에 mask 영역이 들어 있으므로 예전처럼 글자 전체를 비교한다
        selectors = list(s.get('mask', []))
        selectors += [m for m in ref.get('maskSelectors', []) if m not in selectors]
        if 'maskSelectors' in ref:
            texts, cur_masks = qc.text_signature(nodes, selectors), qc.dynamic_masks(nodes, selectors)
        else:
            texts, cur_masks = dump['texts'], dump['masks']
        ref_texts = set(ref.get('texts', []))
        missing = sorted(ref_texts - set(texts))
        added = sorted(set(texts) - ref_texts)
        if missing or added:
            diff['texts'] = {'missing': missing[:30], 'added': added[:30]}
        if shot and os.path.exists(bpng) and s.get('image', True):
            g, size = ref.get('geometry'), ref.get('imageSize')
            masks = []
            if g and g.get('visibleSize') and size:
                # 그려진 글자가 노드 영역보다 조금 넓다(외곽선·그림자) — 게임 좌표로 MASK_PAD 만큼 넓혀 뺀다
                masks = [qc.to_pixels([x - MASK_PAD, y - MASK_PAD, w + 2 * MASK_PAD, h + 2 * MASK_PAD], g, size)
                         for x, y, w, h in ref.get('masks', []) + cur_masks]
            img = imgdiff.compare(bpng, shot, masks)
            area = img['size'][0] * img['size'][1]
            sig = [r for r in img['regions'] if r[2] * r[3] >= area * SIG_AREA]
            img['significant'] = sig
            if sig or img['changed'] > SIG_CHANGED:
                img['crops'] = imgdiff.crops_for(bpng, shot, sig or img['regions'], os.path.join(dev.out_dir, 'crops'),
                                                 f'{self.platform}-{name}')
                diff['image'] = img
            cp['imageChanged'] = img['changed']
        cp['diff'] = diff or None
        cp['verdict'] = 'REVIEW' if diff else 'PASS'
        return cp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('suite_file')
    ap.add_argument('--platform', choices=qc.PLATFORMS)
    ap.add_argument('--case', help='쉼표로 구분한 케이스 id')
    ap.add_argument('--device')
    ap.add_argument('--preset')
    ap.add_argument('--relaunch', action='store_true', help='첫 케이스 전에 앱을 새로 띄운다')
    ap.add_argument('--allow-spend', action='store_true', help='spends=true 케이스(재화 사용)도 돌린다')
    ap.add_argument('--allow-time', action='store_true', help='server_time 단계(서버 시간 변경)가 있는 케이스도 돌린다')
    ap.add_argument('--out')
    ap.add_argument('--check', action='store_true', help='케이스 파일 형식만 검사')
    a = ap.parse_args()
    suite = qc.load_json(a.suite_file)
    errs = validate(suite)
    if a.check:
        print(json.dumps({'ok': not errs, 'errors': errs, 'cases': len(suite.get('cases', []))}, ensure_ascii=False, indent=1))
        return 0 if not errs else 2
    if not a.platform:
        ap.print_usage(sys.stderr)
        return 2
    wanted = set(a.case.split(',')) if a.case else None
    cases = [c for c in suite.get('cases', []) if not wanted or c.get('id') in wanted]
    blocking = [e for e in errs if not wanted or any(f'case {w}' in e for w in wanted)]
    if blocking:
        print(json.dumps({'ok': False, 'errors': blocking}, ensure_ascii=False, indent=1))
        return 2
    if a.preset:
        suite['preset'] = a.preset
    from flowlib import Device
    stamp = time.strftime('%Y%m%d-%H%M%S')
    name = suite.get('suite') or os.path.splitext(os.path.basename(a.suite_file))[0]
    suite['suite'] = name
    out = a.out or os.path.join(qc.RUNS, f'{name}-{a.platform}-{stamp}')
    dev = Device(a.platform, qc.WORKSPACE, out, a.device)
    runner = Runner(dev, suite, a.platform, out, a.allow_spend)
    runner.allow_time = a.allow_time and bool(suite.get('time_ok'))
    results = {'suite': name, 'sheet': suite.get('sheet', ''), 'platform': a.platform, 'device': a.device or '',
               'started': stamp, 'suiteFile': os.path.abspath(a.suite_file), 'cases': []}
    if dev.call('ping').get('ok') is not True and not a.relaunch:
        print(json.dumps({'ok': False, 'error': '브리지 응답이 없다 — 앱을 launch 하거나 --relaunch 를 준다'}, ensure_ascii=False))
        return 3
    first = a.relaunch
    aborted = None
    for case in cases:
        if aborted:
            r = {'id': case['id'], 'title': case.get('title', ''), 'verdict': 'ERROR', 'checkpoints': [], 'reason': '',
                 'error': {'kind': 'BRIDGE', 'step': '-', 'detail': f'앞에서 기기 연결이 끊겨 돌리지 않았다 ({aborted})', 'shot': None}}
            results['cases'].append(r)
            print(f'[{a.platform}] ERROR   {case["id"]} — 연결이 끊겨 건너뜀', flush=True)
            continue
        r = runner.run_case(case, relaunch_first=first)
        if r['verdict'] not in ('NOT_RUN',):
            first = False
        err = r.get('error') or {}
        if err.get('kind') == 'BRIDGE' and dev.call('ping').get('ok') is not True:
            # 연결이 끊긴 채로 나머지를 돌리면 케이스마다 제한 시간만 기다린다 — 멈추고 원인을 알린다
            aborted = f'{case["id"]}: {err.get("detail")}'
            if a.platform == 'ios':
                err['hint'] = 'iPad 가 잠겼는지 먼저 본다(devicectl 오류 「device is locked」). 잠금 해제 후 다시 돌린다'
        results['cases'].append(r)
        print(f'[{a.platform}] {r["verdict"]:<7} {r["id"]} {r["title"]}'
              + (f' — {r["error"]["kind"]} at {r["error"]["step"]}: {r["error"]["detail"]}' if r['error'] else '')
              + (f' — {r["reason"]}' if r['reason'] else '')
              + (f' (힌트: {r["error"]["hint"]})' if r['error'] and r['error'].get('hint') else ''), flush=True)
        qc.save_json(os.path.join(out, 'results.json'), results)
    results['finished'] = time.strftime('%Y%m%d-%H%M%S')
    qc.save_json(os.path.join(out, 'results.json'), results)
    import judge
    req = judge.prepare(out)
    verdicts = [c['verdict'] for c in results['cases']]
    code = 3 if 'ERROR' in verdicts else 1 if ('FAIL' in verdicts or 'REVIEW' in verdicts or 'HUMAN' in verdicts) else 0
    print(json.dumps({'ok': code == 0, 'exit': code, 'results': os.path.join(out, 'results.json'),
                      'judgeRequest': req, 'counts': {v: verdicts.count(v) for v in sorted(set(verdicts))}},
                     ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
