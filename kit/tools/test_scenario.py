import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario_capture  # noqa: E402
import scenario_run  # noqa: E402


class ScenarioTest(unittest.TestCase):
    def test_upsert_scoring_keeps_one_entry_per_point(self):
        data = {'case': {'steps': [{'do': 'checkpoint', 'name': 'episode'}]}}
        self.assertTrue(scenario_capture.upsert_scoring(data, 'episode', 'aos', 'QA', '에피소드 화면', ['골드=100'], when='t1'))
        self.assertFalse(scenario_capture.upsert_scoring(data, 'result', 'aos', 'QA', when='t1'), 'checkpoint 단계가 없으면 알린다')
        scenario_capture.upsert_scoring(data, 'episode', 'ios', 'QA2', None, ['골드=120', '별=3'], when='t2')
        self.assertEqual([p['name'] for p in data['scoring']], ['episode', 'result'])
        ep = data['scoring'][0]
        self.assertEqual(ep['label'], '에피소드 화면', '설명을 안 주면 그대로 둔다')
        self.assertEqual(ep['values'], [{'label': '골드', 'value': '120'}, {'label': '별', 'value': '3'}])
        self.assertEqual(set(ep['platforms']), {'aos', 'ios'})

    def test_suite_points_answers_to_scenario_folder_and_records_last_run(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'tab', 'abc123.json')
            os.makedirs(os.path.dirname(path))
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'key': 'abc123', 'tab': 'tab', 'no': '3', 'tc': {'main': 'A', 'expected': 'E'},
                           'case': {'start': 'lobby', 'steps': [{'do': 'checkpoint', 'name': 'p1'}]}}, f)
            suite = scenario_run.build_suite([path])
            case = suite['cases'][0]
            self.assertEqual(case['id'], 'abc123')
            self.assertEqual(case['answersDir'], os.path.join(d, 'tab', 'abc123'))
            out = os.path.join(d, 'run')
            os.makedirs(out)
            with open(os.path.join(out, 'results.json'), 'w', encoding='utf-8') as f:
                json.dump({'cases': [{'id': 'abc123', 'verdict': 'PASS', 'checkpoints': [{'name': 'p1', 'verdict': 'PASS', 'shot': None}]}]}, f)
            scenario_run.record_last_run([path], 'aos', out)
            last = json.load(open(path, encoding='utf-8'))['lastRun']
            self.assertEqual((last['verdict'], last['platform'], last['checkpoints']['p1']['verdict']), ('PASS', 'aos', 'PASS'))


if __name__ == '__main__':
    unittest.main()
