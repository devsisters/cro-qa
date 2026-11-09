#!/usr/bin/env python3
"""이 맥에서 자동화 테스트를 돌릴 수 있는지 점검한다. 고치지 않고 보기만 한다.

  python3 tools/doctor.py [--ping] [--web]   # --ping: 앱 브리지 응답, --web: 키트 Chrome 의 stove 로그인(QA_SERVER 서버 시간 조회)

출력: 항목별 OK/FAIL/WARN 과 고치는 법. exit 0 = FAIL 없음, 1 = FAIL 있음
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_common as qc  # noqa: E402

rows = []


def add(item, status, detail, fix=''):
    rows.append({'item': item, 'status': status, 'detail': detail, 'fix': fix})


def run(cmd, env=None, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, '', str(e)


def developer_dir():
    code, out, _ = run(['/bin/bash', '-c', f'source "{os.path.join(qc.WORKSPACE, ".gb-agent", "env.sh")}"; echo "$DEVELOPER_DIR"'])
    return out.strip()


def main():
    ping = '--ping' in sys.argv
    add('python3', 'OK' if sys.version_info >= (3, 9) else 'FAIL', sys.version.split()[0],
        'Xcode Command Line Tools 를 설치한다(xcode-select --install)')
    add('sips', 'OK' if shutil.which('sips') else 'FAIL', shutil.which('sips') or '없음', 'macOS 기본 도구 — macOS 가 아니면 쓸 수 없다')
    dev_dir = developer_dir()
    env = dict(os.environ, DEVELOPER_DIR=dev_dir) if dev_dir else None
    code, out, err = run(['xcrun', 'devicectl', 'list', 'devices'], env=env)
    if code == 0:
        connected = [line for line in out.splitlines() if 'connected' in line and 'unavailable' not in line]
        add('Xcode / devicectl (iOS)', 'OK', f'{dev_dir} · 연결된 기기 {len(connected)}대')
        c2, o2, e2 = run(['xcrun', 'devicectl', 'device', 'capture', 'screenshot', '--help'], env=env)
        add('iOS 화면 캡처 (devicectl capture screenshot)', 'OK' if c2 == 0 else 'FAIL',
            '사용 가능' if c2 == 0 else (e2 or o2).strip()[-160:],
            '이 Xcode 의 devicectl 에 화면 캡처 명령이 없다 — Xcode 를 최신으로 올린다. 앱 컨테이너 복사로 우회하지 않는다(개발 서명이 아니면 막힌다)')
    else:
        add('Xcode / devicectl (iOS)', 'FAIL', (err or out).strip()[-160:],
            'App Store 에서 Xcode 를 설치하고 한 번 실행해 추가 구성요소를 설치한다. iPad 를 연결해 「이 컴퓨터 신뢰」')
    adb = shutil.which('adb') or next((p for p in ('/opt/homebrew/bin/adb', os.path.expanduser('~/Library/Android/sdk/platform-tools/adb'))
                                       if os.path.exists(p)), None)
    if adb:
        code, out, _ = run([adb, 'devices'])
        devs = [line.split()[0] for line in out.splitlines()[1:] if line.strip().endswith('device')]
        unauth = [line.split()[0] for line in out.splitlines()[1:] if 'unauthorized' in line]
        add('adb (Android)', 'OK' if devs else 'WARN', f'{adb} · 기기 {devs}' + (f' · 허용 대기 {unauth}' if unauth else ''),
            '' if devs else 'Android 기기에서 개발자 옵션 → USB 디버깅을 켜고, 연결 후 뜨는 「USB 디버깅 허용」을 누른다')
    else:
        add('adb (Android)', 'FAIL', '없음', 'brew install --cask android-platform-tools  (Homebrew 가 없으면 SETUP.md 2장)')
    # 마카롱(계정 상태)·타임머신(서버 시간)용 — 없어도 화면 케이스는 돈다
    node = shutil.which('node') or next((p for p in ('/opt/homebrew/bin/node', '/usr/local/bin/node') if os.path.exists(p)), None)
    if node:
        code, out, _ = run([node, '--version'])
        major = int(out.strip().lstrip('v').split('.')[0] or 0) if code == 0 else 0
        add('Node.js (상태·시간 케이스)', 'OK' if major >= 22 else 'WARN', out.strip(),
            '' if major >= 22 else 'Node 22 이상이 필요하다: brew install node')
    else:
        add('Node.js (상태·시간 케이스)', 'WARN', '없음', 'brew install node  — 상태·시간 케이스에만 필요')
    chrome = '/Applications/Google Chrome.app'
    add('Chrome (상태·시간 케이스)', 'OK' if os.path.isdir(chrome) else 'WARN', chrome if os.path.isdir(chrome) else '없음',
        '' if os.path.isdir(chrome) else 'https://www.google.com/chrome 에서 설치 — 상태·시간 케이스에만 필요')
    if node and '--web' in sys.argv:
        code, out, _ = run(['python3', os.path.join(HERE, 'timemachine.py'), 'get', os.environ.get('QA_SERVER', 'gb-qa-126')], timeout=60)
        ok = code == 0
        add('키트 Chrome 로그인(stove)', 'OK' if ok else 'FAIL', out.strip()[-160:],
            '' if ok else 'node tools/web/chrome_cdp.mjs launch 로 띄운 창에서 stove·마카롱에 로그인한다(SETUP.md 6장)')
    devices_path = os.path.join(HERE, 'device_flows', 'devices.json')
    if not os.path.exists(devices_path):
        add('devices.json', 'WARN', '없음', 'cp tools/device_flows/devices.example.json tools/device_flows/devices.json 후 기기 ID 를 넣는다')
        devices = qc.load_json(os.path.join(HERE, 'device_flows', 'devices.example.json'))
    else:
        devices = qc.load_json(devices_path)
    for key in ('ios', 'aos'):
        d = devices.get(key, {}).get('device')
        add(f'devices.json {key}', 'OK' if d else 'WARN', d or '비어 있음',
            '' if d else ('xcrun devicectl list devices 의 Identifier' if key == 'ios' else 'adb devices 의 serial') + ' 를 넣는다')
    if ping:
        for key in ('ios', 'aos'):
            d = devices.get(key, {}).get('device')
            if not d:
                continue
            code, out, _ = run(['python3', os.path.join(HERE, 'gb_device.py'), 'ping', '--platform',
                                devices[key].get('platform', key), '--device', d, '--checkout', qc.WORKSPACE], timeout=40)
            last = (out.strip().splitlines() or ['{}'])[-1]
            try:
                ok = json.loads(last).get('ok')
            except ValueError:
                ok = False
            add(f'브리지 {key}', 'OK' if ok else 'FAIL', last[-160:],
                '' if ok else 'gb_device.py launch 로 앱을 띄운다. 그래도 안 되면 DEBUG(브리지 포함) 빌드인지 확인한다')
    width = max(len(r['item']) for r in rows)
    for r in rows:
        print(f'{r["status"]:<4} {r["item"]:<{width}}  {r["detail"]}' + (f'\n     → {r["fix"]}' if r['fix'] and r['status'] != 'OK' else ''))
    return 1 if any(r['status'] == 'FAIL' for r in rows) else 0


if __name__ == '__main__':
    sys.exit(main())
