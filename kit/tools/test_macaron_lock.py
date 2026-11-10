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
states.get_field('qa', 'mid', 'x', '/tmp')
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


if __name__ == '__main__':
    unittest.main()
