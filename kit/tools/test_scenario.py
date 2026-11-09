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


class ConditionScoringTest(unittest.TestCase):
    def test_draft_expect_from_screen(self):
        nodes = [{'owner': 'PopInv', 'inst': '_btnClose', 'receiver': 'button'},
                 {'owner': 'PopInv', 'inst': '_labelTitle', 'text': '인벤토리'},
                 {'owner': 'Card', 'inst': '_labelName', 'text': '용감한 쿠키'},
                 {'owner': 'PopInv', 'inst': '_labelGold', 'text': '골드 100'}]
        exp = scenario_capture.draft_expect('PopInv', nodes, [{'owner': 'Card'}], ['골드=100'])
        self.assertEqual(exp['scene'], 'PopInv')
        self.assertEqual(exp['tappable'], [{'owner': 'PopInv', 'inst': '_btnClose'}])
        self.assertEqual(exp['present'], [{'owner': 'PopInv', 'inst': '_labelTitle', 'text': '인벤토리'}], 'mask 영역·숫자 글자는 조건에 넣지 않는다')
        self.assertEqual(exp['count'], [{'owner': 'Card', 'min': 1}])
        self.assertEqual(exp['text'], [{'select': {'owner': 'PopInv', 'inst': '_labelGold'}, 'contains': '100'}])

    def test_new_condition_needs_confirm_and_only_confirmed_is_scored(self):
        data = {'case': {'steps': [{'do': 'checkpoint', 'name': 'inv'}]}}
        scenario_capture.upsert_scoring(data, 'inv', 'aos', 'QA', expect={'scene': 'PopInv'}, when='t')
        steps = scenario_run.apply_scoring(data['case']['steps'], data['scoring'])
        self.assertNotIn('expect', steps[0], '확정 전 조건은 채점에 쓰지 않는다')
        self.assertTrue(steps[0]['scoring']['unconfirmed'])
        self.assertTrue(scenario_capture.confirm(data, 'inv', '담당자', when='t2'))
        steps = scenario_run.apply_scoring(data['case']['steps'], data['scoring'])
        self.assertEqual(steps[0]['expect'], {'scene': 'PopInv'})
        self.assertFalse(steps[0]['scoring']['unconfirmed'])
        scenario_capture.upsert_scoring(data, 'inv', 'ios', 'QA', expect={'scene': 'PopInv2'}, when='t3')
        self.assertFalse(data['scoring'][0]['confirmed'], '조건이 바뀌면 다시 확정 전')
        scenario_capture.upsert_scoring(data, 'inv', 'ios', 'QA', human='연출이 자연스러운지', when='t4')
        self.assertEqual(scenario_run.apply_scoring(data['case']['steps'], data['scoring'])[0]['scoring']['human'], '연출이 자연스러운지')

    def test_runner_marks_human_and_unconfirmed_points(self):
        import case_runner

        class Dev:
            out_dir = tempfile.mkdtemp()
            def tree(self): return {'nodes': [{'inst': '_btnClose', 'receiver': 'button', 'rect': [0, 0, 10, 10]}]}
            def scene(self): return 'PopInv'
            def call(self, *a): return {'result': {}}
            def shot(self, name): return None
        r = case_runner.Runner.__new__(case_runner.Runner)
        r.dev, r.platform, r.suite_name = Dev(), 'aos', 'scenario'
        case = {'id': 'k', 'answersDir': '/nonexistent'}
        cp = r.checkpoint(case, {'do': 'checkpoint', 'name': 'p', 'image': False, 'expect': {'scene': 'PopInv'},
                                 'scoring': {'compareImage': False, 'unconfirmed': False, 'human': ''}})
        self.assertEqual(cp['verdict'], 'PASS')
        cp = r.checkpoint(case, {'do': 'checkpoint', 'name': 'p', 'image': False,
                                 'scoring': {'compareImage': False, 'unconfirmed': False, 'human': '그림 확인'}})
        self.assertEqual((cp['verdict'], cp['human']), ('HUMAN', '그림 확인'))
        cp = r.checkpoint(case, {'do': 'checkpoint', 'name': 'p', 'image': False,
                                 'scoring': {'compareImage': False, 'unconfirmed': True, 'human': ''}})
        self.assertEqual(cp['verdict'], 'HUMAN')
        cp = r.checkpoint(case, {'do': 'checkpoint', 'name': 'p', 'image': False, 'expect': {'scene': 'Other'},
                                 'scoring': {'compareImage': False, 'unconfirmed': False, 'human': '그림 확인'}})
        self.assertEqual(cp['verdict'], 'FAIL', '조건이 틀리면 사람 확인보다 실패가 먼저다')


class ActionCaptureTest(unittest.TestCase):
    def run_case(self, steps, tap_ok=True):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'device_flows'))
        import case_runner
        import flowlib
        from unittest import mock
        calls = []

        def bridge(*args):
            calls.append(args)
            if args[0] == 'scene':
                return {'ok': True, 'result': {'top': 'SceneNavigator'}}
            if args[0] == 'tree':
                return {'ok': True, 'result': {'nodes': [{'inst': '_btnA', 'receiver': 'button', 'rect': [0, 0, 10, 10]}]}}
            if args[0] == 'tap':
                return {'ok': True, 'result': {}} if tap_ok else {'ok': False, 'error': 'node not found: _btnZ'}
            if args[0] == 'screenshot':
                open(args[1], 'wb').write(b'png')
                return {'ok': True}
            return {'ok': True, 'result': {}}
        out = tempfile.mkdtemp()
        dev = flowlib.Device('mac', '/tmp/checkout', out, runner=bridge)
        r = case_runner.Runner(dev, {'suite': 's', 'cases': []}, 'mac', out)
        r.capture_actions = True
        with mock.patch('case_runner.time.sleep', lambda s: None), mock.patch('flowlib.time.sleep', lambda s: None):
            return r.run_case({'id': 'k', 'auto': True, 'start': 'here', 'steps': steps})

    def test_each_action_is_captured_in_order_with_checkpoints(self):
        res = self.run_case([{'do': 'tap', 'target': '_btnA', 'label': 'A 누르기'}, {'do': 'sleep', 's': 0},
                             {'do': 'checkpoint', 'name': 'p', 'image': False}, {'do': 'back'}])
        self.assertEqual([(a['step'], a['label'], a['verdict']) for a in res['actions']], [(0, 'A 누르기', 'DONE'), (3, 'back', 'DONE')])
        self.assertTrue(all(a['shot'] for a in res['actions']))
        self.assertEqual(res['checkpoints'][0]['step'], 2)

    def test_failed_action_is_marked_with_failure_shot(self):
        res = self.run_case([{'do': 'tap', 'target': '_btnZ'}], tap_ok=False)
        self.assertEqual(res['verdict'], 'ERROR')
        self.assertEqual([(a['step'], a['verdict']) for a in res['actions']], [(0, 'FAILED')])
        self.assertIn('NAME_MISSING', res['actions'][0]['detail'])

    def test_report_lists_what_people_should_look_at(self):
        cases = [{'id': 'k', 'scenario': {'tab': 'T', 'no': '1'}, 'actions': [{'step': 0, 'label': 'A', 'verdict': 'DONE'}],
                  'checkpoints': [{'name': 'p1', 'step': 1, 'verdict': 'HUMAN', 'human': '연출 확인', 'checks': []},
                                  {'name': 'p2', 'step': 2, 'verdict': 'FAIL', 'checks': [{'check': '보임: X', 'ok': False}]},
                                  {'name': 'p3', 'step': 3, 'verdict': 'PASS', 'checks': []}]}]
        look = scenario_run.attention(cases)
        self.assertEqual([(x['what'], x['verdict'], x['why']) for x in look], [('p1', 'HUMAN', '연출 확인'), ('p2', 'FAIL', '보임: X')])
        self.assertEqual([x['label'] for x in scenario_run.timeline(cases[0])], ['A', 'p1', 'p2', 'p3'])


if __name__ == '__main__':
    unittest.main()
