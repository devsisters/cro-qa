#!/usr/bin/env python3
"""시나리오 파일(scenarios/<탭>/<TC 키>.json)을 하나 이상 돌린다. 케이스 실행기(case_runner.py)에 그대로 넘긴다.

  python3 tools/scenario_run.py <시나리오.json> [<시나리오.json> ...] --platform ios|aos [--check]
                                [--preset NAME] [--relaunch] [--allow-spend] [--allow-time] [--device ID] [--out DIR]

시나리오의 case(단계)를 케이스 하나로, 여러 파일이면 한 묶음으로 모아 임시 묶음 파일(runs/_scenario-suite.json)을 만든다.
케이스 id 는 TC 키다. checkpoint 의 정답(채점표)은 scenarios/<탭>/<키>/<플랫폼>/ 에서 찾는다(tools/scenario_capture.py 가 만든다).
돌린 뒤 각 시나리오 파일의 lastRun 에 결과(판정·지점별 판정·실행 폴더)를 적는다.
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


def build_suite(files):
    cases, server, time_ok = [], '', False
    for path in files:
        data = qc.load_json(path)
        case = dict(data.get('case') or {})
        case['id'] = data.get('key') or os.path.splitext(os.path.basename(path))[0]
        case['answersDir'] = os.path.splitext(os.path.abspath(path))[0]
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
    return code


def record_last_run(files, platform, out):
    """실행 결과를 시나리오 파일의 lastRun 에 적는다(앱의 채점표에 마지막 결과로 나온다)."""
    results = os.path.join(out, 'results.json')
    if not os.path.exists(results):
        return
    by_id = {c['id']: c for c in qc.load_json(results).get('cases', [])}
    for path in files:
        data = qc.load_json(path)
        c = by_id.get(data.get('key') or os.path.splitext(os.path.basename(path))[0])
        if not c:
            continue
        data['lastRun'] = {
            'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'platform': platform, 'verdict': c.get('verdict'),
            'reason': c.get('reason', ''), 'run': os.path.relpath(out, qc.KIT),
            'checkpoints': {cp['name']: {'verdict': cp.get('verdict'), 'shot': os.path.relpath(cp['shot'], qc.KIT) if cp.get('shot') else None}
                            for cp in c.get('checkpoints', [])}}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write('\n')


if __name__ == '__main__':
    sys.exit(main())
