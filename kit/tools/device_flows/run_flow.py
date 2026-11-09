#!/usr/bin/env python3
"""기기 플로우 실행기.

  python3 run_flow.py <flow> --platform mac|ios|aos --checkout <worktree> [--no-pull] [--out DIR]
  python3 run_flow.py --list

앱은 미리 `gb_device.py launch` 로 띄워 둔다(브리지·토큰). 결과는 <out>/<flow>-<platform>-<시각>.json 에
단계별 OK/FAIL 과, 실패면 분류(NAME_MISSING·BLOCKED·NOT_REACHED·BRIDGE)를 남긴다.
exit: 0 전 단계 통과, 1 확인 실패(화면은 갔는데 기대값이 다름), 2 사용법, 3 흐름 실패(분류 참고).
"""
import argparse
import importlib
import json
import os
import pkgutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'flows'))

from flowlib import Device, FlowFailure  # noqa: E402


def flows():
    return sorted(m.name for m in pkgutil.iter_modules([os.path.join(HERE, 'flows')]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('flow', nargs='?')
    ap.add_argument('--platform', choices=['mac', 'ios', 'aos'])
    ap.add_argument('--checkout')
    ap.add_argument('--device')
    ap.add_argument('--out')
    ap.add_argument('--no-pull', action='store_true', help='재화를 쓰는 뽑기 단계를 건너뛴다')
    ap.add_argument('--relaunch', action='store_true', help='앱을 새로 띄워 같은 시작 상태(프리셋 화면)에서 시작한다')
    ap.add_argument('--states', action='store_true', help='마카롱으로 계정 상태를 바꿔 보는 단계를 켠다(Aside 로그인 필요)')
    ap.add_argument('--preset', help='프리셋 화면에서 고를 프리셋 이름(기본 routes.PRESET)')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    if a.list:
        for name in flows():
            mod = importlib.import_module(name)
            print(f'{name}\t{getattr(mod, "FIGMA", "")}')
        return 0
    if not (a.flow and a.platform and a.checkout) or a.flow not in flows():
        ap.print_usage(sys.stderr)
        print(f'flows: {flows()}', file=sys.stderr)
        return 2
    if a.preset:
        import routes
        routes.PRESET = a.preset
    mod = importlib.import_module(a.flow)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = a.out or os.path.join(a.checkout, '.gb-agent', 'runs', 'device-flows', f'{a.flow}-{a.platform}-{stamp}')
    dev = Device(a.platform, os.path.abspath(a.checkout), out, a.device)
    report = {'flow': a.flow, 'figma': getattr(mod, 'FIGMA', ''), 'platform': a.platform, 'started': stamp,
              'checks': [], 'skips': getattr(mod, 'SKIPS', []), 'failure': None}

    def check(step, ok, detail='', shot=None):
        report['checks'].append({'step': step, 'ok': bool(ok), 'detail': detail, 'shot': shot})
        print(f'[{a.platform}] {"OK  " if ok else "FAIL"} {step} {detail}', flush=True)

    code = 0
    try:
        if a.relaunch:
            r = dev.call('launch', '--restart')
            if not r.get('ok'):
                raise FlowFailure('BRIDGE', 'relaunch', r.get('error'))
            dev.wait(lambda: dev.call('ping').get('ok'), 60, 'relaunch', '브리지 응답')
        kwargs = {'states': True} if a.states else {}
        mod.run(dev, check, pull=not a.no_pull, **kwargs)
    except FlowFailure as e:
        report['failure'] = {'kind': e.kind, 'step': e.step, 'detail': e.detail, 'shot': dev.shot('failure')}
        print(f'[{a.platform}] FLOW {e.kind} at {e.step}: {e.detail}', flush=True)
        code = 3
    if code == 0 and not all(c['ok'] for c in report['checks']):
        code = 1
    report['taps'] = dev.log
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, 'report.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({'ok': code == 0, 'exit': code, 'report': path}, ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
