#!/usr/bin/env python3
"""Host-side device loop and checkout-bound file queue; standard library only."""

import argparse
import contextlib
import fcntl
import hashlib
import io
import ipaddress
import itertools
import json
import math
import os
from pathlib import Path
import plistlib
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid


ADB = '/opt/homebrew/bin/adb'
BUNDLE = 'com.devsisters.enterprise.gb'
PACKAGE = 'com.devsisters.gb'
PROFILE_UUID = '5e40f5f6-6182-4689-a787-e80f35449f7f'
PROFILE_NAME = 'iOS Team Provisioning Profile: ' + BUNDLE
LOCK_ROOT = Path.home() / 'Library/Caches/gb_device/locks'
STATE_ROOT = Path.home() / 'Library/Caches/gb_device/state'
APP_PROCESSES = {}
SECRETS = set()
IDS = itertools.count(1)
BRIDGE_OPS = ('ping', 'scene', 'tree', 'tap', 'swipe', 'scroll', 'capture', 'autorewind', 'testmode')
OPS = ('devices', 'build', 'install', 'launch', 'stop', 'screenshot',
       *BRIDGE_OPS, 'wait-scene', 'os-tap', 'logs', 'crashes')


class DeviceError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DeviceError(2, message)


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be finite and positive')
    return number


def finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError('must be finite')
    return number


def natural(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError('must be nonnegative')
    return number


def parser():
    result = Parser(description=__doc__, add_help=False)
    result.add_argument('--help', action='store_true')
    subs = result.add_subparsers(dest='op', parser_class=Parser)
    for op in (*OPS, 'serve'):
        sub = subs.add_parser(op, add_help=False)
        sub.add_argument('--help', action='store_true')
        sub.add_argument('--platform', choices=('mac', 'android', 'ios'), default='mac')
        sub.add_argument('--device')
        sub.add_argument('--checkout', default=str(Path.cwd()))
        sub.add_argument('--port', type=int, default=17880)
        sub.add_argument('--host')
        sub.add_argument('--timeout', type=positive, default=10.0)
        if op == 'serve':
            sub.add_argument('--queue', required=True)
        if op == 'install':
            sub.add_argument('--apk')
            sub.add_argument('--app')
            sub.add_argument('--identity')
        if op == 'launch':
            sub.add_argument('--app')
            sub.add_argument('--restart', action='store_true')
            sub.add_argument('--console-log', help='iOS: 앱 stdout/stderr 를 이 파일에 받는다(devicectl --console)')
        if op in ('autorewind', 'testmode'):
            sub.add_argument('--json', default='{}', help='브리지 요청 필드(JSON 객체)')
        if op == 'screenshot':
            sub.add_argument('out')
        if op == 'tree':
            sub.add_argument('--max-nodes', type=natural, default=1000)
            sub.add_argument('--max-depth', type=natural, default=32)
            sub.add_argument('--all', action='store_true')
        if op == 'tap':
            sub.add_argument('--x', type=finite)
            sub.add_argument('--y', type=finite)
            sub.add_argument('--node')
            sub.add_argument('--index', type=natural, default=0)
        if op == 'swipe':
            for key in ('x1', 'y1', 'x2', 'y2'):
                sub.add_argument('--' + key, type=finite, required=True)
            sub.add_argument('--duration-ms', type=natural, default=300)
        if op == 'scroll':
            # 스크롤 목록을 손가락 없이 옮긴다(관성 없음). 셋 중 하나, 없으면 지금 위치만 돌려준다
            sub.add_argument('--to', choices=('start', 'end'))
            sub.add_argument('--pages', type=finite, help='보이는 길이의 배수. 양수는 뒤쪽 내용(세로는 아래)')
            sub.add_argument('--by', type=finite, help='게임 좌표 길이. 양수는 뒤쪽 내용')
            sub.add_argument('--node', help='이 노드가 든 목록(없으면 화면에서 가장 넓은 목록)')
            sub.add_argument('--x', type=finite)
            sub.add_argument('--y', type=finite)
        if op == 'wait-scene':
            sub.add_argument('name')
        if op == 'os-tap':
            sub.add_argument('x', type=int)
            sub.add_argument('y', type=int)
        if op == 'logs':
            sub.add_argument('--lines', type=natural, default=100)
        if op == 'crashes':
            sub.add_argument('--fetch')
    return result


def validate(args):
    if args.op not in (*OPS, 'serve'):
        raise DeviceError(2, 'a subcommand is required')
    root = Path(args.checkout).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise DeviceError(2, '--checkout must be an existing absolute directory')
    args.checkout = str(root.resolve())
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 600:
        raise DeviceError(2, '--timeout must be greater than 0 and at most 600 seconds')
    if not 1 <= args.port <= 65535:
        raise DeviceError(2, '--port must be 1..65535')
    if args.device is not None and (not args.device or args.device.startswith('-')):
        raise DeviceError(2, 'invalid device identifier')
    if args.platform != 'mac' and args.op not in ('serve', 'devices', 'build') and not args.device:
        raise DeviceError(2, '--device is required for android/ios')
    if args.op == 'os-tap' and args.platform != 'android':
        raise DeviceError(2, 'os-tap is android only')
    if args.op == 'tap':
        coordinates = args.x is not None and args.y is not None
        if args.node is not None:
            if not args.node or args.x is not None or args.y is not None:
                raise DeviceError(2, 'tap needs either --node or both --x and --y')
        elif not coordinates:
            raise DeviceError(2, 'tap needs either --node or both --x and --y')
    if args.op == 'scroll':
        if sum(getattr(args, key) is not None for key in ('to', 'pages', 'by')) > 1:
            raise DeviceError(2, 'scroll takes one of --to, --pages, --by')
        if (args.x is None) != (args.y is None) or (args.node is not None and args.x is not None):
            raise DeviceError(2, 'scroll target is --node or both --x and --y')
    if args.op == 'crashes' and args.fetch and args.platform != 'ios':
        raise DeviceError(2, '--fetch is ios only')
    return args


def run(command, *, timeout=60, env=None, cwd=None, stdout=None, check=True, merge_stderr=True):
    try:
        proc = subprocess.Popen([str(item) for item in command], shell=False, start_new_session=True,
                              env=env, cwd=cwd,
                              stdout=stdout if stdout is not None else subprocess.PIPE,
                              stderr=subprocess.STDOUT if stdout is not None and merge_stderr else subprocess.PIPE)
        try:
            output, errors = proc.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            if isinstance(exc, KeyboardInterrupt):
                raise
            raise DeviceError(5, 'external command timed out: ' + str(command[0]),
                              killed_process_group=True) from exc
    except OSError as exc:
        raise DeviceError(3, str(exc)) from exc
    if errors:
        print(redact(errors.decode('utf-8', errors='replace').rstrip()), file=sys.stderr)
    if check and proc.returncode:
        raise DeviceError(3, 'external command failed: ' + str(command[0]), exit=proc.returncode)
    return subprocess.CompletedProcess(command, proc.returncode, output, errors)


def redact(value):
    if isinstance(value, str):
        for token in SECRETS:
            value = value.replace(token, '[redacted]')
    elif isinstance(value, dict):
        value = {key: redact(item) for key, item in value.items() if key != 'token'}
    elif isinstance(value, list):
        value = [redact(item) for item in value]
    return value


def strict_json(raw):
    def reject(value):
        raise ValueError('non-finite JSON constant: ' + value)
    return json.loads(raw, parse_constant=reject)


def text_run(command, **kwargs):
    return run(command, **kwargs).stdout.decode('utf-8', errors='replace').strip()


def apple_env(root):
    # Fixed program, positional path: no request value is interpreted as shell code.
    script = root / '.gb-agent/env.sh'
    if not script.is_file():
        raise DeviceError(3, 'missing ' + str(script))
    data = run(['/bin/bash', '-c', 'set -a; source "$1" >/dev/null || exit; env -0',
                'gb-device-env', script]).stdout
    return dict(item.decode().split('=', 1) for item in data.split(b'\0') if b'=' in item)


def devicectl(root, *arguments, timeout=120):
    raw = text_run(['xcrun', 'devicectl', *arguments, '--json-output', '-'],
                   env=apple_env(root), timeout=timeout)
    try:
        return strict_json(raw)
    except ValueError as exc:
        raise DeviceError(3, 'invalid devicectl JSON') from exc


def adb(args, *arguments, **kwargs):
    if arguments and arguments[0] == 'shell':
        arguments = ('shell', *(shlex.quote(str(value)) for value in arguments[1:]))
    return run([ADB, '-s', args.device, *arguments], **kwargs)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def state_path(root, platform, device=None):
    suffix = '' if platform == 'mac' else '-' + safe_name(device or 'unknown')
    directory = STATE_ROOT / checkout_hash(root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory / (platform + suffix + '.json')


def checkout_hash(root):
    return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]


def read_state(path):
    if not path.exists():
        return {}
    value = strict_json(path.read_text())
    if not isinstance(value, dict):
        raise DeviceError(3, 'invalid device state')
    if isinstance(value.get('token'), str):
        SECRETS.add(value['token'])
    return value


def pid_alive(pid):
    if type(pid) is not int or pid <= 1:
        return False
    owned = pid in APP_PROCESSES
    reap_apps()
    if owned and pid not in APP_PROCESSES:
        return False
    status = text_run(['/bin/ps', '-p', str(pid), '-o', 'stat='], check=False)
    if not status or status.startswith('Z'):
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def reap_apps():
    for pid, proc in list(APP_PROCESSES.items()):
        if proc.poll() is not None:
            del APP_PROCESSES[pid]


def pid_birth(pid):
    proc = run(['/bin/ps', '-p', str(pid), '-o', 'lstart='], check=False)
    return proc.stdout.decode().strip() if proc.returncode == 0 else ''


def own_mac_alive(state):
    return (pid_alive(state.get('pid')) and bool(state.get('birth'))
            and pid_birth(state['pid']) == state['birth'])


def stop_mac(root):
    path = state_path(root, 'mac')
    state = read_state(path)
    if not own_mac_alive(state):
        return {'ok': True, 'skipped': 'owned PID is not alive'}
    pid = state['pid']
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while own_mac_alive(state):
        if time.monotonic() >= deadline:
            raise DeviceError(5, 'owned mac PID did not exit after SIGTERM', pid=pid)
        time.sleep(0.1)
    path.unlink(missing_ok=True)
    return {'ok': True, 'pid': pid}


def walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def tunnel_addresses(data):
    result = []
    for key, value in walk(data):
        if 'tunnel' not in key.lower():
            continue
        values = [value] if isinstance(value, str) else [v for _, v in walk(value)]
        for address in values:
            if not isinstance(address, str):
                continue
            try:
                ipaddress.ip_address(address.strip('[]'))
            except ValueError:
                continue
            address = address.strip('[]')
            if address not in result:
                result.append(address)
    return result


def bridge_targets(args, fresh=False):
    if args.platform == 'mac':
        return [('127.0.0.1', args.port)]
    if args.platform == 'android':
        listing = adb(args, 'forward', '--list').stdout.decode()
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == args.device and parts[2] == 'tcp:' + str(args.port):
                if re.fullmatch(r'tcp:[1-9][0-9]*', parts[1]):
                    save_forward(args, int(parts[1][4:]))
                    return [('127.0.0.1', int(parts[1][4:]))]
        # adb reserves an available host port itself, avoiding a bind/close race.
        assigned = adb(args, 'forward', 'tcp:0', 'tcp:' + str(args.port)).stdout.decode().strip()
        if not assigned.isdigit() or not 1 <= int(assigned) <= 65535:
            raise DeviceError(3, 'adb did not return an allocated forward port')
        save_forward(args, int(assigned))
        return [('127.0.0.1', int(assigned))]
    if args.host:
        return [(args.host.strip('[]'), args.port)]
    path = state_path(Path(args.checkout), 'ios', args.device)
    if not fresh:
        # devicectl 로 터널 주소를 찾는 데 명령마다 0.2~0.3초가 든다 — 지난번 주소를 먼저 쓰고, 안 닿으면 다시 찾는다
        cached = read_state(path).get('tunnel_ips')
        if isinstance(cached, list) and cached and all(isinstance(ip, str) for ip in cached):
            return [(ip, args.port) for ip in cached]
    try:
        data = devicectl(Path(args.checkout), 'device', 'info', 'details', '--device', args.device)
    except DeviceError as exc:
        raise DeviceError(4, 'bridge addresses attempted: []; tunnel discovery failed: ' + str(exc)) from exc
    ips = tunnel_addresses(data)
    if not ips:
        raise DeviceError(4, 'bridge addresses attempted: []; no tunnel IP; specify --host')
    atomic_json(path, {**read_state(path), 'tunnel_ips': ips})
    return [(ip, args.port) for ip in ips]


def save_forward(args, port):
    path = state_path(Path(args.checkout), 'android', args.device)
    atomic_json(path, {**read_state(path), 'forward_port': port})


def bridge_request(args, command, **fields):
    request_id = next(IDS)
    state = read_state(state_path(Path(args.checkout), args.platform, args.device))
    if state.get('token'):
        fields['token'] = state['token']
    payload = json.dumps({'id': request_id, 'cmd': command, **fields}, allow_nan=False).encode() + b'\n'
    deadline = time.monotonic() + args.timeout
    cached = args.platform == 'ios' and not args.host
    try:
        return _bridge_send(args, bridge_targets(args), payload, request_id, deadline, connect_cap=3 if cached else None)
    except DeviceError as exc:
        if not cached or exc.code not in (4, 5) or exc.details.get('stage') != 'connect':
            raise
    # 기억해 둔 터널 주소에 연결하지 못했다 — 기기를 다시 꽂았거나 터널이 바뀌었다. 주소를 새로 찾는다
    return _bridge_send(args, bridge_targets(args, fresh=True), payload, request_id, deadline)


def _bridge_send(args, targets, payload, request_id, deadline, connect_cap=None):
    attempted = []
    timed_out = False
    connected = False
    for host, port in targets:
        attempted.append(f'[{host}]:{port}')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            with socket.create_connection((host, port), timeout=min(remaining, connect_cap or remaining)) as sock:
                connected = True
                sock.sendall(payload)
                data = b''
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise socket.timeout()
                    sock.settimeout(remaining)
                    block = sock.recv(65536)
                    if not block:
                        raise OSError('bridge closed before matching response')
                    data += block
                    if len(data) > 16 * 1024 * 1024:
                        raise OSError('bridge response exceeds 16 MiB')
                    while b'\n' in data:
                        line, data = data.split(b'\n', 1)
                        response = strict_json(line)
                        if not isinstance(response, dict):
                            raise ValueError('bridge response is not an object')
                        if response.get('id') != request_id:
                            continue
                        if type(response.get('ok')) is not bool:
                            raise ValueError('bridge response has no boolean ok')
                        if not response['ok']:
                            raise DeviceError(3, str(response.get('error', 'bridge command failed')))
                        if not isinstance(response.get('result'), dict):
                            raise DeviceError(3, 'bridge result is not an object')
                        return response
        except (socket.timeout, TimeoutError):
            timed_out = True
        except ValueError as exc:
            raise DeviceError(3, str(exc)) from exc
        except OSError as exc:
            print('bridge: ' + str(exc), file=sys.stderr)
    raise DeviceError(5 if timed_out else 4,
                      'bridge ' + ('timeout' if timed_out else 'unavailable') + '; addresses attempted: ' + ', '.join(attempted),
                      stage='response' if connected else 'connect')


def default_app(root, platform):
    if platform == 'mac':
        return root / '.gb-agent/build/macos/DerivedData/Build/Products/Debug/Cookie Run (Mac).app'
    return root / '.gb-agent/build/ios-internal/DerivedData/Build/Products/Debug-iphoneos/Cookie Run (InternalBuild).app'


def path_arg(root, value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


@contextlib.contextmanager
def output_file(args, value, *, append=False):
    root = Path(args.checkout)
    path = Path(value).expanduser()
    path = path if path.is_absolute() else root / path
    if not getattr(args, 'daemon', False):
        # Direct CLI: the caller chose the path, so resolve links like /tmp -> /private/tmp first.
        path = Path(os.path.realpath(path))
    # Walk components from a pinned root, never following checkout-controlled links.
    anchor = root if getattr(args, 'daemon', False) else Path(path.anchor)
    try:
        parts = path.relative_to(anchor).parts
    except ValueError as exc:
        raise DeviceError(2, 'output outside checkout') from exc
    if not parts or any(part in ('.', '..') for part in parts):
        raise DeviceError(2, 'invalid output path')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with contextlib.ExitStack() as stack:
        directory = os.open(anchor, flags)
        stack.callback(os.close, directory)
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            directory = os.open(part, flags, dir_fd=directory)
            stack.callback(os.close, directory)
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW |
                     (os.O_APPEND if append else os.O_EXCL), 0o600, dir_fd=directory)
        with os.fdopen(fd, 'ab' if append else 'wb') as stream:
            yield stream


def copy_device_output(args, destination, *arguments):
    # devicectl accepts paths, not inherited fds: stage outside the writable checkout.
    with tempfile.TemporaryDirectory(dir=state_path(Path(args.checkout), args.platform, args.device).parent) as temporary:
        staged = Path(temporary) / Path(destination).name
        devicectl(Path(args.checkout), *arguments, '--destination', str(staged))
        with staged.open('rb') as source, output_file(args, destination) as target:
            shutil.copyfileobj(source, target)


def build(args):
    started = time.time()
    root = Path(args.checkout)
    logs = root / '.gb-agent/device'
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / ('build-' + args.platform + '-' + uuid.uuid4().hex + '.log')
    environment = apple_env(root)
    if args.platform == 'ios':
        command = ['xcodebuild', '-workspace', 'proj.ios_mac/gb-client.xcworkspace',
                   '-scheme', 'Cookie Run (InternalBuild)', '-configuration', 'Debug',
                   '-sdk', 'iphoneos', '-destination', 'generic/platform=iOS',
                   '-derivedDataPath', str(root / '.gb-agent/build/ios-internal/DerivedData'),
                   '-jobs', '16', 'IPHONEOS_DEPLOYMENT_TARGET=15.0',
                   'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO',
                   'COMPILER_INDEX_STORE_ENABLE=NO', 'build']
    else:
        command = ['python3', str(root / '.gb-agent/tools/gb_env.py'), 'build',
                   '--platform', 'macos' if args.platform == 'mac' else 'android',
                   '--checkout', str(root)]
    print('build log: ' + str(log), file=sys.stderr)
    try:
        with output_file(args, log) as stream:
            proc = run(command, env=environment, cwd=root, stdout=stream, timeout=5400, check=False)
    except DeviceError as exc:
        exc.details.update(log=str(log), exit=None)
        raise
    artifacts = ([str(p) for p in sorted((root / '.gb-agent/build/android/artifacts').glob('*.apk'))
                  if p.stat().st_mtime >= started]
                 if args.platform == 'android' else [str(default_app(root, args.platform))])
    result = {'ok': proc.returncode == 0, 'exit': proc.returncode, 'log': str(log), 'artifacts': artifacts}
    if proc.returncode:
        raise DeviceError(3, 'build failed', exit=proc.returncode, log=str(log), artifacts=artifacts)
    if not artifacts or any(not Path(path).exists() for path in artifacts):
        raise DeviceError(3, 'build exited 0 but artifact is missing', exit=0, log=str(log), artifacts=artifacts)
    return result


def provisioning_profile():
    directory = Path.home() / 'Library/Developer/Xcode/UserData/Provisioning Profiles'
    matches = []
    for path in sorted(directory.glob('*.mobileprovision')):
        data = plistlib.loads(run(['security', 'cms', '-D', '-i', path]).stdout)
        if data.get('UUID') == PROFILE_UUID:
            return path, data
        if data.get('Name') == PROFILE_NAME:
            matches.append((path, data))
    if len(matches) != 1:
        raise DeviceError(3, 'expected one provisioning profile named ' + PROFILE_NAME)
    return matches[0]


def sign_ios(args, source):
    root = Path(args.checkout)
    profile_path, profile = provisioning_profile()
    identities = re.findall(r'([0-9A-Fa-f]{40})\s+"(Apple Development: [^"]+)"',
                            text_run(['security', 'find-identity', '-v', '-p', 'codesigning']))
    if args.identity:
        identities = [item for item in identities if any(args.identity in value for value in item)]
    if len(identities) != 1:
        raise DeviceError(2 if len(identities) > 1 else 3,
                          'select exactly one Apple Development identity with --identity')
    identity = identities[0][0]
    source_entitlements = profile.get('Entitlements', {})
    wanted = ('application-identifier', 'com.apple.developer.team-identifier',
              'get-task-allow', 'aps-environment', 'com.apple.security.application-groups',
              'keychain-access-groups')
    entitlements = {key: source_entitlements[key] for key in wanted if key in source_entitlements}
    missing = [key for key in wanted if key not in source_entitlements]
    # Provisioning profiles can use a wildcard, but this signed app has one identifier.
    if 'application-identifier' in entitlements:
        entitlements['application-identifier'] = entitlements['application-identifier'].replace('*', BUNDLE)
    if 'keychain-access-groups' in entitlements:
        entitlements['keychain-access-groups'] = [value.replace('*', BUNDLE)
                                                for value in entitlements['keychain-access-groups']]
    signed_root = root / '.gb-agent/device/ios-signed'
    signed_root.mkdir(parents=True, exist_ok=True)
    destination = signed_root / source.name
    if source.resolve() == destination.resolve():
        raise DeviceError(2, '--app must be the unsigned source, not ios-signed output')
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)
    shutil.copy2(profile_path, destination / 'embedded.mobileprovision')
    entitlements_path = signed_root / 'entitlements.plist'
    entitlements_path.write_bytes(plistlib.dumps(entitlements))
    nested = [path for folder in ('Frameworks', 'PlugIns')
              for path in (destination / folder).rglob('*')
              if path.suffix in ('.framework', '.dylib', '.appex')]
    for path in sorted(nested, key=lambda path: (-len(path.parts), str(path))):
        run(['codesign', '-f', '-s', identity, path], timeout=600)
    for path in sorted(destination.glob('*.dylib')):
        run(['codesign', '-f', '-s', identity, path], timeout=600)
    run(['codesign', '-f', '-s', identity, '--entitlements', entitlements_path, destination], timeout=600)
    run(['codesign', '-v', '--deep', '--strict', destination], timeout=600)
    return destination, missing


def launch(args):
    root = Path(args.checkout)
    if getattr(args, 'daemon', False) and args.app:
        raise DeviceError(2, 'launch --app is not allowed in daemon mode')
    token = secrets.token_hex(16)
    SECRETS.add(token)
    environment = {'GB_AGENT_BRIDGE': '1', 'GB_AGENT_BRIDGE_PORT': str(args.port),
                   'GB_AGENT_BRIDGE_TOKEN': token}
    if args.platform == 'mac':
        path = state_path(root, 'mac')
        state = read_state(path)
        if own_mac_alive(state):
            if not args.restart:
                raise DeviceError(3, 'owned mac PID is alive; use --restart', pid=state['pid'])
            stop_mac(root)
        app = path_arg(root, args.app) if args.app else default_app(root, 'mac')
        with (app / 'Contents/Info.plist').open('rb') as stream:
            executable_name = plistlib.load(stream)['CFBundleExecutable']
        if Path(executable_name).name != executable_name:
            raise DeviceError(3, 'invalid CFBundleExecutable')
        executable = app / 'Contents/MacOS' / executable_name
        path.parent.mkdir(parents=True, exist_ok=True)
        with output_file(args, root / '.gb-agent/device/mac-app.log', append=True) as log:
            proc = subprocess.Popen([str(executable)], env={**os.environ, **environment}, cwd=root,
                                    stdout=log, stderr=subprocess.STDOUT, shell=False, start_new_session=True)
        APP_PROCESSES[proc.pid] = proc
        birth = pid_birth(proc.pid)
        atomic_json(path, {'pid': proc.pid, 'birth': birth, 'executable': str(executable), 'port': args.port, 'token': token})
        if proc.poll() is not None or not birth:
            raise DeviceError(3, 'mac app exited or PID identity could not be recorded', pid=proc.pid)
        return {'ok': True, 'pid': proc.pid, 'state': str(path)}
    if args.platform == 'android':
        atomic_json(state_path(root, 'android', args.device), {'token': token, 'port': args.port})
        adb(args, 'shell', 'setprop', 'debug.gb.agentbridge', '1')
        adb(args, 'shell', 'setprop', 'debug.gb.agentbridge.port', str(args.port))
        adb(args, 'shell', 'setprop', 'debug.gb.agentbridge.token', token)
        adb(args, 'shell', 'am', 'force-stop', PACKAGE)
        raw = adb(args, 'shell', 'cmd', 'package', 'resolve-activity', '--brief',
                  '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', PACKAGE).stdout.decode()
        activities = [line.strip() for line in raw.splitlines() if re.fullmatch(r'[\w.]+/[\w.$]+', line.strip())]
        if len(activities) != 1 or not activities[0].startswith(PACKAGE + '/'):
            raise DeviceError(3, 'could not resolve app launcher activity')
        output = adb(args, 'shell', 'am', 'start', '-W', '-n', activities[0]).stdout.decode()
        if re.search(r'(?im)^\s*(error|exception)', output):
            raise DeviceError(3, 'am start failed: ' + output.strip())
        return {'ok': True, 'activity': activities[0]}
    atomic_json(state_path(root, 'ios', args.device), {'token': token, 'port': args.port})
    if getattr(args, 'console_log', None):
        return launch_ios_console(args, root, environment, token)
    result = devicectl(root, 'device', 'process', 'launch', '--device', args.device,
                       '--terminate-existing', '--environment-variables', json.dumps(environment), BUNDLE)
    pids = [value for key, value in walk(result) if key in ('processIdentifier', 'pid') and type(value) is int]
    if not pids:
        raise DeviceError(3, 'iOS launch returned no PID; cannot track stop', result=result)
    atomic_json(state_path(root, 'ios', args.device), {'pid': pids[0], 'bundle': BUNDLE, 'token': token, 'port': args.port})
    return {'ok': True, 'pid': pids[0], 'result': result}


def ios_app_pids(root, device):
    data = devicectl(root, 'device', 'info', 'processes', '--device', device)
    pids = []
    for process in (data.get('result') or {}).get('runningProcesses', []):
        executable = str(process.get('executable', ''))
        if 'Cookie%20Run%20(InternalBuild).app' in executable or 'Cookie Run (InternalBuild).app' in executable:
            if type(process.get('processIdentifier')) is int:
                pids.append(process['processIdentifier'])
    return pids


def launch_ios_console(args, root, environment, token):
    # --console 은 앱이 끝날 때까지 붙어 있어야 출력이 온다. 이 프로세스를 끊으면 앱도 SIGINT 로 끝난다
    log_path = Path(args.console_log).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    before = set(ios_app_pids(root, args.device))
    stream = open(log_path, 'ab')
    console = subprocess.Popen(['xcrun', 'devicectl', 'device', 'process', 'launch', '--console', '--device', args.device,
                                '--terminate-existing', '--environment-variables', json.dumps(environment), BUNDLE],
                               stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                               env=apple_env(root), start_new_session=True)
    stream.close()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        fresh = [pid for pid in ios_app_pids(root, args.device) if pid not in before]
        if fresh:
            atomic_json(state_path(root, 'ios', args.device), {'pid': fresh[0], 'bundle': BUNDLE, 'token': token,
                                                                 'port': args.port, 'consolePid': console.pid})
            return {'ok': True, 'pid': fresh[0], 'consolePid': console.pid, 'consoleLog': str(log_path)}
        if console.poll() is not None:
            break
        time.sleep(1)
    raise DeviceError(3, 'iOS console launch did not produce an app PID', consoleLog=str(log_path))


def execute(args):
    root = Path(args.checkout)
    op = args.op
    if op == 'devices':
        result = {'ok': True, 'mac': redact(read_state(state_path(root, 'mac'))), 'errors': {}}
        result['mac']['alive'] = own_mac_alive(result['mac'])
        for platform in ('android', 'ios'):
            try:
                if platform == 'android':
                    listing = text_run([ADB, 'devices'])
                    result[platform] = [dict(zip(('serial', 'state'), line.split()[:2]))
                                        for line in listing.splitlines()[1:] if len(line.split()) >= 2]
                else:
                    result[platform] = devicectl(root, 'list', 'devices')
            except DeviceError as exc:
                result['errors'][platform] = str(exc)
        if result['errors']:
            raise DeviceError(3, 'device discovery partially failed', devices=result)
        return result
    if op == 'build':
        return build(args)
    if op == 'install':
        if args.platform == 'mac':
            return {'ok': True, 'skipped': 'mac does not need installation'}
        if args.platform == 'android':
            if not args.apk:
                raise DeviceError(2, 'android install requires --apk')
            apk = path_arg(root, args.apk)
            adb(args, 'install', '-r', apk, timeout=300)
            return {'ok': True, 'apk': str(apk)}
        source = path_arg(root, args.app) if args.app else default_app(root, 'ios')
        signed, missing = sign_ios(args, source)
        result = devicectl(root, 'device', 'install', 'app', '--device', args.device, str(signed), timeout=600)
        return {'ok': True, 'app': str(signed), 'missing_entitlements': missing, 'result': result}
    if op == 'launch':
        return launch(args)
    if op == 'stop':
        if args.platform == 'mac':
            return stop_mac(root)
        if args.platform == 'android':
            adb(args, 'shell', 'am', 'force-stop', PACKAGE)
            return {'ok': True}
        path = state_path(root, 'ios', args.device)
        state = read_state(path)
        pid = state.get('pid')
        if type(pid) is not int or pid <= 1:
            raise DeviceError(3, 'no recorded iOS app PID; launch through this tool first')
        result = devicectl(root, 'device', 'process', 'terminate', '--device', args.device, '--pid', str(pid))
        path.unlink(missing_ok=True)
        return {'ok': True, 'pid': pid, 'result': result}
    if op in BRIDGE_OPS:
        fields = {}
        if op == 'tree':
            fields = {'maxNodes': args.max_nodes, 'maxDepth': args.max_depth, 'visibleOnly': not args.all}
        elif op == 'tap':
            fields = {'node': args.node, 'index': args.index} if args.node else {'x': args.x, 'y': args.y}
        elif op == 'swipe':
            fields = {key: getattr(args, key) for key in ('x1', 'y1', 'x2', 'y2')}
            fields['durationMs'] = args.duration_ms
        elif op == 'scroll':
            fields = {key: getattr(args, key) for key in ('to', 'pages', 'by', 'node', 'x', 'y') if getattr(args, key) is not None}
        elif op in ('autorewind', 'testmode'):
            try:
                fields = json.loads(args.json)
            except ValueError as exc:
                raise DeviceError(2, '--json is not valid JSON') from exc
            if not isinstance(fields, dict) or any(key in fields for key in ('id', 'cmd', 'token')):
                raise DeviceError(2, '--json must be an object without id/cmd/token')
        return bridge_request(args, op, **fields)
    if op == 'wait-scene':
        deadline = time.monotonic() + args.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeviceError(5, 'wait-scene timed out: ' + args.name)
            probe = argparse.Namespace(**vars(args))
            probe.timeout = min(10, remaining)
            try:
                response = bridge_request(probe, 'scene')
                if response.get('result', {}).get('top') == args.name:
                    return response
            except DeviceError as exc:
                if exc.code not in (4, 5):
                    raise
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    if op == 'screenshot':
        out = Path(args.out).expanduser()
        out = out if out.is_absolute() else root / out
        if out.suffix.lower() != '.png':
            raise DeviceError(2, 'screenshot output must end in .png')
        if args.platform == 'mac':
            response = bridge_request(args, 'capture')
            source = response.get('result', {}).get('path')
            if not isinstance(source, str) or not Path(source).is_file():
                raise DeviceError(3, 'capture response has no readable file path')
            if Path(source).resolve() != out:
                with Path(source).open('rb') as capture, output_file(args, out) as target:
                    shutil.copyfileobj(capture, target)
        elif args.platform == 'android':
            with output_file(args, out) as stream:
                adb(args, 'exec-out', 'screencap', '-p', stdout=stream, merge_stderr=False)
        else:
            copy_device_output(args, out, 'device', 'capture', 'screenshot', '--device', args.device)
        return {'ok': True, 'path': str(out)}
    if op == 'os-tap':
        adb(args, 'shell', 'input', 'tap', str(args.x), str(args.y))
        return {'ok': True}
    if op == 'logs':
        if args.platform == 'ios':
            return {'ok': True, 'unsupported': 'iOS live logs'}
        if args.platform == 'mac':
            content = (root / '.gb-agent/device/mac-app.log').read_text(errors='replace')
        else:
            pid = adb(args, 'shell', 'pidof', PACKAGE).stdout.decode().strip().split()
            if len(pid) != 1 or not pid[0].isdigit():
                raise DeviceError(3, 'expected one running Android app PID')
            content = adb(args, 'logcat', '-d', '--pid=' + pid[0]).stdout.decode(errors='replace')
        return {'ok': True, 'lines': content.splitlines()[-args.lines:] if args.lines else []}
    if op == 'crashes':
        if args.platform == 'android':
            return {'ok': True, 'log': adb(args, 'logcat', '-b', 'crash', '-d').stdout.decode(errors='replace')}
        if args.platform == 'mac':
            paths = sorted((Path.home() / 'Library/Logs/DiagnosticReports').glob('Cookie Run*'),
                           key=lambda item: item.stat().st_mtime, reverse=True)
            return {'ok': True, 'files': [str(path) for path in paths[:20]]}
        data = devicectl(root, 'device', 'info', 'files', '--device', args.device, '--domain-type', 'systemCrashLogs')
        names = sorted({value for key, value in walk(data) if key in ('name', 'path', 'relativePath')
                        and isinstance(value, str) and value.endswith('.ips') and 'Cookie Run' in value})
        fetched = []
        if args.fetch:
            directory = Path(args.fetch)
            directory = directory if directory.is_absolute() else root / directory
            for name in names:
                destination = directory / Path(name).name
                copy_device_output(args, destination, 'device', 'copy', 'from', '--device', args.device,
                                   '--domain-type', 'systemCrashLogs', '--source', name)
                fetched.append(str(destination))
        return {'ok': True, 'files': names, 'fetched': fetched}
    raise DeviceError(2, 'unsupported operation')


def safe_name(value):
    # Preserve usual serial/UDID spelling; encode all other bytes without collisions.
    return ''.join(chr(byte) if chr(byte).isascii() and (chr(byte).isalnum() or chr(byte) in '-_')
                   else '%' + format(byte, '02x') for byte in value.encode('utf-8'))


@contextlib.contextmanager
def device_lock(args):
    LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    if args.op == 'build':
        name = 'build-' + args.platform + '-' + checkout_hash(args.checkout)
    elif args.platform == 'mac':
        name = 'mac-' + checkout_hash(args.checkout)
    else:
        name = args.platform + '-' + safe_name(args.device or 'host')
    path = LOCK_ROOT / (name + '.lock')
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeviceError(3, 'device busy') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def perform(args):
    try:
        validate(args)
        if args.op == 'devices':
            return 0, execute(args)
        with device_lock(args):
            return 0, execute(args)
    except DeviceError as exc:
        return exc.code, {'ok': False, 'error': str(exc), **exc.details}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return 3, {'ok': False, 'error': str(exc)}


def request_args(request, checkout):
    if not isinstance(request, dict) or request.get('op') not in OPS:
        raise DeviceError(2, 'operation is not allowed')
    raw = request.get('args', {})
    if not isinstance(raw, dict):
        raise DeviceError(2, 'args must be an object')
    op = request['op']
    cli = parser()
    sub = next(action for action in cli._actions if isinstance(action, argparse._SubParsersAction)).choices[op]
    actions = {action.dest: action for action in sub._actions if action.dest != 'help'}
    normalized = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise DeviceError(2, 'argument name must be a string')
        name = key.replace('-', '_')
        if name not in actions or name in normalized:
            raise DeviceError(2, 'unknown or duplicate argument: ' + key)
        normalized[name] = value
    if any(name in normalized for name in ('host', 'port')):
        raise DeviceError(2, '--host/--port are not allowed in daemon mode')
    if op == 'launch' and 'console_log' in normalized:
        raise DeviceError(2, 'launch --console-log is not allowed in daemon mode')
    if op == 'launch' and 'app' in normalized:
        raise DeviceError(2, 'launch --app is not allowed in daemon mode')
    if op == 'build':
        normalized.pop('timeout', None)
    root = checkout.resolve()
    if 'checkout' in normalized:
        value = normalized['checkout']
        if not isinstance(value, str) or not Path(value).is_absolute() or Path(value).resolve() != root:
            raise DeviceError(2, 'request checkout differs from daemon checkout')
    normalized['checkout'] = str(root)
    for name in ('out', 'fetch', 'app', 'apk'):
        if name in normalized:
            value = normalized[name]
            if not isinstance(value, str) or not value:
                raise DeviceError(2, 'invalid path argument: ' + name)
            path = path_arg(root, value)
            if not path.is_relative_to(root):
                raise DeviceError(2, 'path outside checkout: ' + name)
            normalized[name] = str(path)
    options, positionals = [op], []
    for name, action in actions.items():
        if name not in normalized:
            continue
        value = normalized[name]
        if isinstance(action, argparse._StoreTrueAction):
            if type(value) is not bool:
                raise DeviceError(2, name + ' must be boolean')
            if value:
                options.append(action.option_strings[0])
        else:
            if isinstance(value, (dict, list, bool)) or value is None:
                raise DeviceError(2, 'invalid argument: ' + name)
            if action.option_strings:
                options.append(action.option_strings[0] + '=' + str(value))
            else:
                positionals.append(str(value))
    args = validate(cli.parse_args(options + (['--'] + positionals if positionals else [])))
    args.daemon = True
    return args


@contextlib.contextmanager
def queue_directories(queue, queue_fd=None):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with contextlib.ExitStack() as stack:
        if queue_fd is None:
            queue_fd = os.open(queue, flags)
            stack.callback(os.close, queue_fd)
        current, pinned = os.stat(queue), os.fstat(queue_fd)
        if queue.resolve() != queue or (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise DeviceError(2, 'queue root changed')
        directories = {}
        for name in ('req', 'work', 'res'):
            path = queue / name
            before = os.stat(name, dir_fd=queue_fd, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode) or path.resolve() != queue / name:
                raise DeviceError(2, 'unsafe queue directory: ' + name)
            fd = os.open(name, flags, dir_fd=queue_fd)
            stack.callback(os.close, fd)
            opened = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise DeviceError(2, 'queue directory changed: ' + name)
            directories[name] = fd
        yield directories


def exists_at(directory, name):
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def publish_response(directory, name, value):
    data = json.dumps(redact(value), ensure_ascii=False, allow_nan=False).encode() + b'\n'
    temporary = '.' + name + '.' + uuid.uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_NOFOLLOW | os.O_CREAT | os.O_EXCL,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic publication without overwriting an existing response or following a link.
        os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    finally:
        os.unlink(temporary, dir_fd=directory)


def process_request(path, queue, checkout, queue_fd=None):
    started = time.time()
    try:
        with queue_directories(queue, queue_fd) as directories:
            return process_claim(path.name, directories, checkout, started)
    except Exception as exc:
        print(redact('queue request rejected: ' + str(exc)), file=sys.stderr)
        return False


def process_claim(name, directories, checkout, started):
    req, work, res = (directories[key] for key in ('req', 'work', 'res'))
    request_id, op = Path(name).stem, None
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request_id):
        request_id = 'invalid-' + uuid.uuid4().hex
    claimed, duplicate = False, False
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        try:
            if exists_at(work, name):
                raise DeviceError(3, 'interrupted work already exists; use a new request ID')
            os.rename(name, name, src_dir_fd=req, dst_dir_fd=work)
            claimed = True
            info = os.stat(name, dir_fd=work, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                raise DeviceError(2, 'request must be a regular file of at most 1 MiB')
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=work)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                    raise DeviceError(2, 'request must be a regular file of at most 1 MiB')
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise DeviceError(2, 'request exceeds 1 MiB')
            request = strict_json(raw)
            if not isinstance(request, dict):
                raise DeviceError(2, 'request must be an object')
            supplied_id = request.get('id')
            if not isinstance(supplied_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', supplied_id):
                raise DeviceError(2, 'id must contain 1..128 ASCII letters, digits, _ or -')
            request_id, op = supplied_id, request.get('op')
            if exists_at(res, request_id + '.json'):
                duplicate = True
                archived = 'dup-' + request_id + '-' + str(time.time_ns()) + '.json'
                os.rename(name, archived, src_dir_fd=work, dst_dir_fd=work)
                claimed = False
                raise DeviceError(2, 'duplicate request ID; use a new request ID')
            args = request_args(request, checkout)
            code, output = perform(args)
            if claimed:
                os.unlink(name, dir_fd=work)
                claimed = False
        except DeviceError as exc:
            code, output = exc.code, {'ok': False, 'error': str(exc), **exc.details}
        except Exception as exc:
            code, output = 2, {'ok': False, 'error': str(exc)}
    result = {'id': request_id, 'op': op, 'exit': code, 'stdout_json': output,
              'stderr_tail': stderr.getvalue()[-16384:], 'started': started, 'ended': time.time()}
    try:
        publish_response(res, request_id + ('.dup.json' if duplicate else '.json'), result)
    except (ValueError, TypeError):
        result.update(exit=3, stdout_json={'ok': False, 'error': 'response is not valid JSON'})
        publish_response(res, request_id + ('.dup.json' if duplicate else '.json'), result)
    return True


def serve(args):
    validate(args)
    checkout = Path(args.checkout)
    queue = Path(args.queue).expanduser().resolve()
    for name in ('req', 'work', 'res'):
        (queue / name).mkdir(parents=True, exist_ok=True)
    # One consumer per queue prevents duplicate claims; device locks cover other queues/CLIs.
    with contextlib.ExitStack() as stack:
        queue_fd = os.open(queue, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, queue_fd)
        fd = os.open('.serve.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=queue_fd)
        stream = stack.enter_context(os.fdopen(fd, 'a'))
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeviceError(3, 'queue busy') from exc
        stopping = False

        def stop(_signum, _frame):
            nonlocal stopping
            stopping = True

        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            while not stopping:
                reap_apps()
                try:
                    with queue_directories(queue, queue_fd) as directories:
                        paths = sorted(name for name in os.listdir(directories['req']) if name.endswith('.json'))
                except Exception as exc:
                    print(redact('queue scan rejected: ' + str(exc)), file=sys.stderr)
                    paths = []
                for name in paths:
                    if stopping:
                        break
                    process_request(queue / 'req' / name, queue, checkout, queue_fd)
                if not stopping:
                    time.sleep(0.5)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return {'ok': True, 'stopped': True, 'queue': str(queue)}


def main(argv=None):
    try:
        cli = parser()
        args = cli.parse_args(argv)
        if args.help:
            code, output = 0, {'ok': True, 'help': cli.format_help(), 'commands': OPS + ('serve',)}
        elif args.op == 'serve':
            code, output = 0, serve(args)
        else:
            code, output = perform(args)
        print(json.dumps(redact(output), ensure_ascii=False, allow_nan=False))
        return code
    except KeyboardInterrupt:
        for pid, proc in list(APP_PROCESSES.items()):
            if proc.poll() is None:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
        reap_apps()
        code, output = 130, {'ok': False, 'error': 'interrupted'}
    except DeviceError as exc:
        code, output = exc.code, {'ok': False, 'error': str(exc), **exc.details}
    except (OSError, ValueError, TypeError) as exc:
        code, output = 3, {'ok': False, 'error': str(exc)}
    print(json.dumps(redact(output), ensure_ascii=False, allow_nan=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
