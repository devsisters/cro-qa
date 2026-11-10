#!/usr/bin/env python3
"""기본 기능 시나리오를 돌린다 — 고른 시나리오(basic/scenarios/…json)를 TC 구간마다 케이스로 바꿔 case_runner 로 실행한다.

  python3 tools/basic_run.py --platform ios|aos --version 14.50 <시나리오.json> [<시나리오.json> ...] [--preset NAME] [--relaunch] [--device ID]
  python3 tools/basic_run.py --check <시나리오.json> [...]        # 형식만(기기 없음)

시나리오 하나는 대분류 하나(모드리스트는 중분류 하나)다. 안의 TC 구간이 차례로 돌고, 판정은 TC 별로 나온다.
결과: runs/basic-<버전>-<플랫폼>-<시각>/ — results.json(TC·시나리오 정보 포함) · report.md · basic.json(버전·플랫폼·실행자·시나리오)
시트에 쓰는 것은 이 도구가 하지 않는다. tools/basic_sheet.py update 로 쓸 칸을 정하고 에이전트가 쓴다(basic/README.md).
exit 는 case_runner 와 같다(0 통과 · 1 FAIL/REVIEW · 2 형식·사용법 · 3 ERROR)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import basic_scenario  # noqa: E402
import basic_sheet  # noqa: E402
import qa_common as qc  # noqa: E402
import scenario_run  # noqa: E402


def git_user():
    try:
        return subprocess.run(['git', 'config', 'user.name'], capture_output=True, text=True, cwd=qc.KIT, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--platform', choices=('ios', 'aos'))
    ap.add_argument('--version')
    ap.add_argument('--check', action='store_true')
    a, rest = ap.parse_known_args()
    files = [os.path.abspath(f) for f in a.files]
    root = os.path.abspath(basic_scenario.SCEN_DIR) + os.sep
    bad = [f for f in files if not f.startswith(root) or not f.endswith('.json') or not os.path.exists(f)]
    if bad:
        print(json.dumps({'ok': False, 'error': f'basic/scenarios 안의 시나리오 파일이 아니다: {bad}'}, ensure_ascii=False))
        return 2
    tcs = basic_scenario.load_tcs()
    by_id = {t['id']: t for t in tcs}
    errs = []
    for f in files:
        errs += basic_scenario.check(qc.load_json(f), f, by_id)
    suite = basic_scenario.build_suite(files, tcs)
    os.makedirs(qc.RUNS, exist_ok=True)
    tmp = os.path.join(qc.RUNS, f'_basic-suite-{a.platform or "check"}.json')   # 플랫폼마다 따로 — 두 기기를 동시에 돌린다
    qc.save_json(tmp, suite)
    if a.check:
        if errs:
            print(json.dumps({'ok': False, 'errors': errs}, ensure_ascii=False, indent=1))
            return 2
        return subprocess.call([sys.executable, os.path.join(HERE, 'case_runner.py'), tmp, '--check'])
    if errs:
        print(json.dumps({'ok': False, 'errors': errs}, ensure_ascii=False, indent=1))
        return 2
    version = (a.version or '').strip()
    if not a.platform or not re.fullmatch(r'[\w.\- ]{1,40}', version):
        print(json.dumps({'ok': False, 'error': f'--platform 과 --version(예: 14.50)이 필요하다: {version!r}'}, ensure_ascii=False))
        return 2
    out = os.path.join(qc.RUNS, f'basic-{version.replace(" ", "_")}-{a.platform}-{time.strftime("%Y%m%d-%H%M%S")}')
    os.makedirs(out, exist_ok=True)
    info = basic_scenario.info_for(files, tcs)
    meta = {'version': version, 'platform': a.platform, 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'by': git_user(),
            'sheet': basic_sheet.sheet_info().get('url', ''),
            'scenarios': [os.path.relpath(f, basic_scenario.REPO) for f in files], 'cases': [c['id'] for c in suite['cases']]}
    qc.save_json(os.path.join(out, 'basic.json'), meta)
    code = subprocess.call([sys.executable, os.path.join(HERE, 'case_runner.py'), tmp, '--platform', a.platform, '--out', out] + rest)
    scenario_run.write_tc_report(out, a.platform, info, 'basic', f'기본 기능 {version}')
    return code


if __name__ == '__main__':
    sys.exit(main())
