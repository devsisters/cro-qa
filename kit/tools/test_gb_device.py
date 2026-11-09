"""Contract tests: real loopback bridge, mocked external device commands."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gb_device as device


@contextlib.contextmanager
def external_commands(**kwargs):
    external = mock.Mock(**kwargs)

    def popen(command, **options):
        proc = mock.Mock(pid=9876)

        def communicate(timeout=None):
            result = external(command, timeout=timeout, **options)
            proc.returncode = result.returncode
            return result.stdout, result.stderr
        proc.communicate.side_effect = communicate
        return proc

    with mock.patch.object(device.subprocess, 'Popen', side_effect=popen):
        yield external


class FakeBridge:
    def __init__(self, handler):
        self.handler = handler
        self.received = []
        self.errors = []
        self.socket = socket.socket()
        try:
            self.socket.bind(('127.0.0.1', 0))
        except OSError:
            self.socket.close()
            raise
        self.port = self.socket.getsockname()[1]
        self.socket.listen()
        self.socket.settimeout(2)
        self.thread = threading.Thread(target=self.serve)

    def serve(self):
        try:
            with self.socket.accept()[0] as connection:
                connection.settimeout(2)
                with connection.makefile('rb') as stream:
                    request = json.loads(stream.readline())
                self.received.append(request)
                self.handler(connection, request)
        except Exception as exc:
            self.errors.append(exc)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.thread.join(3)
        self.socket.close()
        if self.thread.is_alive():
            raise AssertionError('fake bridge did not finish')
        if self.errors:
            raise self.errors[0]


def reply(connection, value):
    connection.sendall(json.dumps(value).encode() + b'\n')


class DeviceTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.lock_patch = mock.patch.object(device, 'LOCK_ROOT', self.root / 'locks')
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)
        self.state_patch = mock.patch.object(device, 'STATE_ROOT', self.root / 'host-state')
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.apps_patch = mock.patch.object(device, 'APP_PROCESSES', {})
        self.apps_patch.start()
        self.addCleanup(self.apps_patch.stop)
        self.secrets_patch = mock.patch.object(device, 'SECRETS', set())
        self.secrets_patch.start()
        self.addCleanup(self.secrets_patch.stop)

    def args(self, *argv):
        return device.validate(device.parser().parse_args([*argv, '--checkout', str(self.root)]))

    def invoke(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = device.main([*argv, '--checkout', str(self.root)])
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        return code, json.loads(lines[0])


class DeviceTests(DeviceTestCase):
    def test_bridge_round_trip_and_fragmented_utf8(self):
        def handler(connection, request):
            data = json.dumps({'id': request['id'], 'ok': True, 'result': {'top': '로비'}}, ensure_ascii=False).encode() + b'\n'
            for byte in data:
                connection.sendall(bytes([byte]))
        with FakeBridge(handler) as server:
            code, response = self.invoke('scene', '--port', str(server.port))
        self.assertEqual(code, 0)
        self.assertEqual(response['result']['top'], '로비')
        self.assertEqual(server.received[0]['cmd'], 'scene')

    def test_bridge_ignores_mismatched_id(self):
        def handler(connection, request):
            reply(connection, {'id': request['id'] + 1, 'ok': False, 'error': 'wrong request'})
            reply(connection, {'id': request['id'], 'ok': True, 'result': {'pong': True}})
        with FakeBridge(handler) as server:
            code, response = self.invoke('ping', '--port', str(server.port))
        self.assertEqual(code, 0)
        self.assertTrue(response['result']['pong'])

    def test_bridge_timeout_exit_5(self):
        with FakeBridge(lambda connection, request: time.sleep(0.15)) as server:
            code, response = self.invoke('ping', '--port', str(server.port), '--timeout', '0.03')
        self.assertEqual(code, 5)
        self.assertIn('addresses attempted', response['error'])

    def test_bridge_error_is_exit_3(self):
        with FakeBridge(lambda conn, req: reply(conn, {'id': req['id'], 'ok': False, 'error': 'node missing'})) as server:
            code, response = self.invoke('tap', '--node', 'missing', '--port', str(server.port))
        self.assertEqual((code, response['error']), (3, 'node missing'))

    def test_mac_screenshot_no_os_fallback(self):
        with mock.patch.object(device.socket, 'create_connection', side_effect=ConnectionRefusedError()), external_commands() as run:
            code, result = self.invoke('screenshot', 'capture.png')
        self.assertEqual(code, 4)
        self.assertIn('127.0.0.1', result['error'])
        run.assert_not_called()

    def test_mac_capture_copy(self):
        source = self.root / 'source.png'
        source.write_bytes(b'PNG')
        with FakeBridge(lambda conn, req: reply(conn, {'id': req['id'], 'ok': True, 'result': {'path': str(source)}})) as server:
            code, result = self.invoke('screenshot', 'out.png', '--port', str(server.port))
        self.assertEqual(code, 0)
        self.assertEqual(Path(result['path']).read_bytes(), b'PNG')

    def test_bridge_field_mapping(self):
        for argv, expected in [
            (('tree', '--all', '--max-nodes', '12', '--max-depth', '3'), {'maxNodes': 12, 'maxDepth': 3, 'visibleOnly': False}),
            (('tap', '--x', '1.5', '--y', '-2'), {'x': 1.5, 'y': -2}),
            (('tap', '--node', 'button', '--index', '2'), {'node': 'button', 'index': 2}),
            (('swipe', '--x1', '1', '--y1', '2', '--x2', '3', '--y2', '4', '--duration-ms', '25'),
             {'x1': 1, 'y1': 2, 'x2': 3, 'y2': 4, 'durationMs': 25}),
        ]:
            with self.subTest(argv=argv), mock.patch.object(device, 'bridge_request', return_value={'ok': True}) as bridge:
                code, _ = self.invoke(*argv)
                self.assertEqual(code, 0)
                self.assertEqual(bridge.call_args.kwargs, expected)

    def test_wait_scene_success_and_deadline(self):
        with mock.patch.object(device, 'bridge_request', side_effect=[{'ok': True, 'result': {'top': 'Loading'}}, {'ok': True, 'result': {'top': 'Lobby'}}]), mock.patch.object(device.time, 'sleep'):
            self.assertEqual(self.invoke('wait-scene', 'Lobby')[0], 0)
        with mock.patch.object(device, 'bridge_request', return_value={'ok': True, 'result': {'top': 'Loading'}}):
            self.assertEqual(self.invoke('wait-scene', 'Lobby', '--timeout', '0.01')[0], 5)

    def test_android_forward_allocates_and_reuses(self):
        args = self.args('ping', '--platform', 'android', '--device', 'SERIAL')
        with external_commands(side_effect=[
            subprocess.CompletedProcess([], 0, b'', b''),
            subprocess.CompletedProcess([], 0, b'45678\n', b''),
        ]) as run:
            self.assertEqual(device.bridge_targets(args), [('127.0.0.1', 45678)])
            self.assertEqual(run.call_args_list[0].args[0], [device.ADB, '-s', 'SERIAL', 'forward', '--list'])
            self.assertEqual(run.call_args_list[1].args[0], [device.ADB, '-s', 'SERIAL', 'forward', 'tcp:0', 'tcp:17880'])
            self.assertTrue(all(call.kwargs['shell'] is False for call in run.call_args_list))
        with external_commands(return_value=subprocess.CompletedProcess([], 0, b'OTHER tcp:4000 tcp:17880\nSERIAL tcp:45678 tcp:17880\n', b'')) as run:
            self.assertEqual(device.bridge_targets(args), [('127.0.0.1', 45678)])
            self.assertEqual(run.call_count, 1)
        self.assertEqual(device.read_state(device.state_path(self.root, 'android', 'SERIAL'))['forward_port'], 45678)

    def test_ios_tunnel_discovery_and_host_override(self):
        args = self.args('ping', '--platform', 'ios', '--device', 'UDID')
        with mock.patch.object(device, 'devicectl', return_value={'result': {'connectionProperties': {'tunnelIPAddress': 'fd00::1'}}}):
            self.assertEqual(device.bridge_targets(args), [('fd00::1', 17880)])
        with mock.patch.object(device, 'devicectl', return_value={'result': {'tunnel': {'ip': '127.0.0.2'}}}):
            self.assertEqual(device.bridge_targets(args), [('127.0.0.2', 17880)])
        args.host = '[::1]'
        with mock.patch.object(device, 'devicectl') as devicectl:
            self.assertEqual(device.bridge_targets(args), [('::1', 17880)])
            devicectl.assert_not_called()

    def test_ios_no_tunnel_reports_exit_4(self):
        with mock.patch.object(device, 'devicectl', return_value={}):
            code, result = self.invoke('ping', '--platform', 'ios', '--device', 'UDID')
        self.assertEqual(code, 4)
        self.assertIn('addresses attempted: []', result['error'])

    def test_android_launch_and_logs(self):
        def run(command, **kwargs):
            output = b''
            if 'resolve-activity' in command:
                output = b'priority=0\ncom.devsisters.gb/.MainActivity\n'
            elif 'pidof' in command:
                output = b'1234\n'
            elif 'logcat' in command:
                output = b'old\nnew\n'
            return subprocess.CompletedProcess(command, 0, output, b'')
        with external_commands(side_effect=run) as external:
            self.assertEqual(self.invoke('launch', '--platform', 'android', '--device', 'SERIAL')[0], 0)
            self.assertEqual(external.call_args_list[0].args[0][-3:], ['setprop', 'debug.gb.agentbridge', '1'])
            self.assertEqual(external.call_args_list[1].args[0][-3:], ['setprop', 'debug.gb.agentbridge.port', '17880'])
            code, result = self.invoke('logs', '--platform', 'android', '--device', 'SERIAL', '--lines', '1')
            self.assertEqual(code, 0)
            self.assertEqual(result['lines'], ['new'])
            self.assertIn('--pid=1234', external.call_args.args[0])

    def test_android_screenshot_keeps_stderr_out_of_png(self):
        def run(command, **kwargs):
            self.assertEqual(kwargs['stderr'], subprocess.PIPE)
            kwargs['stdout'].write(b'PNG')
            return subprocess.CompletedProcess(command, 0, None, b'adb warning\n')
        with external_commands(side_effect=run), contextlib.redirect_stderr(io.StringIO()):
            code, _ = self.invoke('screenshot', 'out.png', '--platform', 'android', '--device', 'SERIAL')
        self.assertEqual(code, 0)
        self.assertEqual((self.root / 'out.png').read_bytes(), b'PNG')

    def test_usage_errors_emit_one_json_line(self):
        for argv in [('os-tap', '1', '2'), ('tap', '--x', '2'), ('tap', '--node', 'button', '--y', '2'),
                     ('ping', '--timeout', 'nan'), ('ping', '--port', '0'), ('ping', '--platform', 'ios'),
                     ('unknown',), ('tap', '--x', 'inf', '--y', '2')]:
            with self.subTest(argv=argv):
                self.assertEqual(self.invoke(*argv)[0], 2)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(device.main([]), 2)
        self.assertFalse(json.loads(output.getvalue())['ok'])

    def test_device_busy_is_nonblocking(self):
        args = self.args('ping')
        with device.device_lock(args), mock.patch.object(device, 'execute') as execute:
            code, result = device.perform(args)
        self.assertEqual((code, result['error']), (3, 'device busy'))
        execute.assert_not_called()

    def test_mac_stop_uses_only_recorded_pid(self):
        path = device.state_path(self.root, 'mac')
        device.atomic_json(path, {'pid': 12345, 'birth': 'Tue Nov 3 12:00:00 2026'})
        alive = True

        def kill(pid, sig):
            nonlocal alive
            self.assertEqual(pid, 12345)
            if sig == signal.SIGTERM:
                alive = False
            elif not alive:
                raise ProcessLookupError()

        with mock.patch.object(device.os, 'kill', side_effect=kill) as os_kill, mock.patch.object(device, 'pid_birth', return_value='Tue Nov 3 12:00:00 2026'), mock.patch.object(device, 'text_run', return_value='S'):
            code, result = self.invoke('stop')
        self.assertEqual((code, result['pid']), (0, 12345))
        self.assertEqual([call.args for call in os_kill.call_args_list if call.args[1] != 0], [(12345, signal.SIGTERM)])
        self.assertFalse(path.exists())

    def test_mac_stop_refuses_reused_pid(self):
        device.atomic_json(device.state_path(self.root, 'mac'), {'pid': 12345, 'birth': 'old'})
        with mock.patch.object(device.os, 'kill') as kill, mock.patch.object(device, 'pid_birth', return_value='new'), mock.patch.object(device, 'text_run', return_value='S'):
            code, result = self.invoke('stop')
        self.assertEqual(code, 0)
        self.assertIn('skipped', result)
        kill.assert_called_once_with(12345, 0)

    def test_mac_exited_child_is_reaped_before_liveness_check(self):
        proc = mock.Mock()
        proc.poll.return_value = 0
        device.APP_PROCESSES[12345] = proc
        with mock.patch.object(device.os, 'kill') as kill:
            self.assertFalse(device.pid_alive(12345))
        proc.poll.assert_called_once_with()
        self.assertNotIn(12345, device.APP_PROCESSES)
        kill.assert_not_called()

    def test_mac_launch_records_popen_pid_and_bridge_environment(self):
        app = device.default_app(self.root, 'mac')
        (app / 'Contents').mkdir(parents=True)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'Game'}))
        proc = mock.Mock(pid=4321)
        proc.poll.return_value = None
        with mock.patch.object(device.subprocess, 'Popen', return_value=proc) as popen, mock.patch.object(device, 'pid_birth', return_value='birth'):
            code, _ = self.invoke('launch')
        self.assertEqual(code, 0)
        self.assertEqual(popen.call_args.args[0], [str(app / 'Contents/MacOS/Game')])
        self.assertEqual(popen.call_args.kwargs['env']['GB_AGENT_BRIDGE'], '1')
        self.assertEqual(device.read_state(device.state_path(self.root, 'mac'))['pid'], 4321)
        self.assertEqual(popen.call_args.kwargs['env']['GB_AGENT_BRIDGE_TOKEN'],
                         device.read_state(device.state_path(self.root, 'mac'))['token'])
        self.assertIs(device.APP_PROCESSES[4321], proc)
        with mock.patch.object(device, 'own_mac_alive', return_value=True), mock.patch.object(device.subprocess, 'Popen') as popen:
            self.assertEqual(self.invoke('launch')[0], 3)
            popen.assert_not_called()

    def ios_fixture(self):
        app = self.root / 'Unsigned.app'
        (app / 'Frameworks/SDK.framework').mkdir(parents=True)
        (app / 'Frameworks/helper.dylib').write_bytes(b'framework')
        (app / 'Game.debug.dylib').write_bytes(b'debug')
        (app / '__preview.dylib').write_bytes(b'preview')
        profile = self.root / 'profile.mobileprovision'
        profile.write_bytes(b'profile')
        entitlements = {'application-identifier': '8CTD4H39RN.' + device.BUNDLE,
                        'com.apple.developer.team-identifier': '8CTD4H39RN',
                        'get-task-allow': True, 'aps-environment': 'development',
                        'com.apple.security.application-groups': ['group.test'],
                        'keychain-access-groups': ['8CTD4H39RN.*'],
                        'com.apple.developer.associated-domains': ['applinks:never.example']}
        return app, profile, {'Entitlements': entitlements}

    def test_ios_signing_order_and_entitlements(self):
        app, profile, data = self.ios_fixture()
        identity = 'A' * 40

        def run(command, **kwargs):
            stdout = (f'1) {identity} "Apple Development: Developer (TEAM)"\n'.encode()
                      if command[0] == 'security' else b'')
            return subprocess.CompletedProcess(command, 0, stdout, b'')

        with mock.patch.object(device, 'provisioning_profile', return_value=(profile, data)), external_commands(side_effect=run) as external, mock.patch.object(device, 'devicectl', return_value={}) as install:
            code, result = self.invoke('install', '--platform', 'ios', '--device', 'UDID', '--app', str(app))
        self.assertEqual(code, 0)
        commands = [call.args[0] for call in external.call_args_list if call.args[0][0] == 'codesign']
        self.assertEqual([Path(command[-1]).name for command in commands],
                         ['SDK.framework', 'helper.dylib', 'Game.debug.dylib', '__preview.dylib', 'Unsigned.app', 'Unsigned.app'])
        self.assertEqual(commands[-1][1:4], ['-v', '--deep', '--strict'])
        self.assertIn('--entitlements', commands[-2])
        self.assertTrue(all('--entitlements' not in command for command in commands[:-2]))
        entitlements = plistlib.loads((self.root / '.gb-agent/device/ios-signed/entitlements.plist').read_bytes())
        self.assertNotIn('com.apple.developer.associated-domains', entitlements)
        self.assertEqual(entitlements['keychain-access-groups'], ['8CTD4H39RN.' + device.BUNDLE])
        self.assertEqual(result['missing_entitlements'], [])
        self.assertEqual(install.call_count, 1)
        self.assertEqual(install.call_args.kwargs['timeout'], 600)
        self.assertTrue(all(call.kwargs['timeout'] == 600 for call in external.call_args_list
                            if call.args[0][0] == 'codesign'))

    def test_ios_verify_failure_never_installs(self):
        app, profile, data = self.ios_fixture()
        data['Entitlements'].pop('aps-environment')

        def run(command, **kwargs):
            if command[0] == 'security':
                return subprocess.CompletedProcess(command, 0, ('A' * 40 + ' "Apple Development: Dev"').encode(), b'')
            return subprocess.CompletedProcess(command, 1 if '-v' in command else 0, b'', b'')

        with mock.patch.object(device, 'provisioning_profile', return_value=(profile, data)), external_commands(side_effect=run), mock.patch.object(device, 'devicectl') as install:
            code, _ = self.invoke('install', '--platform', 'ios', '--device', 'UDID', '--app', str(app))
        self.assertEqual(code, 3)
        install.assert_not_called()
        entitlements = plistlib.loads((self.root / '.gb-agent/device/ios-signed/entitlements.plist').read_bytes())
        self.assertNotIn('aps-environment', entitlements)

    def test_ios_multiple_identities_require_selection(self):
        app, profile, data = self.ios_fixture()
        output = ('A' * 40 + ' "Apple Development: A"\n' + 'B' * 40 + ' "Apple Development: B"').encode()
        with mock.patch.object(device, 'provisioning_profile', return_value=(profile, data)), external_commands(return_value=subprocess.CompletedProcess([], 0, output, b'')), mock.patch.object(device, 'devicectl') as install:
            code, _ = self.invoke('install', '--platform', 'ios', '--device', 'UDID', '--app', str(app))
        self.assertEqual(code, 2)
        install.assert_not_called()

    def test_ios_launch_stop_tracks_device_pid(self):
        with mock.patch.object(device, 'devicectl', return_value={'result': {'process': {'processIdentifier': 555}}}) as external:
            self.assertEqual(self.invoke('launch', '--platform', 'ios', '--device', 'UDID')[0], 0)
            call = external.call_args.args
            env = json.loads(call[call.index('--environment-variables') + 1])
            self.assertEqual(env['GB_AGENT_BRIDGE'], '1')
            self.assertEqual(env['GB_AGENT_BRIDGE_PORT'], '17880')
            self.assertEqual(env['GB_AGENT_BRIDGE_TOKEN'], device.read_state(device.state_path(self.root, 'ios', 'UDID'))['token'])
            self.assertEqual(self.invoke('stop', '--platform', 'ios', '--device', 'UDID')[0], 0)
            self.assertEqual(external.call_args.args[-2:], ('--pid', '555'))

    def test_build_commands_log_exit_and_artifact(self):
        for platform in ('mac', 'android', 'ios'):
            with self.subTest(platform=platform):
                artifact = (self.root / '.gb-agent/build/android/artifacts/game.apk'
                            if platform == 'android' else device.default_app(self.root, platform))
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.touch()
                os.utime(artifact, (time.time() + 1, time.time() + 1))
                with mock.patch.object(device, 'apple_env', return_value={'ENV': 'loaded'}), external_commands(return_value=subprocess.CompletedProcess([], 0, None, None)) as external:
                    code, result = self.invoke('build', '--platform', platform)
                self.assertEqual((code, result['exit']), (0, 0))
                self.assertIn(str(artifact), result['artifacts'])
                self.assertTrue(Path(result['log']).is_file())
                call = external.call_args
                self.assertNotEqual(call.kwargs['stdout'], subprocess.PIPE)
                self.assertEqual(call.kwargs['timeout'], 5400)
                self.assertFalse(call.kwargs['shell'])
                self.assertTrue(call.kwargs['start_new_session'])
                if platform == 'ios':
                    self.assertIn('IPHONEOS_DEPLOYMENT_TARGET=15.0', call.args[0])
                    self.assertIn('generic/platform=iOS', call.args[0])
                else:
                    self.assertEqual(call.args[0][:3], ['python3', str(self.root / '.gb-agent/tools/gb_env.py'), 'build'])
        with mock.patch.object(device, 'apple_env', return_value={}), external_commands(return_value=subprocess.CompletedProcess([], 17, None, None)):
            code, result = self.invoke('build')
        self.assertEqual((code, result['exit']), (3, 17))
        self.assertTrue(Path(result['log']).is_file())

    def test_timeout_upper_bound(self):
        for value in ('601', '0', '-1', 'inf'):
            self.assertEqual(self.invoke('ping', '--timeout', value)[0], 2)
        self.assertEqual(self.args('ping', '--timeout', '600').timeout, 600)

    def test_state_is_outside_checkout_and_ignores_legacy_state(self):
        checkout = self.root / 'checkout'
        checkout.mkdir()
        legacy = checkout / '.gb-agent/device/mac.json'
        device.atomic_json(legacy, {'pid': 12345, 'birth': 'forged'})
        path = device.state_path(checkout, 'mac')
        self.assertFalse(path.is_relative_to(checkout))
        self.assertEqual(path.parent.name, device.hashlib.sha256(str(checkout).encode()).hexdigest()[:16])
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(device.read_state(path), {})
        with mock.patch.object(device.os, 'kill') as kill:
            self.assertIn('skipped', device.stop_mac(checkout))
        kill.assert_not_called()

    def test_bridge_token_is_automatically_attached_and_redacted(self):
        token = 'a' * 32
        device.atomic_json(device.state_path(self.root, 'mac'), {'token': token})
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock

        def receive(_size):
            request = json.loads(sock.sendall.call_args.args[0])
            self.assertEqual(request['token'], token)
            return json.dumps({'id': request['id'], 'ok': True,
                               'result': {'echo': token}}).encode() + b'\n'
        sock.recv.side_effect = receive
        with mock.patch.object(device.socket, 'create_connection', return_value=sock):
            code, result = self.invoke('ping')
        self.assertEqual(code, 0)
        self.assertNotIn(token, json.dumps(result))

    def test_bridge_rejects_nonfinite_and_nonobject_result(self):
        for raw_result in ('NaN', 'Infinity', '-Infinity', '[]', 'null', '42'):
            with self.subTest(result=raw_result):
                sock = mock.MagicMock()
                sock.__enter__.return_value = sock

                def receive(_size):
                    request_id = json.loads(sock.sendall.call_args.args[0])['id']
                    return ('{"id":%d,"ok":true,"result":%s}\n' % (request_id, raw_result)).encode()
                sock.recv.side_effect = receive
                with mock.patch.object(device.socket, 'create_connection', return_value=sock):
                    self.assertEqual(self.invoke('scene')[0], 3)

    def test_devicectl_rejects_nonfinite_json(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            with mock.patch.object(device, 'apple_env', return_value={}), mock.patch.object(device, 'text_run', return_value='{"value":' + value + '}'):
                with self.assertRaises(device.DeviceError) as error:
                    device.devicectl(self.root, 'list', 'devices')
                self.assertEqual(error.exception.code, 3)

    def test_stdout_serialization_failure_is_one_json_error(self):
        with mock.patch.object(device, 'execute', return_value={'value': float('nan')}):
            self.assertEqual(self.invoke('ping')[0], 3)

    def test_wait_scene_retries_connection_failures(self):
        with mock.patch.object(device, 'bridge_request', side_effect=[device.DeviceError(4, 'offline'),
                {'ok': True, 'result': {'top': 'Lobby'}}]), mock.patch.object(device.time, 'sleep'):
            self.assertEqual(self.invoke('wait-scene', 'Lobby')[0], 0)
        with mock.patch.object(device, 'bridge_request', side_effect=device.DeviceError(4, 'offline')):
            self.assertEqual(self.invoke('wait-scene', 'Lobby', '--timeout', '.01')[0], 5)

    def test_external_timeout_kills_process_group(self):
        proc = mock.Mock(pid=12345)
        proc.communicate.side_effect = [subprocess.TimeoutExpired('tool', 1), (b'', b'')]
        with mock.patch.object(device.subprocess, 'Popen', return_value=proc) as popen, mock.patch.object(device.os, 'killpg') as kill:
            with self.assertRaises(device.DeviceError) as error:
                device.run(['tool'], timeout=1)
        self.assertEqual(error.exception.code, 5)
        self.assertTrue(error.exception.details['killed_process_group'])
        kill.assert_called_once_with(12345, signal.SIGKILL)
        self.assertEqual(proc.communicate.call_count, 2)
        self.assertFalse(popen.call_args.kwargs['shell'])
        self.assertTrue(popen.call_args.kwargs['start_new_session'])

    def test_build_timeout_keeps_group_cleanup_evidence(self):
        proc = mock.Mock(pid=12345)
        proc.communicate.side_effect = [subprocess.TimeoutExpired('build', 5400), (b'', b'')]
        with mock.patch.object(device, 'apple_env', return_value={}), mock.patch.object(device.subprocess, 'Popen', return_value=proc), mock.patch.object(device.os, 'killpg') as kill:
            code, result = self.invoke('build')
        self.assertEqual(code, 5)
        self.assertTrue(result['killed_process_group'])
        self.assertTrue(Path(result['log']).is_file())
        self.assertIsNone(result['exit'])
        kill.assert_called_once_with(12345, signal.SIGKILL)

    def test_keyboard_interrupt_cleans_group_and_emits_one_json(self):
        proc = mock.Mock(pid=12345)
        proc.communicate.side_effect = [KeyboardInterrupt(), (b'', b'')]
        with mock.patch.object(device.subprocess, 'Popen', return_value=proc), mock.patch.object(device.os, 'killpg') as kill:
            code, result = self.invoke('os-tap', '1', '2', '--platform', 'android', '--device', 'SERIAL')
        self.assertEqual((code, result['error']), (130, 'interrupted'))
        kill.assert_called_once_with(12345, signal.SIGKILL)

    def test_mac_zombie_is_not_alive(self):
        with mock.patch.object(device, 'text_run', return_value='Z+'), mock.patch.object(device.os, 'kill') as kill:
            self.assertFalse(device.pid_alive(12345))
        kill.assert_not_called()

    def test_mac_and_build_locks_are_separate_by_checkout(self):
        other = self.root / 'other'
        other.mkdir()
        args = self.args('ping')
        second = argparse.Namespace(**vars(args))
        second.checkout = str(other)
        with device.device_lock(args), device.device_lock(second), device.device_lock(self.args('build')):
            self.assertEqual(len(list(device.LOCK_ROOT.glob('*.lock'))), 3)

    def test_identity_substring_and_extension_signing_order(self):
        app, profile, data = self.ios_fixture()
        (app / 'PlugIns/Widget.appex/Frameworks/Nested.framework').mkdir(parents=True)
        identities = ('A' * 40 + ' "Apple Development: Alice (TEAM)"\n' +
                      'B' * 40 + ' "Apple Development: Bob (TEAM)"').encode()
        with mock.patch.object(device, 'provisioning_profile', return_value=(profile, data)), external_commands(return_value=subprocess.CompletedProcess([], 0, identities, b'')) as external:
            device.sign_ios(self.args('install', '--identity', 'Alice'), app)
        names = [Path(call.args[0][-1]).name for call in external.call_args_list if call.args[0][0] == 'codesign']
        self.assertLess(names.index('Nested.framework'), names.index('Widget.appex'))
        self.assertLess(names.index('Widget.appex'), names.index('Game.debug.dylib'))
        self.assertEqual(names[-2:], ['Unsigned.app', 'Unsigned.app'])
        with mock.patch.object(device, 'provisioning_profile', return_value=(profile, data)), external_commands(return_value=subprocess.CompletedProcess([], 0, identities, b'')):
            with self.assertRaises(device.DeviceError) as error:
                device.sign_ios(self.args('install', '--identity', 'TEAM'), app)
            self.assertEqual(error.exception.code, 2)

    def test_android_activity_shell_quoting_and_launch_token(self):
        activity = device.PACKAGE + '/.Main$Nested'

        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, activity.encode() if 'resolve-activity' in command else b'', b'')
        with external_commands(side_effect=run) as external:
            code, _ = self.invoke('launch', '--platform', 'android', '--device', 'SERIAL')
        self.assertEqual(code, 0)
        commands = [call.args[0] for call in external.call_args_list]
        start = next(command for command in commands if 'start' in command)
        self.assertEqual(start[-1], device.shlex.quote(activity))
        token = device.read_state(device.state_path(self.root, 'android', 'SERIAL'))['token']
        self.assertEqual(len(token), 32)
        self.assertIn([device.ADB, '-s', 'SERIAL', 'shell', 'setprop', 'debug.gb.agentbridge.token', token], commands)

    def test_android_build_rejects_stale_apk(self):
        artifact = self.root / '.gb-agent/build/android/artifacts/stale.apk'
        artifact.parent.mkdir(parents=True)
        artifact.touch()
        os.utime(artifact, (1, 1))
        with mock.patch.object(device, 'apple_env', return_value={}), external_commands(return_value=subprocess.CompletedProcess([], 0, None, None)):
            code, result = self.invoke('build', '--platform', 'android')
        self.assertEqual(code, 3)
        self.assertEqual(result['artifacts'], [])

    def test_direct_cli_output_follows_caller_symlink(self):
        target = self.root / 'real'
        target.mkdir()
        (self.root / 'link').symlink_to(target, target_is_directory=True)
        args = self.args('screenshot', 'link/image.png')
        with device.output_file(args, self.root / 'link/image.png') as stream:
            stream.write(b'PNG')
        self.assertEqual((target / 'image.png').read_bytes(), b'PNG')

    def test_output_fd_survives_parent_swap_and_rejects_symlink(self):
        args = self.args('screenshot', 'output/image.png')
        args.daemon = True
        directory = self.root / 'output'
        directory.mkdir()
        outside = self.root / 'elsewhere'
        outside.mkdir()
        original_open = os.open

        def swap(path, flags, *positional, **kwargs):
            if path == 'image.png':
                directory.rename(self.root / 'pinned')
                directory.symlink_to(outside, target_is_directory=True)
            return original_open(path, flags, *positional, **kwargs)
        with mock.patch.object(device.os, 'open', side_effect=swap), device.output_file(args, directory / 'image.png') as stream:
            stream.write(b'PNG')
        self.assertEqual((self.root / 'pinned/image.png').read_bytes(), b'PNG')
        self.assertFalse((outside / 'image.png').exists())
        with self.assertRaises(OSError), device.output_file(args, directory / 'second.png'):
            pass


class QueueTests(DeviceTestCase):
    def setUp(self):
        super().setUp()
        self.queue = self.root / 'queue'
        for name in ('req', 'work', 'res'):
            (self.queue / name).mkdir(parents=True)

    def request(self, request_id='test', op='ping', args=None):
        path = self.queue / 'req' / (request_id + '.json')
        path.write_text(json.dumps({'id': request_id, 'op': op, 'args': args or {}}))
        return path

    def response(self, request_id='test'):
        return json.loads((self.queue / 'res' / (request_id + '.json')).read_text())

    def test_queue_rejects_nonallowed_operations(self):
        for index, op in enumerate(('serve', 'shell', 'exec', 'rm')):
            with self.subTest(op=op), mock.patch.object(device, 'execute') as execute:
                path = self.request(str(index), op)
                device.process_request(path, self.queue, self.root)
                self.assertEqual(self.response(str(index))['exit'], 2)
                execute.assert_not_called()

    def test_queue_rejects_escape_and_different_checkout(self):
        (self.root / 'outside-link').symlink_to(self.root.parent, target_is_directory=True)
        cases = [('screenshot', {'out': '../escape.png'}), ('screenshot', {'out': '/tmp/escape.png'}),
                 ('screenshot', {'out': 'outside-link/escape.png'}), ('crashes', {'platform': 'ios', 'device': 'UDID', 'fetch': '../outside'}),
                 ('install', {'platform': 'android', 'device': 'SERIAL', 'apk': '../outside.apk'}),
                 ('ping', {'checkout': str(self.root.parent)}), ('ping', {'checkout': '.'})]
        for index, (op, args) in enumerate(cases):
            with self.subTest(args=args), mock.patch.object(device, 'execute') as execute:
                device.process_request(self.request(str(index), op, args), self.queue, self.root)
                self.assertEqual(self.response(str(index))['exit'], 2)
                execute.assert_not_called()

    def test_queue_atomic_claim_and_publication(self):
        path = self.request('atomic', 'install', {'platform': 'mac'})
        published = []
        original = os.link

        def link(source, destination, **kwargs):
            self.assertEqual(kwargs['src_dir_fd'], kwargs['dst_dir_fd'])
            self.assertFalse((self.queue / 'res' / destination).exists())
            self.assertEqual(json.loads((self.queue / 'res' / source).read_text())['exit'], 0)
            published.append((source, destination))
            original(source, destination, **kwargs)

        def execute(args):
            self.assertFalse(path.exists())
            self.assertTrue((self.queue / 'work/atomic.json').exists())
            self.assertFalse((self.queue / 'res/atomic.json').exists())
            print('progress', file=sys.stderr)
            return {'ok': True, 'skipped': True}

        with mock.patch.object(device, 'execute', side_effect=execute), mock.patch.object(device.os, 'link', side_effect=link):
            self.assertTrue(device.process_request(path, self.queue, self.root))
        result = self.response('atomic')
        self.assertEqual(result['stderr_tail'], 'progress\n')
        self.assertLessEqual(result['started'], result['ended'])
        self.assertEqual(set(result), {'id', 'op', 'exit', 'stdout_json', 'stderr_tail', 'started', 'ended'})
        self.assertEqual(len(published), 1)
        self.assertEqual(list((self.queue / 'work').iterdir()), [])
        self.assertEqual(len(list((self.queue / 'res').iterdir())), 1)

    def test_queue_argument_types_and_unknown_options(self):
        for index, args in enumerate(({'shell': 'touch bad'}, {'restart': 'true'}, {'app': []}, {'platform': None})):
            with self.subTest(args=args), mock.patch.object(device, 'execute') as execute:
                device.process_request(self.request(str(index), 'launch', args), self.queue, self.root)
                self.assertEqual(self.response(str(index))['exit'], 2)
                execute.assert_not_called()

    def test_queue_rejects_bad_id_without_path_traversal(self):
        path = self.queue / 'req/bad.json'
        path.write_text(json.dumps({'id': '../outside', 'op': 'ping'}))
        with mock.patch.object(device, 'execute') as execute:
            device.process_request(path, self.queue, self.root)
        execute.assert_not_called()
        self.assertEqual(self.response('bad')['exit'], 2)
        self.assertFalse((self.queue / 'outside.json').exists())

    def test_queue_duplicate_result_not_reexecuted(self):
        (self.queue / 'res/test.json').write_text('{"original":true}')
        with mock.patch.object(device, 'execute') as execute:
            self.assertTrue(device.process_request(self.request(), self.queue, self.root))
        execute.assert_not_called()
        self.assertTrue(self.response()['original'])
        self.assertEqual(len(list((self.queue / 'work').glob('dup-test-*.json'))), 1)
        self.assertEqual(self.response('test.dup')['exit'], 2)

    def test_queue_busy_publishes_failure(self):
        with device.device_lock(self.args('ping')):
            device.process_request(self.request(), self.queue, self.root)
        result = self.response()
        self.assertEqual((result['exit'], result['stdout_json']['error']), (3, 'device busy'))

    def test_queue_rechecks_all_directory_symlinks(self):
        path = self.request()
        for name in ('req', 'work', 'res'):
            directory = self.queue / name
            saved = self.queue / (name + '-saved')
            directory.rename(saved)
            directory.symlink_to(saved, target_is_directory=True)
            try:
                with mock.patch.object(device, 'execute') as execute, contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertFalse(device.process_request(path, self.queue, self.root))
                execute.assert_not_called()
                self.assertIn('queue request rejected', errors.getvalue())
            finally:
                directory.unlink()
                saved.rename(directory)
        with mock.patch.object(device, 'execute', return_value={'ok': True}):
            self.assertTrue(device.process_request(path, self.queue, self.root))

    def test_queue_response_uses_pinned_res_fd(self):
        outside = self.root / 'outside'
        outside.mkdir()

        def execute(args):
            (self.queue / 'res').rename(self.queue / 'res-pinned')
            (self.queue / 'res').symlink_to(outside, target_is_directory=True)
            return {'ok': True}
        with mock.patch.object(device, 'execute', side_effect=execute):
            self.assertTrue(device.process_request(self.request(), self.queue, self.root))
        self.assertTrue((self.queue / 'res-pinned/test.json').is_file())
        self.assertFalse((outside / 'test.json').exists())
        with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(device, 'execute') as execute:
            self.assertFalse(device.process_request(self.request('next'), self.queue, self.root))
        execute.assert_not_called()

    def test_queue_rejects_replaced_root_and_nondirectory(self):
        fd = os.open(self.queue, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.queue.rename(self.root / 'old-queue')
            for name in ('req', 'work', 'res'):
                (self.queue / name).mkdir(parents=True)
            with mock.patch.object(device, 'execute') as execute, contextlib.redirect_stderr(io.StringIO()):
                self.assertFalse(device.process_request(self.request(), self.queue, self.root, fd))
            execute.assert_not_called()
        finally:
            os.close(fd)
        (self.queue / 'res').rmdir()
        (self.queue / 'res').write_text('not a directory')
        with mock.patch.object(device, 'execute') as execute, contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(device.process_request(self.queue / 'req/test.json', self.queue, self.root))
        execute.assert_not_called()

    def test_queue_rejects_symlink_directory_and_oversized_request(self):
        target = self.root / 'target.json'
        target.write_text('{"id":"target","op":"ping"}')
        (self.queue / 'req/link.json').symlink_to(target)
        (self.queue / 'req/directory.json').mkdir()
        (self.queue / 'req/huge.json').write_bytes(b' ' * (1024 * 1024 + 1))
        for name in ('link', 'directory', 'huge'):
            with mock.patch.object(device, 'execute') as execute:
                self.assertTrue(device.process_request(self.queue / 'req' / (name + '.json'), self.queue, self.root))
            self.assertEqual(self.response(name)['exit'], 2)
            execute.assert_not_called()

    def test_queue_cleanup_and_unexpected_failure_publish_then_continue(self):
        original = os.unlink

        def unlink(path, **kwargs):
            if path == 'cleanup.json':
                raise PermissionError('cleanup denied')
            return original(path, **kwargs)
        with mock.patch.object(device, 'execute', return_value={'ok': True}), mock.patch.object(device.os, 'unlink', side_effect=unlink):
            self.assertTrue(device.process_request(self.request('cleanup'), self.queue, self.root))
        self.assertEqual(self.response('cleanup')['exit'], 2)
        with mock.patch.object(device, 'execute', side_effect=RuntimeError('unexpected')):
            self.assertTrue(device.process_request(self.request('unexpected'), self.queue, self.root))
        self.assertEqual(self.response('unexpected')['exit'], 2)
        with mock.patch.object(device, 'execute', return_value={'ok': True}):
            self.assertTrue(device.process_request(self.request('next'), self.queue, self.root))
        self.assertEqual(self.response('next')['exit'], 0)

    def test_queue_serialization_failure_publishes_error(self):
        with mock.patch.object(device, 'execute', return_value={'value': float('nan')}):
            self.assertTrue(device.process_request(self.request(), self.queue, self.root))
        self.assertEqual(self.response()['exit'], 3)

    def test_daemon_rejects_host_port_app_and_excess_timeout(self):
        for index, (op, args) in enumerate((('ping', {'host': '127.0.0.1'}), ('ping', {'port': 17880}),
                ('launch', {'app': 'game.app'}), ('ping', {'timeout': 601}))):
            with mock.patch.object(device, 'execute') as execute:
                device.process_request(self.request(str(index), op, args), self.queue, self.root)
            self.assertEqual(self.response(str(index))['exit'], 2)
            execute.assert_not_called()
        args = device.request_args({'op': 'build', 'args': {'timeout': 999999}}, self.root)
        self.assertEqual(args.timeout, 10)
        self.assertTrue(args.daemon)

    def test_serve_signal_finishes_current_request(self):
        self.request('first', 'install', {'platform': 'mac'})
        self.request('second', 'install', {'platform': 'mac'})
        handlers = {}

        def register(sig, handler):
            previous = handlers.get(sig, signal.SIG_DFL)
            handlers[sig] = handler
            return previous

        def execute(args):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return {'ok': True, 'finished': True}

        with mock.patch.object(device.signal, 'signal', side_effect=register), mock.patch.object(device, 'execute', side_effect=execute):
            result = device.serve(self.args('serve', '--queue', str(self.queue)))
        self.assertTrue(result['stopped'])
        self.assertTrue(self.response('first')['stdout_json']['finished'])
        self.assertTrue((self.queue / 'req/second.json').exists())
        self.assertFalse((self.queue / 'res/second.json').exists())


if __name__ == '__main__':
    unittest.main()
