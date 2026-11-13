"""자동화 테스트 도구 단위 테스트 — 기기 없이 가짜 브리지로 돈다.  python3 -m unittest test_autotest (tools 폴더에서)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'device_flows'))

import answer_key  # noqa: E402
import case_runner  # noqa: E402
import imgdiff  # noqa: E402
import judge  # noqa: E402
import qa_common as qc  # noqa: E402
import report  # noqa: E402
import rewind_runner  # noqa: E402
import sheet_import  # noqa: E402
from flowlib import Device  # noqa: E402


def make_png(path, w, h, color, box=None, box_color=(255, 255, 255)):
    """sips 로 단색 PNG 를 만든다(BMP 를 직접 쓰고 sips 로 PNG 변환)."""
    import struct
    stride = (w * 3 + 3) & ~3
    rows = []
    for y in range(h):
        line = bytearray()
        for x in range(w):
            c = box_color if box and box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3] else color
            line += bytes((c[2], c[1], c[0]))
        rows.append(bytes(line) + b'\0' * (stride - w * 3))
    data = b''.join(rows)
    header = b'BM' + struct.pack('<IHHI', 54 + len(data), 0, 0, 54) + struct.pack('<IiiHHIIiiII', 40, w, -h, 1, 24, 0, len(data), 2835, 2835, 0, 0)
    bmp = path + '.bmp'
    with open(bmp, 'wb') as f:
        f.write(header + data)
    subprocess.run(['sips', '-s', 'format', 'png', bmp, '--out', path], capture_output=True, check=True)
    os.remove(bmp)


class FakeBridge:
    """화면 하나짜리 가짜 게임. tap 하면 scenes 순서대로 넘어간다."""

    def __init__(self, png, nodes_by_scene, start='SceneNavigator'):
        self.png = png
        self.nodes_by_scene = nodes_by_scene
        self.scene = start
        self.taps = []

    def __call__(self, *args):
        cmd = args[0]
        if cmd == 'ping':
            return {'ok': True, 'result': {'visibleSize': [568, 320], 'visibleOrigin': [0, 0], 'frameSize': [1136, 640]}}
        if cmd == 'scene':
            return {'ok': True, 'result': {'top': self.scene}}
        if cmd == 'tree':
            return {'ok': True, 'result': {'nodes': self.nodes_by_scene.get(self.scene, [])}}
        if cmd == 'screenshot':
            shutil.copy(self.png, args[1])
            return {'ok': True}
        if cmd == 'tap':
            target = args[2] if args[1] == '--node' else f'{args[2]},{args[4]}'
            self.taps.append(target)
            if target == '_btnProbability':
                self.scene = 'PopShopGachaProbability'
            elif target == '_btnClose' or (args[1] == '--x' and self.scene == 'PopShopGachaProbability'):
                self.scene = 'SceneNavigator'
            return {'ok': True, 'result': {}}
        if cmd == 'swipe':
            return {'ok': True}
        return {'ok': False, 'error': f'unknown {cmd}'}


LOBBY_NODES = [
    {'inst': '_btnShopGacha', 'receiver': 'button', 'rect': [10, 10, 50, 50], 'enabled': True},
    {'inst': '_btnProbability', 'receiver': 'button', 'rect': [400, 250, 80, 30], 'text': '확률 정보'},
    {'inst': '_labelWallet', 'text': '9,999,900', 'rect': [400, 290, 100, 20]},
    {'inst': '_labelTitle', 'text': '아이싱 뽑기', 'rect': [200, 280, 100, 20]},
]
PROB_NODES = [
    {'inst': '_btnTabIcing', 'receiver': 'button', 'enabled': False, 'owner': 'PopShopGachaProbability', 'rect': [50, 200, 60, 30]},
    {'inst': '_btnClose', 'receiver': 'button', 'owner': 'PopShopGachaProbability', 'rect': [500, 280, 30, 30]},
    {'owner': 'CellShopGachaProbabilityList', 'text': '아이싱', 'rect': [100, 100, 300, 30]},
]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (qc.ANSWERS, qc.RUNS)
        qc.ANSWERS = os.path.join(self.tmp, 'answers')
        qc.RUNS = os.path.join(self.tmp, 'runs')
        self.png = os.path.join(self.tmp, 'a.png')
        make_png(self.png, 160, 90, (20, 40, 200))

    def tearDown(self):
        qc.ANSWERS, qc.RUNS = self.saved
        shutil.rmtree(self.tmp)

    def runner(self, bridge, suite, out):
        dev = Device('mac', self.tmp, out, runner=bridge)
        return case_runner.Runner(dev, suite, 'mac', out)


SUITE = {'suite': 'unit', 'cases': [
    {'id': 'TC-01', 'title': '확률', 'auto': True, 'start': 'here', 'steps': [
        {'do': 'tap', 'target': '_btnProbability'},
        {'do': 'wait_scene', 'scene': 'PopShopGachaProbability', 'timeout': 5},
        {'do': 'checkpoint', 'name': 'prob', 'settle': 0, 'expect': {
            'scene': 'PopShopGachaProbability', 'disabled': ['_btnTabIcing'],
            'count': [{'owner': 'CellShopGachaProbabilityList', 'min': 1}]}},
        {'do': 'close_popup', 'owner': 'PopShopGachaProbability'},
    ]},
    {'id': 'TC-02', 'title': '수동', 'auto': False, 'reason': '소리'},
    {'id': 'TC-03', 'title': '재화', 'auto': True, 'spends': True, 'start': 'here',
     'steps': [{'do': 'checkpoint', 'name': 'x'}]},
]}


class TestValidate(unittest.TestCase):
    def test_sample_suite_is_valid(self):
        suite = qc.load_json(os.path.join(qc.CASES, 'sample-mycookie-gacha.json'))
        self.assertEqual(case_runner.validate(suite), [])

    def test_errors(self):
        bad = {'cases': [
            {'id': 'A', 'auto': None},
            {'id': 'B', 'auto': False},
            {'id': 'C', 'auto': True, 'steps': [{'do': 'fly'}]},
            {'id': 'D', 'auto': True, 'steps': [{'do': 'checkpoint', 'name': 'n', 'expect': {'present': [{'bogus': 1}]}}]},
            {'id': 'E', 'auto': True, 'steps': [{'do': 'swipe'}, {'do': 'checkpoint', 'name': 'n'}]},
        ]}
        errs = '\n'.join(case_runner.validate(bad))
        for frag in ('case A: auto 가 비어', 'case B: auto=false 면 reason', "do='fly'", 'case D checkpoint n', 'case E step 0 (swipe)'):
            self.assertIn(frag, errs)


class TestExpect(unittest.TestCase):
    def test_checks(self):
        nodes = PROB_NODES + [{'inst': '_btnX', 'receiver': 'button', 'blockedBy': 3, 'blockedByDesc': 'Pop/_bg'}]
        res = qc.check_expect({'scene': 'PopShopGachaProbability', 'disabled': ['_btnTabIcing'], 'absent': ['로딩'],
                               'tappable': ['_btnClose', '_btnX'], 'present': [{'text_contains': '아이'}],
                               'text': [{'select': {'owner': 'CellShopGachaProbabilityList'}, 'equals': '아이싱'}]},
                              'PopShopGachaProbability', nodes)
        self.assertEqual([r['ok'] for r in res], [True, True, True, True, False, True, True])
        self.assertIn('Pop/_bg', res[4]['detail'])

    def test_order(self):
        def card(text, x, y):
            return {'owner': 'Card', 'inst': '_labelName', 'text': text, 'rect': [x, y, 70, 30]}
        sel = {'owner': 'Card', 'inst': '_labelName'}
        # 위 줄(y 큼)부터, 줄 안에서는 왼쪽부터
        on = [card('C', 300, 50), card('my', 100, 160), card('A', 200, 160), card('B', 300, 160), card('D', 100, 50)]
        off = [card('A', 100, 160), card('B', 200, 160), card('my', 300, 160), card('C', 100, 50)]
        self.assertEqual(qc.screen_order(on, sel), ['my', 'A', 'B', 'D', 'C'])
        res = qc.check_expect({'order': [{'select': sel, 'first': ['my']}]}, 'S', on)
        self.assertEqual([r['ok'] for r in res], [True])
        res = qc.check_expect({'order': [{'select': sel, 'notFirst': ['my'], 'sameAs': 'on', 'ignore': ['my']}]},
                              'S', off, {'on': on})
        # off 는 A B C (my 뺌), on 은 A B D C — 앞 3개 중 셋째가 다르다
        self.assertEqual([r['ok'] for r in res], [True, False])
        off2 = [card('A', 100, 160), card('B', 200, 160), card('my', 300, 160), card('D', 100, 50)]
        res = qc.check_expect({'order': [{'select': sel, 'sameAs': 'on', 'ignore': ['my']}]}, 'S', off2, {'on': on})
        self.assertTrue(res[0]['ok'])
        res = qc.check_expect({'order': [{'select': sel, 'sameAs': 'none'}]}, 'S', off2, {})
        self.assertFalse(res[0]['ok'])

    def test_when(self):
        nodes = [{'inst': '_spriteCheck'}]
        self.assertTrue(qc.check_when({'present': '_spriteCheck'}, nodes))
        self.assertFalse(qc.check_when({'absent': '_spriteCheck'}, nodes))
        self.assertTrue(qc.check_when({'absent': '_other'}, nodes))

    def test_validate_order_when(self):
        suite = {'cases': [{'id': 'O', 'auto': True, 'steps': [
            {'do': 'tap', 'target': 'x', 'when': {'maybe': 'x'}},
            {'do': 'checkpoint', 'name': 'b', 'expect': {'order': [{'select': '_l', 'sameAs': 'a'}]}},
            {'do': 'checkpoint', 'name': 'a', 'expect': {'order': [{'select': '_l'}]}},
        ]}]}
        errs = '\n'.join(case_runner.validate(suite))
        for frag in ('step 0: when 은', 'sameAs 「a」 는 이 checkpoint 보다 앞', 'first·notFirst·sameAs'):
            self.assertIn(frag, errs)

    def test_worst(self):
        self.assertEqual(qc.worst(['PASS', 'REVIEW', 'FAIL']), 'FAIL')
        self.assertEqual(qc.worst([]), 'NOT_RUN')


class TestGeometry(unittest.TestCase):
    def test_letterbox(self):
        # iPad: 4:3 프레임에 16:9 게임 화면이 위아래 레터박스로 들어간다
        g = {'visibleSize': [568, 320], 'visibleOrigin': [0, 0]}
        x, y, w, h = qc.to_pixels([0, 300, 100, 20], g, [2224, 1668])
        s = 2224 / 568
        self.assertEqual(x, 0)
        self.assertEqual(w, round(100 * s))
        self.assertEqual(y, round((1668 - 320 * s) / 2 + (320 - 300 - 20) * s))

    def test_signature_skips_digits(self):
        sig = qc.text_signature([{'text': '확인'}, {'text': '39일 11:22'}, {'text': 'MID : AB1'}, {'owner': 'P', 'text': '닫기'}])
        self.assertEqual(sig, ['- | 확인', 'P | 닫기'])

    def test_signature_skips_masked(self):
        nodes = [{'owner': 'Card', 'text': '용감한 쿠키'}, {'owner': 'P', 'text': '닫기'}]
        self.assertEqual(qc.text_signature(nodes, [{'owner': 'Card'}]), ['P | 닫기'])


class TestImageDiff(Base):
    def test_same_and_changed(self):
        b = os.path.join(self.tmp, 'b.png')
        make_png(b, 160, 90, (20, 40, 200), box=(10, 10, 40, 30))
        self.assertEqual(imgdiff.compare(self.png, self.png)['changed'], 0)
        r = imgdiff.compare(self.png, b)
        self.assertGreater(r['changed'], 0.05)
        self.assertTrue(r['regions'])
        x, y, w, h = r['regions'][0]
        self.assertTrue(x <= 10 and y <= 10 and x + w >= 50 and y + h >= 40, r['regions'])
        masked = imgdiff.compare(self.png, b, [(0, 0, 60, 50)])
        self.assertEqual(masked['changed'], 0)
        crops = imgdiff.crops_for(self.png, b, r['regions'], os.path.join(self.tmp, 'c'), 't')
        self.assertTrue(os.path.exists(crops[0]['actual']))


class TestRunFlow(Base):
    def test_run_baseline_judge_report(self):
        out = os.path.join(qc.RUNS, 'unit-mac-1')
        bridge = FakeBridge(self.png, {'SceneNavigator': LOBBY_NODES, 'PopShopGachaProbability': PROB_NODES})
        r = self.runner(bridge, SUITE, out)
        res = [r.run_case(c) for c in SUITE['cases']]
        self.assertEqual([x['verdict'] for x in res], ['PASS', 'NOT_RUN', 'NOT_RUN'], res[0])
        self.assertEqual(res[0]['checkpoints'][0]['baseline'], 'none')
        self.assertEqual(bridge.scene, 'SceneNavigator')  # close_popup 이 닫기 버튼 가운데(515,295)를 눌렀다
        self.assertIn('515.0,295.0', bridge.taps)
        results = {'suite': 'unit', 'platform': 'mac', 'started': 's', 'cases': res, 'suiteFile': ''}
        qc.save_json(os.path.join(out, 'results.json'), results)
        # 사람 승인 → 정답지
        self.assertEqual(answer_key.approve(out, None, None, 'tester', ''), 0)
        self.assertTrue(os.path.exists(os.path.join(qc.ANSWERS, 'unit', 'mac', 'TC-01', 'prob.png')))

        # 같은 화면 → PASS(정답지 일치)
        out2 = os.path.join(qc.RUNS, 'unit-mac-2')
        bridge.scene = 'SceneNavigator'
        cp = self.runner(bridge, SUITE, out2).run_case(SUITE['cases'][0])['checkpoints'][0]
        self.assertEqual(cp['verdict'], 'PASS', cp)
        self.assertNotEqual(cp['baseline'], 'none')

        # 글자가 바뀌고 화면 일부가 달라짐 → REVIEW → 판정 반영
        changed = os.path.join(self.tmp, 'changed.png')
        make_png(changed, 160, 90, (20, 40, 200), box=(60, 20, 50, 40))
        nodes = [dict(n) for n in PROB_NODES]
        nodes[2]['text'] = '아이싱(새 문구)'
        bridge2 = FakeBridge(changed, {'SceneNavigator': LOBBY_NODES, 'PopShopGachaProbability': nodes})
        out3 = os.path.join(qc.RUNS, 'unit-mac-3')
        c3 = self.runner(bridge2, SUITE, out3).run_case(SUITE['cases'][0])
        cp = c3['checkpoints'][0]
        self.assertEqual(cp['verdict'], 'REVIEW', cp)
        self.assertIn('CellShopGachaProbabilityList | 아이싱', cp['diff']['texts']['missing'])
        self.assertTrue(cp['diff']['image']['crops'])
        qc.save_json(os.path.join(out3, 'results.json'),
                     {'suite': 'unit', 'platform': 'mac', 'started': 's', 'cases': [c3], 'suiteFile': ''})
        req = judge.prepare(out3)
        text = open(req, encoding='utf-8').read()
        self.assertIn('TC-01 / prob', text)
        self.assertIn('expected', text)
        vf = os.path.join(self.tmp, 'v.json')
        with open(vf, 'w') as f:
            json.dump([{'case': 'TC-01', 'checkpoint': 'prob', 'verdict': 'DEFECT', 'category': 'wrong_text', 'reason': '문구 변경'}], f)
        self.assertEqual(judge.apply(out3, vf), 0)
        after = qc.load_json(os.path.join(out3, 'results.json'))
        self.assertEqual(after['cases'][0]['verdict'], 'FAIL')
        self.assertFalse(os.path.exists(req))
        rep = report.build([out, out3], os.path.join(self.tmp, 'rep'))
        md = open(os.path.join(rep, 'report.md'), encoding='utf-8').read()
        self.assertIn('wrong_text', md)
        csvtext = open(os.path.join(rep, 'results.csv'), encoding='utf-8-sig').read()
        self.assertIn('TC-01', csvtext)

    def test_flow_failure_is_error(self):
        out = os.path.join(qc.RUNS, 'unit-mac-err')
        bridge = FakeBridge(self.png, {'SceneNavigator': LOBBY_NODES})
        bridge.__class__ = type('B', (FakeBridge,), {})
        orig = bridge.__call__

        def call(*args):
            if args[0] == 'tap':
                return {'ok': False, 'error': 'node not found: _btnProbability'}
            return orig(*args)
        r = self.runner(call, SUITE, out)
        import case_runner
        with mock.patch.object(case_runner, 'FIND_WAIT', 0.3):   # 노드가 끝내 없으면 잠깐 다시 시도한 뒤 NAME_MISSING
            res = r.run_case(SUITE['cases'][0])
        self.assertEqual(res['verdict'], 'ERROR')
        self.assertEqual(res['error']['kind'], 'NAME_MISSING')

    def test_expect_fail_and_refuse_approve(self):
        out = os.path.join(qc.RUNS, 'unit-mac-fail')
        nodes = [dict(n) for n in PROB_NODES]
        nodes[0]['enabled'] = True
        bridge = FakeBridge(self.png, {'SceneNavigator': LOBBY_NODES, 'PopShopGachaProbability': nodes})
        res = self.runner(bridge, SUITE, out).run_case(SUITE['cases'][0])
        self.assertEqual(res['verdict'], 'FAIL')
        qc.save_json(os.path.join(out, 'results.json'), {'suite': 'unit', 'platform': 'mac', 'cases': [res]})
        self.assertEqual(answer_key.approve(out, None, None, 'tester', ''), 4)


class TestStateAndTime(Base):
    def test_validate_needs_server_and_time_ok(self):
        suite = {'cases': [{'id': 'A', 'auto': True, 'steps': [
            {'do': 'state', 'path': 'wallet.x.amt', 'value': 50}, {'do': 'server_time', 'to': '+1d'},
            {'do': 'checkpoint', 'name': 'n'}]}]}
        errs = '\n'.join(case_runner.validate(suite))
        self.assertIn('server(예: gb-qa-126)', errs)
        self.assertIn('time_ok', errs)
        suite.update(server='gb-qa-126', time_ok=True)
        self.assertEqual(case_runner.validate(suite), [])

    def test_server_time_case_not_run_without_flag(self):
        suite = {'suite': 'unit', 'server': 'gb-x', 'time_ok': True, 'cases': [
            {'id': 'T', 'auto': True, 'start': 'here', 'steps': [{'do': 'server_time', 'to': '+1d'}, {'do': 'checkpoint', 'name': 'n'}]}]}
        bridge = FakeBridge(self.png, {'SceneNavigator': LOBBY_NODES})
        res = self.runner(bridge, suite, os.path.join(qc.RUNS, 'u')).run_case(suite['cases'][0])
        self.assertEqual(res['verdict'], 'NOT_RUN')
        self.assertIn('--allow-time', res['reason'])

    def test_state_changes_and_restores(self):
        import states
        import routes
        calls = []
        store = {'wallet.x.amt': 900}
        saved = (states.get_field, states.set_field, routes.refresh_user_info)

        def get_field(env, mid, path, out):
            calls.append(('get', env, mid, path))
            return store[path]

        def set_field(env, mid, path, value, out, expect=None):
            assert store[path] == expect, (store[path], expect)
            calls.append(('set', path, value))
            store[path] = value
        states.get_field, states.set_field = get_field, set_field
        routes.refresh_user_info = lambda dev: calls.append(('refresh',))
        try:
            nodes = LOBBY_NODES + [{'name': 'labelMid', 'text': 'MID : ABC123\nbuild', 'rect': [0, 0, 10, 10]}]
            bridge = FakeBridge(self.png, {'SceneNavigator': nodes})
            suite = {'suite': 'unit', 'server': 'gb-x', 'cases': [
                {'id': 'S', 'auto': True, 'start': 'here', 'steps': [
                    {'do': 'state', 'path': 'wallet.x.amt', 'value': 50, 'restore': True},
                    {'do': 'checkpoint', 'name': 'n', 'settle': 0, 'expect': {'present': ['_btnShopGacha']}}]}]}
            res = self.runner(bridge, suite, os.path.join(qc.RUNS, 's')).run_case(suite['cases'][0])
            restored_value = store['wallet.x.amt']
            # 기본은 되돌리지 않는다 — 두 번째 실행은 이미 50 이면 저장하지 않는다
            del suite['cases'][0]['steps'][0]['restore']
            calls_before = len(calls)
            res2 = self.runner(bridge, suite, os.path.join(qc.RUNS, 's2')).run_case(suite['cases'][0])
            after_first = store['wallet.x.amt']
            res3 = self.runner(bridge, suite, os.path.join(qc.RUNS, 's3')).run_case(suite['cases'][0])
        finally:
            states.get_field, states.set_field, routes.refresh_user_info = saved
        self.assertEqual(res['verdict'], 'PASS', res)
        self.assertEqual(restored_value, 900)  # restore: true 면 되돌렸다
        self.assertEqual(res['state'][0], {'path': 'wallet.x.amt', 'from': 900, 'to': 50, 'mid': 'ABC123'})
        self.assertTrue(res['stateRestored'])
        self.assertEqual([c[0] for c in calls][:5], ['get', 'set', 'refresh', 'set', 'refresh'])
        self.assertEqual(after_first, 50)                      # 되돌리지 않았다
        self.assertNotIn('stateRestored', res2)
        self.assertTrue(res3['state'][0]['already'])          # 이미 50 이라 저장하지 않았다
        self.assertEqual([c[0] for c in calls[calls_before:]], ['get', 'set', 'refresh', 'get', 'refresh'])


class TestAutoplay(Base):
    """기본 기능 실행 — 인게임에 들어가면 자동 달리기(피하기·구멍 구출·이어달리기)로 끝까지 달린다"""

    def bridge(self, events, enabled=False):
        sent = []
        st = {'enabled': enabled, 'input': enabled, 'inGame': False, 'lastEvent': 3}
        queue = [list(events)]

        def call(*args):
            if args[0] == 'autorewind':
                f = json.loads(args[2])
                sent.append(f)
                if f['op'] == 'status':
                    return {'ok': True, 'result': dict(st)}
                if f['op'] == 'set':
                    st.update(enabled=True, input=True)
                    return {'ok': True, 'result': {}}
                if f['op'] == 'events':
                    batch = queue.pop(0) if queue else []
                    return {'ok': True, 'result': {'events': batch, 'next': f['since'] + len(batch)}}
                return {'ok': True, 'result': {}}
            return FakeBridge(self.png, {'SceneNavigator': LOBBY_NODES})(*args)
        return call, sent

    def suite(self, autoplay=True):
        s = {'suite': 'basic', 'cases': [{'id': 'TC-005', 'auto': True, 'start': 'here', 'steps': [
            {'do': 'play', 'timeout': 30}, {'do': 'checkpoint', 'name': 'result', 'settle': 0, 'image': False}]}]}
        if autoplay:
            s['autoplay'] = {'mode': 'smart', 'rescue': True, 'relay': True, 'mistakeRatio': 0}
        return s

    def test_validate_needs_autoplay(self):
        self.assertIn('autoplay', '\n'.join(case_runner.validate(self.suite(autoplay=False))))
        self.assertEqual(case_runner.validate(self.suite()), [])

    def test_basic_suite_carries_preset(self):
        import basic_scenario
        play = qc.load_json(os.path.join(qc.KIT, 'presets', 'basic-play.json'))['input']
        self.assertEqual(basic_scenario.build_suite([])['autoplay'], play)
        self.assertEqual((play['mode'], play['rescue'], play['relay']), ('smart', True, True))

    def test_play_runs_to_result(self):
        evs = [{'type': 'game_start', 't': 0}, {'type': 'rescue_click', 't': 20}, {'type': 'relay_click', 't': 40},
               {'type': 'rewind_skip', 'reason': 'online_sync', 't': 0}, {'type': 'game_over', 't': 61.24, 'jelly': '900'},
               {'type': 'result_screen', 'scene': 'SceneResult', 't': 61.3}]
        call, sent = self.bridge(evs)
        out = os.path.join(qc.RUNS, 'basic-play')
        with mock.patch.object(case_runner, 'PLAY_POLL', 0.01):
            res = self.runner(call, self.suite(), out).run_case(self.suite()['cases'][0])
        self.assertIsNone(res['error'])
        self.assertEqual(res['autoplay'], 'on')
        sets = [f for f in sent if f['op'] == 'set']
        self.assertEqual(len(sets), 1)   # 케이스 시작 때 한 번 켜고, play 단계는 켜진 것을 확인만 한다
        self.assertEqual((sets[0]['triggers'], sets[0]['infiniteRewind'], sets[0]['input']['mode']), ([], False, 'smart'))
        p = res['plays'][0]
        self.assertEqual((p['runners'], p['runs'][0]['end'], p['playSec'], p['rescue'], p['relay'], p['result'], p['skips']),
                         (1, 'game_over', 61.2, 1, 1, 'SceneResult', ['online_sync']))

    def test_relay_mode_waits_for_last_runner(self):
        # 릴레이 모드 — 주자마다 game_over 가 오고, 마지막 주자 뒤에 결과 화면이 나온다(2026-11-13 Android 실측 순서)
        batches = [[{'type': 'game_start', 't': 0}, {'type': 'crash', 't': 16}, {'type': 'game_over', 't': 42.3, 'jelly': '1695'}],
                   [], [{'type': 'game_start', 't': 0}, {'type': 'game_over', 't': 41.8, 'jelly': '411'}],
                   [{'type': 'game_start', 't': 0}, {'type': 'game_over', 't': 30.0, 'jelly': '850'},
                    {'type': 'result_screen', 'scene': 'SceneResultRelayTrainingMode', 't': 30.0}]]
        call, _ = self.bridge([])
        def relay(*args):
            if args[0] == 'autorewind' and json.loads(args[2])['op'] == 'events':
                f = json.loads(args[2])
                b = batches.pop(0) if batches else []
                return {'ok': True, 'result': {'events': b, 'next': f['since'] + len(b)}}
            return call(*args)
        with mock.patch.object(case_runner, 'PLAY_POLL', 0.01):
            res = self.runner(relay, self.suite(), os.path.join(qc.RUNS, 'basic-relay')).run_case(self.suite()['cases'][0])
        self.assertIsNone(res['error'])
        p = res['plays'][0]
        self.assertEqual((p['runners'], p['playSec'], p['crash'], p['result']), (3, 114.1, 1, 'SceneResultRelayTrainingMode'))
        self.assertFalse(p['stoppedByLimit'])

    def test_already_on_is_not_reset(self):
        call, sent = self.bridge([], enabled=True)
        suite = self.suite()
        suite['cases'][0]['steps'] = [{'do': 'checkpoint', 'name': 'x', 'settle': 0, 'image': False}]
        res = self.runner(call, suite, os.path.join(qc.RUNS, 'basic-on')).run_case(suite['cases'][0])
        self.assertEqual(res['autoplay'], 'on')
        self.assertFalse([f for f in sent if f['op'] == 'set'])

    def test_play_fails_when_game_never_starts(self):
        call, _ = self.bridge([])
        suite = self.suite()
        suite['cases'][0]['steps'][0]['start_timeout'] = 0.05
        with mock.patch.object(case_runner, 'PLAY_POLL', 0.01):
            res = self.runner(call, suite, os.path.join(qc.RUNS, 'basic-nostart')).run_case(suite['cases'][0])
        self.assertEqual((res['verdict'], res['error']['kind']), ('ERROR', 'NOT_REACHED'))


class TestSheetImport(unittest.TestCase):
    def test_convert(self):
        csv_text = ('QA 시트,,,,,,\n'
                    '번호,대분류,중분류,테스트 항목,테스트 방법,기대 결과,iOS 결과,Note\n'
                    '1,아이싱 뽑기,진입,탭 진입,로비 → 뽑기,화면이 나온다,PASS,\n'
                    '2,,,확률 정보,확률 정보 누름,팝업,,메모\n'
                    ',,,,,,,\n'
                    '3,옷장,,이동,옷장 누름,옷장 화면,,\n')
        s = sheet_import.convert(csv_text, 'unit', 'http://x')
        self.assertEqual(s['columns']['id'], '번호')
        self.assertNotIn('Note', s['columns'].values())
        self.assertEqual([c['id'] for c in s['cases']], ['TC-001', 'TC-002', 'TC-003'])
        self.assertEqual(s['cases'][1]['sheet']['area'], '아이싱 뽑기')
        self.assertEqual(s['cases'][1]['sheet']['extra'], {'Note': '메모'})
        self.assertEqual(s['cases'][0]['sheet_row'], 3)
        self.assertIsNone(s['cases'][0]['auto'])
        self.assertTrue(case_runner.validate(s))  # 아직 auto 가 비어 있어 오류가 난다

    def test_checklist_sheet_with_unnamed_area(self):
        # 실제 QA 기본기능 시트 형식: 대분류 열의 헤더가 비어 있고 병합 셀, 결과 칸(AOS·iOS)이 있다
        csv_text = (',점검 테스트,,,,,,,,,Android,,,iOS\n'
                    ',,,,,,,,,,Pass,0,,Pass,0\n'
                    ',No,,Sub1,중요도,CheckList,AOS,iOS,tester,comment\n'
                    ',1,실행,앱 아이콘,Critical,앱 아이콘이 출력된다.,N/T,N/T,,\n'
                    ',2,,앱 실행,Critical,앱 실행이 가능하다.,N/T,N/T,,\n'
                    ',3,,,Critical,최신 OS 에서 실행된다.,N/T,N/T,,\n')
        s = sheet_import.convert(csv_text, 'unit')
        self.assertEqual(s['columns'], {'id': 'No', 'sub': 'Sub1', 'priority': '중요도', 'title': 'CheckList', 'area': ''})
        self.assertEqual([c['sheet']['area'] for c in s['cases']], ['실행'] * 3)
        self.assertEqual(s['cases'][2]['sheet']['sub'], '앱 실행')
        self.assertEqual(s['cases'][0]['sheet']['priority'], 'Critical')

    def test_guess(self):
        self.assertEqual(sheet_import.guess('Android'), None)
        self.assertEqual(sheet_import.guess('No.'), 'id')
        self.assertEqual(sheet_import.guess('예상 결과'), 'expected')


class TestRewindRunner(unittest.TestCase):
    def case(self, **kw):
        c = {'id': 'RW-01', 'map': 'aaaa0001', 'plays': 2,
             'cards': {'cookie1': 100100, 'cookie2': 'random', 'pet': 'random', 'treasures': ['random', 0, 'random']},
             'triggers': [{'type': 'interval', 'delaySec': 10, 'count': 2}]}
        c.update(kw)
        return {'kind': 'rewind', 'cases': [c]}

    def test_validate_ok_and_errors(self):
        self.assertEqual(rewind_runner.validate(self.case()), [])
        self.assertTrue(rewind_runner.validate(self.case(triggers=[{'type': 'sometimes', 'count': 1}])))
        self.assertTrue(rewind_runner.validate(self.case(map='')))
        self.assertTrue(rewind_runner.validate(self.case(cards={'treasures': ['random']})))
        self.assertTrue(rewind_runner.validate(self.case(target='middle')))
        self.assertEqual(rewind_runner.validate(self.case(input={'mode': 'random', 'seed': 3, 'abilityEverySec': 8})), [])
        self.assertTrue(rewind_runner.validate(self.case(input={'mode': 'bogus'})))
        self.assertEqual(rewind_runner.validate(self.case(input={'mode': 'smart', 'mistakeRatio': 0.2})), [])
        self.assertTrue(rewind_runner.validate(self.case(input={'mode': 'smart', 'mistakeRatio': 2})))
        self.assertTrue(rewind_runner.validate(self.case(input={'slideRatio': 2})))
        self.assertTrue(rewind_runner.validate({'kind': 'basic', 'cases': []}))

    def test_stop_after_rewinds_is_validated_and_judged_pass(self):
        self.assertEqual(rewind_runner.validate(self.case(stopAfterSec=5)), [])
        self.assertEqual(rewind_runner.validate(self.case(stopAfterSec=None)), [])
        self.assertTrue(rewind_runner.validate(self.case(stopAfterSec=-1)))
        self.assertTrue(rewind_runner.validate(self.case(stopAfterSec='5')))
        ev = [{'type': 'rewind_request'}, {'type': 'rewind_done'}, {'type': 'rewind_request'}, {'type': 'rewind_done'}, {'type': 'timeout_stop'}]
        verdict, reason = rewind_runner.judge_play(ev, '', stop_after=5)
        self.assertEqual(verdict, 'PASS')
        self.assertIn('목표 횟수 뒤 5초까지 확인', reason)
        self.assertNotIn('목표 횟수', rewind_runner.judge_play(ev, '')[1])

    def test_resolve_cards_keeps_fixed_and_never_duplicates(self):
        import random
        pools = {'cookie': [100100, 100200, 100300], 'pet': [201800, 201900], 'treasure': [300100, 300200, 300300]}
        for seed in range(20):
            cards = rewind_runner.resolve_cards({'cookie1': 100100, 'cookie2': 'random', 'pet': 'random',
                                                 'treasures': ['random', 0, 'random']}, pools, random.Random(seed))
            self.assertEqual(cards['cookie1'], 100100)
            self.assertNotEqual(cards['cookie2'], 100100)
            self.assertEqual(cards['treasures'][1], 0)
            self.assertNotEqual(cards['treasures'][0], cards['treasures'][2])

    def test_judge_play(self):
        done = [{'seq': 1, 'type': 'rewind_request'}, {'seq': 2, 'type': 'rewind_done'}]
        self.assertEqual(rewind_runner.judge_play(done, '')[0], 'PASS')
        self.assertEqual(rewind_runner.judge_play(done + [{'seq': 3, 'type': 'state_mismatch', 't': 1.0, 'revive': '1/2'}], '')[0], 'FAIL')
        self.assertEqual(rewind_runner.judge_play(done + [{'seq': 3, 'type': 'rewind_fail', 't': 1.0, 'detail': 'desync'}], '')[0], 'FAIL')
        self.assertEqual(rewind_runner.judge_play(done, '앱 종료: signal 2')[0], 'ERROR')
        self.assertEqual(rewind_runner.judge_play([{'seq': 1, 'type': 'rewind_skip', 'reason': 'no_checkpoint'}], '')[0], 'UNSURE')

    def test_sample_suite_is_valid(self):
        path = os.path.join(os.path.dirname(HERE), 'cases', 'sample-rewind.json')
        self.assertEqual(rewind_runner.validate(qc.load_json(path)), [])


if __name__ == '__main__':
    unittest.main()


class FakeList:
    """세로 목록 40칸(칸 높이 50) 중 화면(높이 320)에 보이는 칸만 트리에 나오는 가짜 게임. offset 은 처음부터 내려온 길이."""

    def __init__(self, target_index, scroll=True):
        self.offset = 120.0      # 처음 위치가 목록 중간이어도 처음으로 돌아가 찾는다
        self.target = target_index
        self.scroll_ok = scroll
        self.calls = []

    def nodes(self):
        out = []
        for i in range(40):
            top = 320 - (i * 50 - self.offset)          # 화면 좌표(원점 왼쪽 아래)
            if 0 <= top - 50 and top <= 320:
                out.append({'owner': 'Cell', 'text': '보유하지 않음' if i == self.target else f'펫 {i}', 'rect': [10, top - 50, 100, 50]})
        return out

    def __call__(self, *args):
        cmd = args[0]
        self.calls.append(args)
        if cmd == 'ping':
            return {'ok': True, 'result': {'visibleSize': [568, 320]}}
        if cmd == 'tree':
            return {'ok': True, 'result': {'nodes': self.nodes()}}
        if cmd == 'scroll':
            if not self.scroll_ok:
                return {'ok': False, 'error': 'unknown cmd'}
            a = dict(zip(args[1::2], args[2::2]))
            if a.get('--to') == 'start':
                self.offset = 0.0
            elif '--pages' in a:
                self.offset += float(a['--pages']) * 320
            elif '--by' in a:
                self.offset += float(a['--by'])
            self.offset = max(0.0, min(self.offset, 40 * 50 - 320))
            return {'ok': True, 'result': {'atEnd': self.offset >= 40 * 50 - 320, 'atStart': self.offset == 0}}
        if cmd == 'swipe':
            self.offset = max(0.0, min(self.offset + 100, 40 * 50 - 320))
            return {'ok': True, 'result': {}}
        return {'ok': False, 'error': f'unknown {cmd}'}


class TestScrollFind(unittest.TestCase):
    STEP = {'do': 'scroll_find', 'select': {'owner': 'Cell', 'text': '보유하지 않음'}, 'band': ['15%', '70%'], 'max': 45}

    def run_find(self, bridge, step=None):
        import case_runner
        from flowlib import Device
        r = case_runner.Runner(Device('mac', tempfile.gettempdir(), tempfile.gettempdir(), runner=bridge), {'cases': []}, 'mac',
                               tempfile.gettempdir())
        with mock.patch.object(case_runner, 'SETTLE_POLL', 0):
            r.scroll_find(step or self.STEP, 'find')
        return r

    def test_bridge_scroll_finds_item_before_current_position_and_puts_it_in_band(self):
        bridge = FakeList(target_index=1)          # 처음 위치(120)보다 위에 있다 — 스와이프로는 못 찾던 경우
        self.run_find(bridge)
        hit = [n for n in bridge.nodes() if n['text'] == '보유하지 않음']
        self.assertTrue(hit)
        self.assertFalse(any(c[0] == 'swipe' for c in bridge.calls))

    def test_bridge_scroll_deep_item_without_swipes(self):
        bridge = FakeList(target_index=33)
        self.run_find(bridge)
        hit = [n for n in bridge.nodes() if n['text'] == '보유하지 않음']
        self.assertTrue(hit and 48 <= hit[0]['rect'][1] <= 224)
        self.assertLess(sum(c[0] == 'scroll' for c in bridge.calls), 12)

    def test_missing_item_fails_at_list_end_not_after_max_swipes(self):
        from flowlib import FlowFailure
        bridge = FakeList(target_index=99)
        with self.assertRaises(FlowFailure) as e:
            self.run_find(bridge)
        self.assertEqual(e.exception.kind, 'NOT_REACHED')
        self.assertLess(sum(c[0] == 'scroll' for c in bridge.calls), 10)

    def test_old_build_without_scroll_falls_back_to_swipe(self):
        bridge = FakeList(target_index=8, scroll=False)
        self.run_find(bridge)
        self.assertTrue(any(c[0] == 'swipe' for c in bridge.calls))
