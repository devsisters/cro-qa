#!/usr/bin/env python3
"""시나리오 파일(scenarios/<탭>/<TC 키>.json)을 하나 이상 돌린다. 케이스 실행기(case_runner.py)에 그대로 넘긴다.

  python3 tools/scenario_run.py <시나리오.json> [<시나리오.json> ...] --platform ios|aos [--check]
                                [--preset NAME] [--relaunch] [--allow-spend] [--allow-time] [--device ID] [--out DIR]

시나리오의 case(단계)를 케이스 하나로, 여러 파일이면 한 묶음으로 모아 임시 묶음 파일(runs/_scenario-suite.json)을 만든다.
케이스 id 는 TC 키다. checkpoint 의 정답(채점표)은 scenarios/<탭>/<키>/<플랫폼>/ 에서 찾는다(tools/scenario_capture.py 가 만든다).
돌린 뒤 마지막 결과(판정·지점별 판정·실행 폴더)를 이 컴퓨터에만 적는다 — workspace/scenario-runs/<탭>/<키>.json.
실행 폴더(runs/)는 공유하지 않으므로 마지막 결과도 시나리오 파일(공유)에 넣지 않는다.
--check 는 형식만 검사한다. exit 는 case_runner 와 같다(0 통과 · 1 FAIL/REVIEW · 2 형식 오류 · 3 ERROR).
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_common as qc  # noqa: E402


def apply_scoring(steps, scoring):
    """채점표를 같은 이름의 checkpoint 단계에 붙인다. 확정된 조건만 expect 에 더하고, 확정 전·사람 확인 지점은 표시만 한다."""
    by_name = {p.get('name'): p for p in scoring}
    out = []
    for s in steps:
        p = by_name.get(s.get('name')) if s.get('do') == 'checkpoint' else None
        if p:
            s = dict(s)
            if p.get('confirmed'):
                exp = dict(s.get('expect') or {})
                for k, v in (p.get('expect') or {}).items():
                    if isinstance(v, list):
                        exp[k] = list(exp.get(k) or []) + [x for x in v if x not in (exp.get(k) or [])]
                    else:
                        exp[k] = v
                s['expect'] = exp
            s['mask'] = list(s.get('mask') or []) + [m for m in p.get('mask') or [] if m not in (s.get('mask') or [])]
            s['scoring'] = {'compareImage': bool(p.get('compareImage')), 'unconfirmed': not p.get('confirmed'),
                            'human': (p.get('humanNote') or p.get('label') or '사람이 캡처를 보고 판단') if p.get('human') else ''}
        out.append(s)
    return out


def build_suite(files):
    cases, server, time_ok = [], '', False
    for path in files:
        data = qc.load_json(path)
        case = dict(data.get('case') or {})
        case['id'] = data.get('key') or os.path.splitext(os.path.basename(path))[0]
        case['answersDir'] = os.path.splitext(os.path.abspath(path))[0]
        case['steps'] = apply_scoring(case.get('steps') or [], data.get('scoring') or [])
        tc = data.get('tc') or {}
        path_text = ' / '.join(v for v in (tc.get('main'), tc.get('sub1'), tc.get('sub2'), tc.get('sub3')) if v)
        case.setdefault('title', f'{data.get("tab", "")} No.{data.get("no", "")} {path_text}'.strip())
        case.setdefault('auto', True)
        case.setdefault('sheet', {'expected': tc.get('expected', '')})
        cases.append(case)
        server = server or data.get('server', '')
        time_ok = time_ok or bool(data.get('time_ok'))
    suite = {'suite': 'scenario', 'kind': 'outgame', 'cases': cases}
    if server:
        suite['server'] = server
    if time_ok:
        suite['time_ok'] = True
    return suite


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--platform')
    ap.add_argument('--check', action='store_true')
    a, rest = ap.parse_known_args()
    suite = build_suite(a.files)
    os.makedirs(qc.RUNS, exist_ok=True)
    tmp = os.path.join(qc.RUNS, '_scenario-suite.json')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(suite, f, ensure_ascii=False, indent=1)
    out = None
    if not a.check and a.platform and '--out' not in rest:
        out = os.path.join(qc.RUNS, f'scenario-{a.platform}-{time.strftime("%Y%m%d-%H%M%S")}')
        rest = rest + ['--out', out]
    cmd = [sys.executable, os.path.join(HERE, 'case_runner.py'), tmp] + (['--check'] if a.check else []) \
        + (['--platform', a.platform] if a.platform else []) + rest
    code = subprocess.call(cmd)
    if out:
        record_last_run(a.files, a.platform, out)
        write_report(a.files, a.platform, out)
    return code


VERDICT_KO = {'PASS': '통과', 'FAIL': '실패', 'HUMAN': '사람 확인', 'REVIEW': '확인 필요', 'UNSURE': '확인 필요',
              'ERROR': '진행 실패', 'NOT_RUN': '미실행', 'DONE': '진행', 'FAILED': '진행 실패'}


def timeline(c):
    """액션 캡처와 채점 지점을 실행 순서대로 — [{kind, step, label, verdict, shot, ...}]"""
    items = [dict(x, kind='action') for x in c.get('actions', [])]
    items += [{'kind': 'checkpoint', 'step': cp.get('step', 10 ** 6), 'label': cp['name'], 'verdict': cp.get('verdict'),
               'shot': cp.get('shot'), 'checks': cp.get('checks', []), 'human': cp.get('human', '')} for cp in c.get('checkpoints', [])]
    return sorted(items, key=lambda x: (x.get('step') if x.get('step') is not None else 10 ** 6))


def attention(cases):
    """사람이 볼 것 — 실패한 채점 지점, 사람 확인 지점, 진행이 멈춘 액션"""
    out = []
    for c in cases:
        sc = c.get('scenario') or {}
        for x in timeline(c):
            if x['kind'] == 'checkpoint' and x['verdict'] in ('FAIL', 'HUMAN', 'REVIEW'):
                why = '; '.join(k['check'] for k in x.get('checks', []) if not k['ok']) or x.get('human') or '정답 그림과 차이'
                out.append({'case': c['id'], 'tab': sc.get('tab', ''), 'no': sc.get('no', ''), 'what': x['label'],
                            'verdict': x['verdict'], 'why': why, 'shot': x.get('shot')})
            elif x['kind'] == 'action' and x['verdict'] == 'FAILED':
                out.append({'case': c['id'], 'tab': sc.get('tab', ''), 'no': sc.get('no', ''), 'what': x['label'],
                            'verdict': 'FAILED', 'why': x.get('detail', ''), 'shot': x.get('shot')})
    return out


def write_report(files, platform, out):
    """results.json 에 시나리오(TC) 정보를 붙이고 report.md 를 쓴다 — 위에 TC 별 표, 아래에 지점별 캡처가 든 상세."""
    results_path = os.path.join(out, 'results.json')
    if not os.path.exists(results_path):
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(files[0]))) if files else ''
    info = {}
    for path in files:
        data = qc.load_json(path)
        tc = data.get('tc') or {}
        info[data.get('key') or os.path.splitext(os.path.basename(path))[0]] = {
            'tab': data.get('tab', ''), 'no': data.get('no', ''), 'section': tc.get('section', ''),
            'path': ' › '.join(v for v in (tc.get('main'), tc.get('sub1'), tc.get('sub2'), tc.get('sub3')) if v),
            'expected': tc.get('expected', ''), 'file': os.path.relpath(os.path.abspath(path), root) if root else path,
            'labels': {p.get('name'): p.get('label', '') for p in data.get('scoring') or []}}
    write_tc_report(out, platform, info, 'scenario', '아웃게임 시나리오')


def write_tc_report(out, platform, info, kind, title):
    """results.json 에 TC 정보(info: 케이스 id → tab·no·path·expected·file·labels)를 붙이고 report.md 를 쓴다.
    아웃게임 시나리오와 기본 기능 실행이 같이 쓴다 — 위에 TC 별 표, 「사람이 볼 것」, 아래에 흐름·캡처가 든 상세."""
    results_path = os.path.join(out, 'results.json')
    if not os.path.exists(results_path):
        return
    results = qc.load_json(results_path)
    results['kind'] = kind
    for c in results.get('cases', []):
        c['scenario'] = info.get(c['id'], {})
    qc.save_json(results_path, results)
    rel = lambda p: os.path.relpath(p, out).replace(' ', '%20') if p and os.path.isabs(p) else (p or '')
    cases = results.get('cases', [])
    counts = {}
    for c in cases:
        counts[c['verdict']] = counts.get(c['verdict'], 0) + 1
    L = [f'# {title} [{platform.upper()}]', '',
         f'TC {len(cases)} · ' + ' · '.join(f'{VERDICT_KO.get(v, v)} {n}' for v, n in counts.items()), '',
         '| 탭 | No | 분류 | 기대 결과 | 판정 | 사유 |', '|---|---|---|---|---|---|']
    for c in cases:
        sc = c.get('scenario') or {}
        reason = c.get('reason') or ''
        if c.get('error'):
            reason = f'{c["error"].get("kind")} at {c["error"].get("step")}: {c["error"].get("detail")}'
        bad = [f'{cp["name"]}: ' + '; '.join(x['check'] for x in cp.get('checks', []) if not x['ok'])
               for cp in c.get('checkpoints', []) if any(not x['ok'] for x in cp.get('checks', []))]
        human = [f'{cp["name"]}: {cp.get("human")}' for cp in c.get('checkpoints', []) if cp.get('verdict') == 'HUMAN']
        reason = ' / '.join(x for x in [reason] + bad + human if x)
        cell = lambda v: str(v).replace('|', '\\|').replace('\n', ' ')
        L.append(f'| {cell(sc.get("tab", ""))} | {cell(sc.get("no", ""))} | {cell(sc.get("path", ""))} | {cell(sc.get("expected", ""))} '
                 f'| {VERDICT_KO.get(c["verdict"], c["verdict"])} | {cell(reason) or "-"} |')
    look = attention(cases)
    results['attention'] = look
    qc.save_json(results_path, results)
    L += ['', '## 사람이 볼 것', '']
    if look:
        L += ['| 탭 | No | 지점·액션 | 판정 | 왜 | 캡처 |', '|---|---|---|---|---|---|']
        for x in look:
            L.append(f'| {cell(x["tab"])} | {cell(x["no"])} | {cell(x["what"])} | {VERDICT_KO.get(x["verdict"], x["verdict"])} | {cell(x["why"])} | '
                     + (f'![]({rel(x["shot"])})' if x.get('shot') else '-') + ' |')
    else:
        L.append('없음 — 모든 지점이 조건을 통과했고 사람 확인 지점이 없다.')
    L += ['', '## 상세', '']
    last_tab = None
    for c in cases:
        sc = c.get('scenario') or {}
        if kind == 'basic':
            # 기본 기능 — 시나리오(대분류) 아래에 TC 별 리포트
            if sc.get('tab') != last_tab:
                last_tab = sc.get('tab')
                L += [f'### 시나리오 {last_tab}', '']
            L += [f'#### {sc.get("no", c["id"])} — {VERDICT_KO.get(c["verdict"], c["verdict"])}', '']
        else:
            L += [f'### {sc.get("tab", "")} No.{sc.get("no", "")} — {VERDICT_KO.get(c["verdict"], c["verdict"])}', '']
        L += [
              f'- 분류: {sc.get("path", "")}', f'- 기대 결과: {sc.get("expected", "")}']
        if sc.get('file'):
            L.append(f'- 시나리오: `{sc["file"] if kind == "basic" else "scenarios/" + sc["file"]}`')
        if c.get('error'):
            e = c['error']
            L.append(f'- 진행 실패: {e.get("kind")} at {e.get("step")} — {e.get("detail")}')
            if e.get('shot'):
                L.append(f'  ![실패]({rel(e["shot"])})')
        L.append('- 흐름(실행 순서):')
        for n, x in enumerate(timeline(c), 1):
            if x['kind'] == 'checkpoint':
                label = (sc.get('labels') or {}).get(x['label'], '')
                L.append(f'  {n}. 채점 **{x["label"]}** {label} — {VERDICT_KO.get(x["verdict"], x["verdict"])}')
                for k in x.get('checks', []):
                    if not k['ok']:
                        L.append(f'     - ✗ {k["check"]} ({k["detail"]})')
                if x.get('human'):
                    L.append(f'     - 사람 확인: {x["human"]}')
            else:
                L.append(f'  {n}. 액션 {x["label"]} — {VERDICT_KO.get(x["verdict"], x["verdict"])}' + (f' ({x["detail"]})' if x.get('detail') else ''))
            if x.get('shot'):
                L.append(f'     ![{n}]({rel(x["shot"])})')
        L.append('')
    with open(os.path.join(out, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


LAST_RUNS = os.path.join(qc.WORKSPACE, 'scenario-runs')


def last_run_path(scenario_path, root=None):
    """시나리오 파일의 마지막 결과를 두는 곳(이 컴퓨터에만) — <root>/<탭 폴더>/<키>.json"""
    tab = os.path.basename(os.path.dirname(os.path.abspath(scenario_path)))
    return os.path.join(root or LAST_RUNS, tab, os.path.basename(scenario_path))


def record_last_run(files, platform, out, root=None):
    """실행 결과를 이 컴퓨터의 마지막 결과 파일에 적는다(앱의 채점표에 마지막 결과로 나온다).
    시나리오 파일은 공유되므로 건드리지 않는다. 예전 방식으로 시나리오 파일에 남은 lastRun 은 지운다."""
    results = os.path.join(out, 'results.json')
    if not os.path.exists(results):
        return
    by_id = {c['id']: c for c in qc.load_json(results).get('cases', [])}
    for path in files:
        data = qc.load_json(path)
        c = by_id.get(data.get('key') or os.path.splitext(os.path.basename(path))[0])
        if not c:
            continue
        last = {
            'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'platform': platform, 'verdict': c.get('verdict'),
            'reason': c.get('reason', ''), 'run': os.path.relpath(out, qc.KIT),
            'checkpoints': {cp['name']: {'verdict': cp.get('verdict'), 'shot': os.path.relpath(cp['shot'], qc.KIT) if cp.get('shot') else None,
                                         'failed': [x['check'] + f' ({x["detail"]})' for x in cp.get('checks', []) if not x['ok']],
                                         'human': cp.get('human', '')}
                            for cp in c.get('checkpoints', [])},
            'actions': [{'step': x.get('step'), 'label': x.get('label'), 'verdict': x.get('verdict'), 'scene': x.get('scene'),
                         'shot': os.path.relpath(x['shot'], qc.KIT) if x.get('shot') else None, 'detail': x.get('detail', '')}
                        for x in c.get('actions', [])],
            'error': (c.get('error') or {}).get('detail', '')}
        target = last_run_path(path, root)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(last, f, ensure_ascii=False, indent=1)
            f.write('\n')
        if 'lastRun' in data:
            data.pop('lastRun')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
                f.write('\n')


if __name__ == '__main__':
    sys.exit(main())
