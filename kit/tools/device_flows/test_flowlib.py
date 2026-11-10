import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flowlib  # noqa: E402
from flowlib import Device, FlowFailure  # noqa: E402


class FakeBridge:
    def __init__(self, nodes=None, scene='SceneNavigator', tap=None):
        self.nodes = nodes or []
        self.scene = scene
        self.tap_result = tap or {'ok': True, 'result': {'x': 1, 'y': 2}}
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == 'scene':
            return {'ok': True, 'result': {'top': self.scene}}
        if args[0] == 'tree':
            return {'ok': True, 'result': {'nodes': self.nodes}}
        if args[0] == 'tap':
            return self.tap_result
        return {'ok': True, 'result': {}}


def device(bridge):
    return Device('mac', '/tmp/checkout', '/tmp/out', runner=bridge)


class FlowlibTest(unittest.TestCase):
    def test_tap_blocked_is_classified(self):
        dev = device(FakeBridge(tap={'ok': False, 'error': 'blocked by PopNotice/x'}))
        with self.assertRaises(FlowFailure) as cm:
            dev.tap('_btnShopGacha')
        self.assertEqual(cm.exception.kind, 'BLOCKED')

    def test_tap_missing_name_is_classified_with_scene(self):
        dev = device(FakeBridge(tap={'ok': False, 'error': 'node not found'}, scene='SceneShopGacha'))
        with self.assertRaises(FlowFailure) as cm:
            dev.tap('_btnGone')
        self.assertEqual(cm.exception.kind, 'NAME_MISSING')
        self.assertIn('SceneShopGacha', cm.exception.detail)

    def test_tap_other_error_is_bridge(self):
        dev = device(FakeBridge(tap={'ok': False, 'error': 'bridge unavailable'}))
        with self.assertRaises(FlowFailure) as cm:
            dev.tap('x')
        self.assertEqual(cm.exception.kind, 'BRIDGE')

    def test_wait_times_out_as_not_reached(self):
        dev = device(FakeBridge())
        with mock.patch.object(flowlib.time, 'sleep'):
            with self.assertRaises(FlowFailure) as cm:
                dev.wait(lambda: False, 0.01, 'step', 'thing')
        self.assertEqual(cm.exception.kind, 'NOT_REACHED')

    def test_nodes_drop_clipped_and_offscreen(self):
        dev = device(FakeBridge(nodes=[{'id': 1}, {'id': 2, 'clipped': True}, {'id': 3, 'offscreen': True},
                                       {'id': 4, 'clipped': 'partial'}]))
        self.assertEqual([n['id'] for n in dev.nodes()], [1, 4])

    def test_close_popup_prefers_named_close_button(self):
        nodes = [
            {'owner': 'Pop', 'inst': '_btnClose', 'receiver': 'button', 'rect': [10, 10, 20, 20]},
            {'owner': 'Pop', 'receiver': 'button', 'rect': [500, 300, 20, 20]},
        ]
        bridge = FakeBridge(nodes=nodes)
        device(bridge).close_popup('Pop')
        taps = [c for c in bridge.calls if c[0] == 'tap']
        self.assertEqual(taps[-1][1:5], ('--x', '20.0', '--y', '20.0'))

    def test_close_popup_falls_back_to_top_right_small_button(self):
        nodes = [
            {'owner': 'Pop', 'receiver': 'button', 'rect': [10, 10, 20, 20]},
            {'owner': 'Pop', 'receiver': 'button', 'rect': [500, 300, 20, 20]},
            {'owner': 'Other', 'receiver': 'button', 'rect': [600, 310, 20, 20]},
        ]
        bridge = FakeBridge(nodes=nodes)
        device(bridge).close_popup('Pop')
        taps = [c for c in bridge.calls if c[0] == 'tap']
        self.assertEqual(taps[-1][1:5], ('--x', '510.0', '--y', '310.0'))

    def test_close_popup_taps_screen_center_when_only_touch_text(self):
        bridge = FakeBridge(nodes=[{'owner': 'PopUpdateHighlight', 'text': 'Touch!'}])
        device(bridge).close_popup('PopUpdateHighlight')
        taps = [c for c in bridge.calls if c[0] == 'tap']
        self.assertEqual(taps[-1][1:5], ('--x', '284.0', '--y', '160.0'))

    def test_close_popup_ignores_touch_text_of_other_owner(self):
        self.assertIsNone(device(FakeBridge(nodes=[{'owner': 'Other', 'text': 'Touch!'}])).close_popup('Pop'))

    def test_close_popup_returns_none_when_unknown(self):
        self.assertIsNone(device(FakeBridge(nodes=[])).close_popup('Pop'))


if __name__ == '__main__':
    unittest.main()


class PresetAndTitleTest(unittest.TestCase):
    """서버 선택 창 프리셋 고르기 · 제목 화면 영상 — 실제 기기의 트리 모양(2026-11-09 Android 실측)으로 흉내 낸다."""

    def setUp(self):
        import routes
        self.routes = routes
        self.sleep = mock.patch('routes.time.sleep', lambda s: None)
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def preset_nodes(self, offset, chosen):
        area = {'id': 45, 'inst': '_gNodePresetList', 'rect': [117.0, 17.5, 228.0, 230.0]}
        names = [f'p{i}' for i in range(30)]
        items = [{'id': 100 + i, 'name': 'preset', 'text': n, 'opacity': 255 if n == chosen else 100,
                  'rect': [117.0, 215.5 - 32 * i + offset, 228.0, 32.0]} for i, n in enumerate(names)]
        return [area] + items

    def test_select_preset_scrolls_until_visible_then_taps_and_confirms(self):
        state = {'offset': 0.0, 'chosen': 'p0'}

        class Bridge(FakeBridge):
            def __call__(self, *args):
                self.calls.append(args)
                if args[0] == 'tree':
                    return {'ok': True, 'result': {'nodes': test.preset_nodes(state['offset'], state['chosen'])}}
                if args[0] == 'swipe':
                    state['offset'] += float(args[args.index('--y2') + 1]) - float(args[args.index('--y1') + 1])
                if args[0] == 'tap':
                    y = float(args[args.index('--y') + 1])
                    i = round((215.5 + 16 + state['offset'] - y) / 32)
                    state['chosen'] = f'p{i}'
                return {'ok': True, 'result': {}}
        test = self
        bridge = Bridge()
        self.routes.select_preset(device(bridge), 'p25')
        self.assertEqual(state['chosen'], 'p25')
        self.assertTrue(any(c[0] == 'swipe' for c in bridge.calls))

    def test_select_preset_missing_name_fails_clearly(self):
        bridge = FakeBridge(nodes=self.preset_nodes(0, 'p0'))
        with mock.patch('routes.time.time', side_effect=[0, 0] + [100] * 10):
            with self.assertRaises(FlowFailure) as e:
                self.routes.select_preset(device(bridge), 'nope', timeout=1)
        self.assertEqual(e.exception.kind, 'NAME_MISSING')

    def test_title_movie_turns_dont_show_again_on_and_skips_video(self):
        bridge = FakeBridge(scene='Title', nodes=[{'inst': '_btnDontShowAgain', 'rect': [10, 10, 40, 20]},
                                                 {'type': 'cocos2d::experimental::ui::VideoPlayer', 'rect': [0, 0, 568, 320]}])
        self.routes.skip_title_movie(device(bridge))
        taps = [c for c in bridge.calls if c[0] == 'tap']
        self.assertEqual(taps[0][1:3], ('--node', '_btnDontShowAgain'))
        self.assertEqual(len(taps), 2)

    def test_title_movie_leaves_checked_box_alone(self):
        bridge = FakeBridge(scene='Title', nodes=[{'inst': '_btnDontShowAgain', 'rect': [10, 10, 40, 20]},
                                                 {'inst': '_spriteDontShowAgainCheck', 'rect': [10, 10, 20, 20]}])
        self.routes.skip_title_movie(device(bridge))
        self.assertFalse([c for c in bridge.calls if c[0] == 'tap'])
