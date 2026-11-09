import argparse
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_find  # noqa: E402

NODES = [
    {'id': 1, 'owner': 'Scene', 'type': 'cocos2d::Node'},
    {'id': 2, 'owner': 'Scene', 'inst': '_btnSort', 'receiver': 'button', 'rect': [1, 2, 3, 4]},
    {'id': 3, 'owner': 'Card', 'inst': '_btnSelect', 'receiver': 'button', 'rect': [0, 0, 1, 1]},
    {'id': 4, 'owner': 'Card', 'inst': '_btnSelect', 'receiver': 'button', 'rect': [5, 0, 1, 1]},
    {'id': 5, 'owner': 'Card', 'inst': '_labelName', 'text': '용감한 쿠키'},
    {'id': 6, 'owner': 'Scene', 'inst': '_btnOff', 'receiver': 'button', 'enabled': False},
]


def args(**kw):
    base = dict(owner=None, inst=None, text=None, type=None, tappable=False, buttons=False, texts=False, all=False)
    base.update(kw)
    return argparse.Namespace(**base)


class UiFindTest(unittest.TestCase):
    def test_summary_drops_noise_and_groups_repeats(self):
        out = ui_find.summary('Scene', NODES, 60)
        self.assertIn('_btnSelect · 버튼(눌림) · 0,0,1,1 · ×2', out)
        self.assertNotIn('[1]', out, '이름·글자·버튼이 없는 노드는 요약에 넣지 않는다')
        self.assertIn('버튼(꺼짐)', out)
        self.assertIn('「용감한 쿠키」', out)

    def test_filters(self):
        self.assertEqual([n['id'] for n in ui_find.pick(NODES, args(owner='Card', buttons=True))], [3, 4])
        self.assertEqual([n['id'] for n in ui_find.pick(NODES, args(text='쿠키'))], [5])
        self.assertEqual([n['id'] for n in ui_find.pick(NODES, args(tappable=True, owner='Scene'))], [2])
        self.assertEqual(len(ui_find.grouped(ui_find.pick(NODES, args(owner='Card')), each=True)), 3)


if __name__ == '__main__':
    unittest.main()
