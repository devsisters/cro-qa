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

    def test_close_popup_returns_none_when_unknown(self):
        self.assertIsNone(device(FakeBridge(nodes=[])).close_popup('Pop'))


if __name__ == '__main__':
    unittest.main()
