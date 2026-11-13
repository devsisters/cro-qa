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
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'device_flows'))

import imgdiff  # noqa: E402
import qa_common as qc  # noqa: E402

SIG_AREA = 0.0025     # 이미지 면적의 0.25% 이상인 차이 덩어리만 의미 있는 차이로 본다(반짝이 등 작은 연출 제외)
MASK_PAD = 4         # 마스크 여백(게임 좌표). 실측: Android 디버그 문구 경계가 0 이면 남고 4 면 사라졌다
# 화면을 바꾸는 단계 — 「액션마다 캡처」가 켜져 있으면 이 단계가 끝날 때마다 화면을 찍어 흐름(actions)으로 남긴다
ACTION_STEPS = {'tap', 'tap_select', 'tap_xy', 'swipe', 'back', 'close_popup', 'route', 'scroll_find', 'state', 'server_time'}
ACTION_SETTLE = 2.0   # 액션 뒤 화면이 멈출 때까지 기다리는 최대 시간(초). 멈추면 바로 다음으로 간다
DEBUG_OVERLAY = ('TextureCache |',)   # 디버그 빌드 화면 위 표시줄 — 메모리 숫자가 계속 바뀐다
SETTLE_POLL = 0.25    # 화면이 멈췄는지 볼 때 트리를 다시 읽는 간격
FIND_WAIT = 5.0       # 누를 노드가 아직 없거나 덮여 있으면(화면 전환 중) 이만큼 다시 시도한다
SIG_CHANGED = 0.03    # 마스크 뒤 바뀐 픽셀이 3% 를 넘으면 덩어리 크기와 상관없이 REVIEW

STEP_KEYS = {
    'tap': ('target',), 'tap_select': ('select',), 'tap_xy': ('x', 'y'), 'swipe': (), 'wait_scene': ('scene',),
    'wait': ('select',), 'wait_gone': ('select',), 'sleep': ('s',), 'close_popup': (), 'route': ('name',),
    'checkpoint': ('name',), 'back': (), 'state': ('path',), 'server_time': ('to',), 'scroll_find': ('select',),
    'play': (),
}
PLAY_START_WAIT = 180   # play 단계 — 인게임이 시작되기를 기다리는 최대 시간(로딩 포함)
PLAY_POLL = 2.0
PLAY_END_EVENTS = ('game_over', 'timeout_stop', 'crash_stop')
ROUTES = ('to_lobby', 'back_to_lobby', 'lobby_to_gacha', 'refresh_user_info')
START = ('relaunch', 'lobby', 'here')


def tree_signature(tree):
    """화면이 멈췄는지 비교할 트리 요약 — 보이는 노드의 이름·글자·위치(정수로 반올림)·투명도·보임·활성.
    이름도 글자도 없는 노드(반짝이는 카드 효과 같은 반복 장식)는 뺀다 — 그것까지 보면 그 화면은 영영 멈추지 않는다.
    목록이 들어오는 연출은 카드 안의 이름 있는 라벨도 함께 움직이고 흐려지므로 그대로 잡힌다.
    트리의 노드 순서는 읽을 때마다 바뀔 수 있어 순서와 상관없이 비교한다. 디버그 표시줄(텍스처 메모리)은 늘 바뀌므로 뺀다."""
    out = []
    for n in qc.visible(tree or {}):
        if not (n.get('inst') or n.get('name') or n.get('text')) or str(n.get('text') or '').startswith(DEBUG_OVERLAY):
            continue
        r = n.get('rect') or ()
        out.append(repr((n.get('owner'), n.get('inst'), n.get('name'), n.get('text'), tuple(round(v) for v in r),
                         n.get('opacity'), n.get('visible'), n.get('enabled'))))
    return tuple(sorted(out))


def coord(v, total):
    """게임 좌표. 숫자 그대로이거나 "50%" 처럼 화면 크기 대비 비율(원점 왼쪽 아래)."""
    if isinstance(v, str) and v.endswith('%'):
        return total * float(v[:-1]) / 100
    return float(v)


# --- 기기 정보 · 기기 조건 ------------------------------------------------------
def _cmd(args, timeout=20):
    import subprocess
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def device_info(platform, device_id):
    """실행한 기기의 모델·OS — 결과에 남기고 checkpoint 의 device 조건에 쓴다. 못 읽으면 빈 값."""
    info = {'id': device_id or '', 'model': '', 'name': '', 'os': ''}
    if platform == 'aos':
        base = ['adb'] + (['-s', device_id] if device_id else []) + ['shell', 'getprop']
        info['model'] = _cmd(base + ['ro.product.model'])
        info['name'] = _cmd(base + ['ro.product.marketname'])
        info['os'] = _cmd(base + ['ro.build.version.release'])
    elif platform == 'ios' and device_id:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'info.json')
            _cmd(['xcrun', 'devicectl', 'device', 'info', 'details', '--device', device_id, '--json-output', path], 60)
            try:
                r = qc.load_json(path).get('result', {})
            except (OSError, ValueError):
                r = {}
        hw, dp = r.get('hardwareProperties', {}), r.get('deviceProperties', {})
        info['model'] = hw.get('productType', '')        # 예: iPad7,4
        info['name'] = hw.get('marketingName', '')       # 예: iPad Pro (10.5-inch)
        info['os'] = dp.get('osVersionNumber', '')       # 예: 17.7.11
    return info


def _ver(s):
    return tuple(int(x) for x in str(s).split('.') if x.isdigit())


def os_match(want, have):
    """want: "14"(그 버전 — 앞자리가 같으면 된다, 17.7 ↔ 17.7.11) · ">=16" · "<=15" """
    if not have:
        return False
    w = str(want).strip()
    for op in ('>=', '<='):
        if w.startswith(op):
            a, b = _ver(have), _ver(w[2:])
            return a >= b if op == '>=' else a[:len(b)] <= b
    return _ver(have)[:len(_ver(w))] == _ver(w)


def device_match(cond, platform, info):
    """checkpoint 의 device 조건 → (맞는가, 설명). cond = {"aos": {"model": [...], "os": [...]}, "ios": {...}}
    그 플랫폼 항목이 없으면 이 플랫폼에서는 확인하지 않는 줄이다."""
    have = f'{info.get("model") or "?"}{" (" + info["name"] + ")" if info.get("name") else ""} · OS {info.get("os") or "?"}'
    c = (cond or {}).get(platform)
    if c is None:
        return False, f'이 플랫폼({platform})에서 확인하지 않는 줄 — 실행 기기 {have}'
    models = [m.lower() for m in (c.get('model') or [])]
    if models and (info.get('model') or '').lower() not in models and (info.get('name') or '').lower() not in models:
        return False, f'조건 기기({", ".join(c["model"])})가 아니다 — 실행 기기 {have}'
    oses = c.get('os') or []
    if isinstance(oses, str):
        oses = [oses]
    if oses and not any(os_match(w, info.get('os')) for w in oses):
        return False, f'조건 OS({", ".join(map(str, oses))})가 아니다 — 실행 기기 {have}'
    return True, f'조건 기기에서 실행 — {have}'


# --- 케이스 파일 검사----------------------------------------------------------
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
        resume = c.get('resume')
        if resume is not None:
            # start: here 인 케이스가 앞 케이스 실패로 엉뚱한 화면에서 시작하지 않게 — 그때만 resume 의 start·steps 로 들어간다
            if resume.get('start', 'lobby') not in ('relaunch', 'lobby'):
                errs.append(f'{where}: resume.start 는 relaunch 또는 lobby')
            for i, s in enumerate(resume.get('steps') or []):
                if s.get('do') not in STEP_KEYS:
                    errs.append(f'{where} resume step {i}: do={s.get("do")!r} 는 모르는 동작')
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
            if do == 'play' and not suite.get('autoplay'):
                errs.append(f'{where} step {i} (play): 케이스 파일 머리에 autoplay(자동 달리기 input)가 필요 — 기본 기능은 kit/presets/basic-play.json')
            if do == 'play' and not isinstance(s.get('timeout', 600), (int, float)):
                errs.append(f'{where} step {i} (play): timeout 은 초(숫자)')
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
                    for item in exp.get('order', []):
                        qc.normalize(item['select'])
                        if not any(k in item for k in ('first', 'notFirst', 'sameAs')):
                            raise ValueError('order 에는 first·notFirst·sameAs 중 하나가 필요')
                        if item.get('sameAs') and item['sameAs'] not in names - {s.get('name')}:
                            raise ValueError(f'order.sameAs 「{item["sameAs"]}」 는 이 checkpoint 보다 앞에 있어야 한다')
                    for sel in s.get('mask', []):
                        qc.normalize(sel)
                    if s.get('image', True) not in (True, False, 'capture'):
                        raise ValueError('image 는 true(캡처·비교) · false(캡처 안 함) · "capture"(캡처만, 비교 안 함)')
                    if 'device' in s:
                        dc = s['device']
                        if not isinstance(dc, dict) or not dc or any(k not in ('aos', 'ios') for k in dc):
                            raise ValueError('device 는 {"aos": {"model": [...], "os": [...]}, "ios": {...}}')
                        for k, v in dc.items():
                            if not isinstance(v, dict) or any(x not in ('model', 'os') for x in v) or not v:
                                raise ValueError(f'device.{k} 는 model(목록)·os(목록 — "14" · ">=16")')
                except (ValueError, KeyError, TypeError) as e:
                    errs.append(f'{where} checkpoint {s.get("name")}: {e}')
            for key in ('select',):
                if key in s:
                    try:
                        qc.normalize(s[key])
                    except ValueError as e:
                        errs.append(f'{where} step {i}: {e}')
            if 'when' in s:
                w = s['when']
                if do == 'checkpoint':
                    errs.append(f'{where} step {i}: checkpoint 에는 when 을 쓰지 않는다(판정 지점은 늘 지난다)')
                elif not isinstance(w, dict) or not w or any(k not in ('present', 'absent') for k in w):
                    errs.append(f'{where} step {i}: when 은 {{"present": 선택자}} 또는 {{"absent": 선택자}}')
                else:
                    try:
                        for sel in w.values():
                            qc.normalize(sel)
                    except ValueError as e:
                        errs.append(f'{where} step {i} when: {e}')
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
        # 인게임 자동 달리기 설정(게임 AutoRewind 의 input). 있으면 케이스마다 켜 두어 인게임에 들어가는 순간 그 방식으로 달린다
        self.autoplay = suite.get('autoplay')

    def nodes(self, tree=None):
        return qc.visible(tree if tree is not None else self.dev.tree())

    def run_case(self, case, relaunch_first=False):
        from flowlib import FlowFailure
        import routes
        res = {'id': case['id'], 'title': case.get('title', ''), 'verdict': None, 'checkpoints': [], 'actions': [], 'error': None,
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
        self.cp_nodes = {}   # 이 케이스에서 지난 checkpoint 의 노드(order.sameAs 비교용)
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
            if self.autoplay:
                res['autoplay'] = self.arm_autoplay()
            for i, step in enumerate(case.get('steps', [])):
                current = i
                self.step(case, i, step, res)
                if step.get('do') == 'checkpoint' and res['checkpoints']:
                    res['checkpoints'][-1]['step'] = i
                elif step.get('do') in ACTION_STEPS and not any(x.get('step') == i for x in res.get('skipped', [])):
                    # 화면이 멈출 때까지만 기다린다(고정 대기 없음). when 으로 건너뛴 단계는 기다리지도 찍지도 않는다
                    if step.get('do') != 'scroll_find':
                        self.settle(step.get('settle', ACTION_SETTLE))
                    if getattr(self, 'capture_actions', False):
                        self.capture_action(i, step, res, 'DONE')
        except FlowFailure as e:
            res['error'] = {'kind': e.kind, 'step': e.step, 'detail': e.detail, 'shot': self.dev.shot('failure'),
                            'shotError': getattr(self.dev, 'shot_error', None)}
            steps = case.get('steps', [])
            if getattr(self, 'capture_actions', False) and 'current' in locals() and current < len(steps):
                # 멈춘 액션 — 실패 시점 캡처를 그 액션의 캡처로 쓴다
                res['actions'].append({'step': current, 'do': steps[current].get('do'), 'label': self.action_label(steps[current]),
                                       'verdict': 'FAILED', 'scene': None, 'shot': res['error']['shot'],
                                       'detail': f'{e.kind}: {e.detail}'})
        except Exception as e:  # noqa: BLE001 — 케이스 하나의 예외로 묶음 전체를 멈추지 않는다
            res['error'] = {'kind': 'RUNNER', 'step': '', 'detail': f'{type(e).__name__}: {e}', 'shot': None}
        finally:
            self.restore_state(res)
        cps = [c['verdict'] for c in res['checkpoints']]
        res['verdict'] = 'ERROR' if res['error'] else qc.worst(cps)
        skipped = [c for c in res['checkpoints'] if c.get('verdict') == 'NOT_RUN' and c.get('device')]
        if skipped and not res['error']:
            judged = [c for c in res['checkpoints'] if c not in skipped]
            if not judged:
                # 판정 줄이 모두 다른 기기용 — 이 실행은 이 TC 를 확인하지 않았다(시트 칸을 건드리지 않는다)
                res['verdict'] = 'NOT_RUN'
                res['reason'] = '조건 기기가 아니라 확인하지 않음 — ' + '; '.join(f'{c["name"]}: {c["device"]}' for c in skipped)
            elif res['verdict'] == 'PASS':
                # 일부 줄만 이 기기에서 확인 — 통과로 쓰지 않고 Check 로 남긴다(나머지 줄은 조건 기기에서 따로 본다)
                res['verdict'] = 'UNSURE'
                res['reason'] = '일부 줄만 이 기기에서 확인: ' + ', '.join(c['name'] for c in skipped) + ' 는 조건 기기 필요'
        if case.get('partial'):
            res['partial'] = case['partial']   # 시트에 쓸 때 줄을 합쳐도 Pass 로 올리지 않게 남긴다
        if case.get('partial') and res['verdict'] == 'PASS':
            # 시트 기대 중 일부만 확인한 케이스 — 통과로 쓰지 않고 사람 확인(Check)으로 남긴다
            res['verdict'] = 'UNSURE'
            res['reason'] = f'일부만 자동 확인: {case["partial"]}'
        return res

    @staticmethod
    def action_label(s):
        if s.get('label'):
            return s['label']
        do = s.get('do')
        what = s.get('target') or s.get('name') or s.get('owner') or ''
        if not what and s.get('select') is not None:
            what = qc.describe(s['select'])
        if not what and do == 'tap_xy':
            what = f'{s.get("x")},{s.get("y")}'
        return f'{do} {what}'.strip()

    def settle(self, max_s):
        """화면 트리(위치·글자·투명도·보임)가 연속 두 번 같을 때까지, 최대 max_s 초 기다린다. 마지막 트리를 돌려준다.
        고정 시간을 쉬는 대신 화면이 멈추면 바로 넘어간다. 계속 움직이는 화면이면 max_s 에서 끝난다(예전 고정 대기와 같다)."""
        end = time.time() + max(0.0, float(max_s))
        prev = None
        while True:
            tree = self.dev.tree()
            sig = tree_signature(tree)
            if sig == prev or time.time() >= end:
                return tree
            prev = sig
            time.sleep(SETTLE_POLL)

    def tap_retry(self, fn, label, timeout):
        """누를 노드가 아직 없거나(NAME_MISSING) 다른 것에 덮여 있으면(BLOCKED) — 화면 전환 중이다 — timeout 동안 다시 시도한다."""
        from flowlib import FlowFailure
        end = time.time() + timeout
        while True:
            try:
                return fn()
            except FlowFailure as e:
                if e.kind not in ('NAME_MISSING', 'BLOCKED') or time.time() >= end:
                    raise
            time.sleep(SETTLE_POLL)

    def scroll_find(self, s, label):
        """목록에서 select 가 보이는 영역(band 높이 범위) 안에 나올 때까지 찾는다.
        게임 브리지에 scroll 명령이 있으면 목록 처음으로 간 뒤 한 쪽씩 정확히 넘긴다(관성 없음, 끝에 닿으면 바로 실패).
        없으면(예전 빌드) 손가락처럼 스와이프한다."""
        from flowlib import FlowFailure
        dev = self.dev
        w, h = dev.visible_size()
        lo, hi = [coord(v, h) for v in s.get('band', ['5%', '85%'])]
        target = ['--node', s['list']] if s.get('list') else []

        def hits(tree=None):
            return [n for n in qc.select(self.nodes(tree), s['select']) if n.get('rect')]

        def in_band(found):
            return [n for n in found if lo <= n['rect'][1] <= hi]

        r = dev.call('scroll', '--to', 'start', *target)
        if r.get('ok'):
            for _ in range(int(s.get('max', 40))):
                found = hits(dev.tree())   # 관성 없이 옮겼다 — 트리는 바로 새 칸을 보여 준다
                if in_band(found):
                    self.settle(0.6)
                    return
                if found:
                    # 보이긴 하는데 띠 밖(머리글 밑·아래 끝) — 띠 가운데로 정확히 옮긴다. 양수 by 는 내용을 위로 올린다
                    n = found[0]
                    r = dev.call('scroll', '--by', f'{(lo + hi) / 2 - (n["rect"][1] + n["rect"][3] / 2):.1f}', *target)
                    if r.get('ok') and hits(dev.tree()):
                        self.settle(0.6)
                        return
                if (r.get('result') or {}).get('atEnd'):
                    break
                r = dev.call('scroll', '--pages', str(s.get('page', 0.8)), *target)
                if not r.get('ok'):
                    raise FlowFailure('BRIDGE', label, f'scroll: {r.get("error")}')
            raise FlowFailure('NOT_REACHED', label, f'목록 끝까지 넘겨도 {qc.describe(s["select"])} 가 나오지 않았다')
        if 'unknown cmd' not in str(r.get('error')) and 'invalid choice' not in str(r.get('error')):
            raise FlowFailure('BRIDGE', label, f'scroll: {r.get("error")}')
        sw = s.get('swipe', {'x1': '55%', 'y1': '20%', 'x2': '55%', 'y2': '55%'})
        for _ in range(int(s.get('max', 40))):
            if in_band(hits()):
                return
            dev.swipe(coord(sw['x1'], w), coord(sw['y1'], h), coord(sw['x2'], w), coord(sw['y2'], h), s.get('ms', 400))
            self.settle(1.2)   # 관성 스크롤이 멈추면 바로 다시 읽는다
        raise FlowFailure('NOT_REACHED', label, f'목록을 넘겨도 {qc.describe(s["select"])} 가 나오지 않았다')

    def capture_action(self, i, s, res, verdict):
        shot = self.dev.shot(f'step{i:02d}-{s.get("do")}')
        res['actions'].append({'step': i, 'do': s.get('do'), 'label': self.action_label(s), 'verdict': verdict,
                               'scene': self.dev.scene(), 'shot': shot})

    def step(self, case, i, s, res):
        from flowlib import FlowFailure
        import routes
        dev = self.dev
        do = s['do']
        label = s.get('label') or f'{do} #{i}'
        timeout = s.get('timeout', 15)
        if s.get('when') and not qc.check_when(s['when'], self.nodes()):
            # 조건이 맞지 않으면 이 단계는 건너뛴다(예: 토글이 이미 원하는 상태)
            res.setdefault('skipped', []).append({'step': i, 'label': label, 'when': s['when']})
            return
        find_wait = float(s.get('find_wait', FIND_WAIT))
        if do == 'tap':
            self.tap_retry(lambda: dev.tap(s['target'], label, s.get('index')), label, find_wait)
        elif do == 'tap_select':
            def tap_hit():
                hit = qc.select(self.nodes(), s['select'])
                if not hit:
                    raise FlowFailure('NAME_MISSING', label, f'{qc.describe(s["select"])} 가 트리에 없다 (scene={dev.scene()})')
                return dev.tap_node(hit[s.get('index', -1)], label)
            self.tap_retry(tap_hit, label, find_wait)
        elif do == 'tap_xy':
            w, h = dev.visible_size()
            dev.tap_xy(coord(s['x'], w), coord(s['y'], h), label)
        elif do == 'back':
            self.tap_retry(lambda: dev.tap('_btnBack', label), label, find_wait)
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
            self.scroll_find(s, label)
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
        elif do == 'play':
            self.play(s, label, res)
        elif do == 'checkpoint':
            if s.get('device'):
                ok, why = device_match(s['device'], self.platform, getattr(self, 'device_info', {}) or {})
                if not ok:
                    # 조건 기기가 아니면 이 줄은 판정하지 않는다(실패가 아니다) — 다른 기기에서 돌린 결과로 채운다
                    res['checkpoints'].append({'name': s['name'], 'verdict': 'NOT_RUN', 'device': why, 'checks': [], 'shot': None})
                    return
                res.setdefault('deviceChecked', []).append({'name': s['name'], 'device': why})
            # settle 은 이제 「최대」 기다리는 시간이다 — 화면이 멈추면 바로 확인한다(목록 등장 연출이 끝나기를 기다린다)
            tree = self.settle(float(s.get('settle', 1.0))) if s.get('settle', 1.0) else None
            res['checkpoints'].append(self.checkpoint(case, s, tree))
        if s.get('after'):
            time.sleep(float(s['after']))

    # --- 인게임 자동 달리기 ---
    def bridge(self, cmd, **fields):
        return self.dev.call(cmd, '--json', json.dumps(fields))

    def arm_autoplay(self):
        """게임 AutoRewind 에 자동 달리기를 켜 둔다 — 되감기 트리거 없이 입력(피하기·구멍 구출·이어달리기)만.
        이미 켜져 있으면 다시 보내지 않는다(달리는 중에 다시 보내면 그 판의 배운 값이 초기화된다).
        자동 되감기 모듈이 없는 빌드면 켜지 못한 이유를 돌려주고 케이스는 계속 돈다."""
        r = self.bridge('autorewind', op='status')
        st = r.get('result') or {}
        if r.get('ok') and st.get('enabled') and st.get('input'):
            return 'on'
        fields = {'triggers': [], 'infiniteRewind': False,
                  'input': dict(self.autoplay, seed=int(self.autoplay.get('seed') or time.time()) % 1000000007)}
        r = self.bridge('autorewind', op='set', **fields)
        return 'on' if r.get('ok') else f'켜지 못함: {r.get("error")}'

    def play(self, s, label, res):
        """인게임 한 판을 자동 달리기로 끝까지 달린다. 인게임 진입은 앞 단계가 하고, 이 단계는 시작을 기다린 뒤
        판이 끝나 결과 화면이 나올 때까지 이벤트를 모은다. timeout(달린 시간, 기본 600초)을 넘으면 그만두기로 끝낸다."""
        from flowlib import FlowFailure
        if not self.autoplay:
            raise FlowFailure('RUNNER', label, '자동 달리기 설정(suite autoplay)이 없다 — 기본 기능 실행기(basic_run)로 돌린다')
        armed = self.arm_autoplay()
        if armed != 'on':
            raise FlowFailure('BRIDGE', label, f'자동 달리기를 {armed}')
        limit = float(s.get('timeout', 600))
        st = (self.bridge('autorewind', op='status').get('result') or {})
        since = int(st.get('lastEvent') or 0)
        events, started, run_deadline, ended_at, quit_at, misses = [], bool(st.get('inGame')), None, None, None, 0
        start_wait = float(s.get('start_timeout', PLAY_START_WAIT))
        start_deadline = time.time() + start_wait
        if started:
            run_deadline = time.time() + limit
        while True:
            now = time.time()
            if not started and now > start_deadline:
                raise FlowFailure('NOT_REACHED', label, f'{int(start_wait)}s 안에 인게임이 시작되지 않았다 (scene={self.dev.scene()})')
            if run_deadline and now > run_deadline and quit_at is None and ended_at is None:
                quit_at = now
                self.bridge('autorewind', op='quit')
            if quit_at and ended_at is None and now - quit_at > 90:
                raise FlowFailure('NOT_REACHED', label, f'제한 {int(limit)}초 뒤 그만두기를 보냈지만 판이 끝나지 않았다 (scene={self.dev.scene()})')
            if ended_at and now - ended_at > 90:
                raise FlowFailure('NOT_REACHED', label, f'판이 끝났지만 90초 안에 결과 화면이 나오지 않았다 (scene={self.dev.scene()})')
            r = self.bridge('autorewind', op='events', since=since)
            if not r.get('ok'):
                misses += 1
                if misses >= 5 and not self.dev.call('ping').get('ok'):
                    raise FlowFailure('BRIDGE', label, '판 도중 앱이 응답하지 않는다(종료 의심)')
                time.sleep(PLAY_POLL)
                continue
            misses = 0
            for e in r['result'].get('events') or []:
                events.append(e)
                if e['type'] == 'game_start' and not started:
                    started, run_deadline = True, time.time() + limit
                if e['type'] in PLAY_END_EVENTS and ended_at is None:
                    ended_at = time.time()
            since = r['result'].get('next', since)
            if any(e['type'] == 'result_screen' for e in events):
                break
            time.sleep(PLAY_POLL)
        types = [e['type'] for e in events]
        over = next((e for e in events if e['type'] in PLAY_END_EVENTS), {})
        res.setdefault('plays', []).append({
            'label': label, 'end': over.get('type', ''), 'playSec': round(float(over.get('t') or 0), 1), 'jelly': over.get('jelly'),
            'revive': types.count('revive'), 'rescue': types.count('rescue_click'), 'relay': types.count('relay_click'),
            'bonus': types.count('bonus_enter'), 'stoppedByLimit': quit_at is not None,
            'result': next((e.get('scene') for e in events if e['type'] == 'result_screen'), ''),
            'skips': sorted({e.get('reason', '') for e in events if e['type'] == 'rewind_skip'} - {''})})

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

    def checkpoint(self, case, s, tree=None):
        dev = self.dev
        name = s['name']
        tree = tree if tree is not None else dev.tree()
        nodes = self.nodes(tree)
        scene = dev.scene()
        geometry = dev.call('ping').get('result', {})
        shot = dev.shot(name) if s.get('image', True) else None
        prior = getattr(self, 'cp_nodes', {})
        cp = {'name': name, 'scene': scene, 'shot': shot,
              'checks': qc.check_expect(s.get('expect'), scene, nodes, prior),
              'baseline': None, 'diff': None, 'verdict': None}
        prior[name] = nodes
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
        if s.get('image') == 'capture':
            # 캡처만 남기고 그림 비교는 하지 않는다(로비처럼 매번 달라지는 화면 — 판정은 조건으로만)
            cp['baseline'] = 'off'
            cp['verdict'] = 'PASS'
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


def server_for_preset(preset):
    """실행 프리셋이 곧 테스트 중인 서버다 — 마카롱·타임머신 주소를 케이스 파일의 server 가 아니라 이 이름으로 만든다.
    서버 이름 꼴(gb-…)이 아닌 프리셋이면 None(케이스 파일의 server 를 그대로 쓴다)."""
    return preset if re.fullmatch(r'gb-[a-z0-9-]+', preset or '') else None


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
    ap.add_argument('--no-action-capture', action='store_true', help='액션(누르기·드래그 등)마다 화면을 찍지 않는다')
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
        server = server_for_preset(a.preset)
        if server and suite.get('server') != server:
            if suite.get('server'):
                print(f'마카롱·타임머신 서버를 케이스 파일의 {suite["server"]} 대신 실행 프리셋 {server} 로 쓴다', flush=True)
            suite['server'] = server
    from flowlib import Device
    stamp = time.strftime('%Y%m%d-%H%M%S')
    name = suite.get('suite') or os.path.splitext(os.path.basename(a.suite_file))[0]
    suite['suite'] = name
    out = a.out or os.path.join(qc.RUNS, f'{name}-{a.platform}-{stamp}')
    dev = Device(a.platform, qc.WORKSPACE, out, a.device)
    runner = Runner(dev, suite, a.platform, out, a.allow_spend)
    runner.capture_actions = not a.no_action_capture
    runner.allow_time = a.allow_time and bool(suite.get('time_ok'))
    runner.device_info = device_info(a.platform, dev.device_id) if a.platform in ('aos', 'ios') else {}
    results = {'suite': name, 'sheet': suite.get('sheet', ''), 'platform': a.platform, 'device': a.device or dev.device_id,
               'deviceInfo': runner.device_info, 'started': stamp, 'suiteFile': os.path.abspath(a.suite_file), 'cases': []}
    if runner.device_info:
        di = runner.device_info
        print(f'[{a.platform}] 기기: {di.get("model") or "?"} {di.get("name") or ""} · OS {di.get("os") or "?"}', flush=True)
    # 게임이 연결 모드로 떠 있지 않으면 되감기처럼 첫 케이스 전에 앱을 띄워 로비까지 간다(서버 프리셋·제목 영상 처리 포함)
    first = a.relaunch or dev.call('ping').get('ok') is not True
    if first and not a.relaunch:
        print(f'[{a.platform}] 게임 연결이 없어 앱을 연결 모드로 띄우고 로비까지 간다', flush=True)
    aborted = None
    prev_clean = False   # 바로 앞 케이스가 오류 없이 끝났는가 — start: here 케이스가 그 화면을 이어받아도 되는가
    for case in cases:
        if aborted:
            r = {'id': case['id'], 'title': case.get('title', ''), 'verdict': 'ERROR', 'checkpoints': [], 'reason': '',
                 'error': {'kind': 'BRIDGE', 'step': '-', 'detail': f'앞에서 기기 연결이 끊겨 돌리지 않았다 ({aborted})', 'shot': None}}
            results['cases'].append(r)
            print(f'[{a.platform}] ERROR   {case["id"]} — 연결이 끊겨 건너뜀', flush=True)
            continue
        run = case
        if case.get('start') == 'here' and case.get('resume') and (first or not prev_clean):
            rs = case['resume']
            run = dict(case, start=rs.get('start', 'lobby'), steps=list(rs.get('steps') or []) + list(case.get('steps') or []))
            print(f'[{a.platform}] {case["id"]} — 앞 구간이 끝까지 가지 못해 시작 화면부터 다시 들어간다', flush=True)
        r = runner.run_case(run, relaunch_first=first)
        if run is not case:
            r['resumed'] = len(case['resume'].get('steps') or [])
        if r['verdict'] not in ('NOT_RUN',):
            first = False
            prev_clean = not r.get('error')
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
