"""마카롱 단계 잠금 — 두 기기 실행이 동시에 마카롱 탭을 쓰지 않고 차례로 쓴다"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

CHILD = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
import states
states.LOCK_FILE = sys.argv[2]
def fake_open(env, mid):
    time.sleep(0.6)          # 탭을 열고 문서를 받는 시간
    return 't'
states._open = fake_open
states._run = lambda cmd: (0, {'ok': True, 'value': 1})
t0 = time.time()
states.set_field('qa', 'mid', 'x', 1, '/tmp')   # 편집기로 저장하는 단계만 잠금을 잡는다(읽기는 조회 API 라 잠그지 않는다)
print(json.dumps({'start': t0, 'end': time.time()}))
'''


class MacaronLockTest(unittest.TestCase):
    def test_two_runs_take_turns(self):
        with tempfile.TemporaryDirectory() as d:
            lock = os.path.join(d, 'macaron.lock')
            args = [sys.executable, '-c', CHILD, os.path.join(HERE, 'device_flows'), lock]
            procs = [subprocess.Popen(args, stdout=subprocess.PIPE, text=True) for _ in range(2)]
            outs = [p.communicate(timeout=30)[0] for p in procs]
            spans = [json.loads(o.strip().splitlines()[-1]) for o in outs]
            first, second = sorted(spans, key=lambda s: s['end'])
            self.assertGreaterEqual(second['end'] - first['end'], 0.55, '두 번째 실행은 첫 번째가 탭을 닫은 뒤에 탭을 연다')
            self.assertTrue(any('기다린다' in o for o in outs), '기다리는 쪽은 그 사실을 로그에 남긴다')


class PeekFirstTest(unittest.TestCase):
    def test_remove_already_missing_does_not_open_editor(self):
        sys.path.insert(0, os.path.join(HERE, 'device_flows'))
        import states
        calls = []

        def fake_run(cmd):
            calls.append(cmd)
            if cmd[:3] == ['node', states.ASIDE, 'open']:
                return 0, {'targetId': 'T'}
            if 'peek' in cmd:
                return 0, {'ok': True, 'exists': False}
            return 0, {'ok': True}
        orig = states._run, states._open
        states._run = fake_run
        states._open = lambda env, mid: self.fail('이미 없는 항목인데 편집기 탭을 열었다')
        try:
            info = states.remove_item('gb-qa-1', 'MID', 'inventory.pets.@id=1', '/tmp')
        finally:
            states._run, states._open = orig
        self.assertTrue(info['already'])
        self.assertTrue(any('peek' in c for c in calls))
        self.assertIn('https://macaron.gb-qa-1.stove.devspie.com/couchbase_modifier/', [c[3] for c in calls if c[:3] == ['node', states.ASIDE, 'open']])


if __name__ == '__main__':
    unittest.main()
