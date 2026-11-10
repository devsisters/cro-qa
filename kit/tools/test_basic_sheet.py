"""기본 기능 시트 도구 — TC 탭 읽기, 실행 결과 → 결과 탭 칸, 사람이 적은 칸 보호"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import basic_scenario  # noqa: E402
import basic_sheet  # noqa: E402
import scenario_run  # noqa: E402


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def make_run(d, name, platform, cases, version='14.50'):
    out = os.path.join(d, name)
    write(os.path.join(out, 'results.json'), {'cases': cases})
    write(os.path.join(out, 'basic.json'), {'version': version, 'platform': platform, 'at': '2026-11-10T15:20:00', 'by': '담당자'})
    return out


PASS = {'id': 'TC-028', 'verdict': 'PASS', 'checkpoints': [{'name': 'tabs', 'verdict': 'PASS', 'checks': [{'check': 'a', 'ok': True}, {'check': 'b', 'ok': True}]}]}
FAIL = {'id': 'TC-029', 'verdict': 'FAIL', 'checkpoints': [{'name': 'pet', 'verdict': 'FAIL', 'checks': [{'check': '보임: 보유하지 않음', 'ok': False, 'detail': '없음'}]}]}
ERR = {'id': 'TC-030', 'verdict': 'ERROR', 'error': {'kind': 'flow', 'step': 2, 'detail': '_btnMyCookie 없음'}}


class TcTabTest(unittest.TestCase):
    def test_reads_rows_by_header_name(self):
        rows = {1: {0: 'ID', 1: '대분류', 2: '중분류', 3: '중요도', 4: '확인 내용', 5: '판정 항목', 6: '자동화 구분', 7: '사전 조건', 8: '비고'},
                2: {0: 'TC-001', 1: '실행', 2: '앱', 3: 'Critical', 4: '앱 실행', 5: '로비까지 간다', 6: '화면'},
                3: {0: '', 4: '빈 줄'},
                4: {0: 'TC-002', 1: '실행', 6: '수동', 8: '메모'}}
        tcs = basic_sheet.parse_tc_rows(rows)
        self.assertEqual([t['id'] for t in tcs], ['TC-001', 'TC-002'])
        self.assertEqual((tcs[0]['judge'], tcs[0]['class'], tcs[1]['note']), ('로비까지 간다', '화면', '메모'))


class ResultCellsTest(unittest.TestCase):
    def test_status_and_reason(self):
        with tempfile.TemporaryDirectory() as d:
            run = make_run(d, 'basic-14.50-aos-20261110-152000', 'aos', [PASS, FAIL, ERR])
            platform, rows = basic_sheet.result_rows(run)
            self.assertEqual(platform, 'aos')
            self.assertEqual([rows[k][0] for k in ('TC-028', 'TC-029', 'TC-030')], ['Pass', 'Fail', 'Block'])
            self.assertIn('조건 2개 통과', rows['TC-028'][1])
            self.assertIn('✗ 보임: 보유하지 않음 (없음)', rows['TC-029'][1])
            self.assertIn('진행 실패', rows['TC-030'][1])
            self.assertTrue(rows['TC-028'][2].startswith('2026-11-10 15:20 · 담당자 · '))

    def test_plan_writes_platform_cells_merges_rows_and_keeps_human_results(self):
        with tempfile.TemporaryDirectory() as d:
            run = make_run(d, 'basic-14.50-ios-20261110-152000', 'ios', [PASS, FAIL, ERR])
            _, rows = basic_sheet.result_rows(run)
            ids = [['ID'], ['TC-027'], ['TC-028'], ['TC-029'], ['TC-030']]
            # G:L — TC-030 의 iOS 칸은 사람이 Fail 로 적었다(실행 칸 비어 있음)
            cols = [['AOS', 'AOS 근거', 'AOS 실행', 'iOS', 'iOS 근거', 'iOS 실행'], ['N/T'], ['N/T', '', '', 'N/T'],
                    ['Pass', 'x', '자동', 'Pass', 'y', '2026-11-09 · 자동'], ['N/T', '', '', 'Fail', '', '']]
            plan = basic_sheet.plan_update('14.50', [('ios', rows)], ids, cols)
            self.assertEqual([u['range'] for u in plan['updates']], ["'14.50'!J3:L4"])
            self.assertEqual(plan['updates'][0]['values'][0][0], 'Pass')
            self.assertEqual(plan['updates'][0]['values'][1][0], 'Fail', '자동 결과는 덮어쓴다')
            self.assertEqual([(x['id'], x['platform']) for x in plan['skipped']], [('TC-030', 'ios')])

    def test_device_lines_merge_with_earlier_run_instead_of_overwriting(self):
        """TC-003 처럼 줄마다 조건 기기가 다른 TC — 다른 기기에서 먼저 쓴 줄 결과를 살려 합친다"""
        low_dev, new_dev = '조건 기기에서 실행 — SM-S921B · OS 14', '조건 기기에서 실행 — SM-S938N · OS 16'
        first = {'id': 'TC-003', 'verdict': 'UNSURE', 'deviceChecked': [{'name': '최저사양', 'device': low_dev}], 'checkpoints': [
            {'name': '최저사양', 'verdict': 'PASS', 'checks': [{'check': 'a', 'ok': True}]},
            {'name': '최신 OS', 'verdict': 'NOT_RUN', 'device': '조건 OS(>=16)가 아니다 — 실행 기기 SM-S921B · OS 14', 'checks': []}]}
        second = {'id': 'TC-003', 'verdict': 'UNSURE', 'deviceChecked': [{'name': '최신 OS', 'device': new_dev}], 'checkpoints': [
            {'name': '최저사양', 'verdict': 'NOT_RUN', 'device': '조건 기기(SM-S921B)가 아니다 — 실행 기기 SM-S938N · OS 16', 'checks': []},
            {'name': '최신 OS', 'verdict': 'PASS', 'checks': [{'check': 'a', 'ok': True}]}]}
        with tempfile.TemporaryDirectory() as d:
            _, r1 = basic_sheet.result_rows(make_run(d, 'basic-14.50-aos-20261110-150000', 'aos', [first]))
            self.assertEqual(r1['TC-003'][0], 'Check')
            # 첫 실행 결과가 시트에 있는 상태에서 두 번째 기기 결과를 쓴다
            cols = [['AOS', 'AOS 근거', 'AOS 실행'], r1['TC-003']]
            _, r2 = basic_sheet.result_rows(make_run(d, 'basic-14.50-aos-20261110-160000', 'aos', [second]))
            plan = basic_sheet.plan_update('14.50', [('aos', r2)], [['ID'], ['TC-003']], cols)
            status, reason, stamp = plan['updates'][0]['values'][0]
            self.assertEqual(status, 'Pass', '두 줄 모두 조건 기기에서 통과')
            self.assertIn(low_dev, reason)
            self.assertIn(new_dev, reason)
            self.assertNotIn('확인 안 함', reason)
            self.assertIn('앞 실행에서 가져온 줄', stamp)
            # 실패 줄이 있으면 Fail, partial 이 있으면 Check
            r2['TC-003'].partial = '다른 줄'
            plan = basic_sheet.plan_update('14.50', [('aos', r2)], [['ID'], ['TC-003']], cols)
            self.assertEqual(plan['updates'][0]['values'][0][0], 'Check')
            # 사람이 적은 칸(실행 칸 비어 있음)은 여전히 건드리지 않는다
            plan = basic_sheet.plan_update('14.50', [('aos', r2)], [['ID'], ['TC-003']], [['AOS'], ['Fail', '', '']])
            self.assertEqual(len(plan['skipped']), 1)

    def test_missing_row_is_appended_with_tc_columns(self):
        with tempfile.TemporaryDirectory() as d:
            run = make_run(d, 'basic-14.50-aos-20261110-152000', 'aos', [PASS])
            _, rows = basic_sheet.result_rows(run)
            tcs = {'TC-028': {'area': '쿠키 인벤토리', 'sub': '분류', 'priority': 'Critical', 'check': '탭', 'class': '화면'}}
            plan = basic_sheet.plan_update('14.50', [('aos', rows)], [['ID'], ['TC-001']], [['AOS']], tcs)
            self.assertEqual(plan['appended'], ['TC-028'])
            self.assertEqual(plan['updates'][0]['range'], "'14.50'!A3:I3")
            self.assertEqual(plan['updates'][0]['values'][0][:6], ['TC-028', '쿠키 인벤토리', '분류', 'Critical', '탭', '화면'])
            self.assertEqual(plan['updates'][0]['values'][0][6], 'Pass')

    def test_create_payload_shape(self):
        tcs = [{'id': 'TC-001', 'area': 'a', 'sub': 'b', 'priority': 'Major', 'check': 'c', 'class': '화면'}]
        p = basic_sheet.create_payload('14.50', 123, tcs)
        self.assertEqual(p['values']['range'], "'14.50'!A1:M2")
        self.assertEqual(p['values']['values'][0], basic_sheet.RESULT_HEADER)
        self.assertEqual(p['values']['values'][1][6], 'N/T')
        self.assertTrue(p['summary']['values'][1][1].startswith('=COUNTIF($G$2:$G'))
        self.assertTrue(all(r.get(next(iter(r)), {}) for r in p['requests']))

    def test_quote_tab_with_apostrophe(self):
        self.assertEqual(basic_sheet.quote_tab("14.50 '재"), "'14.50 ''재'")


class BasicReportTest(unittest.TestCase):
    def test_report_marks_kind_basic_and_tc_info(self):
        with tempfile.TemporaryDirectory() as d:
            out = make_run(d, 'basic-14.50-aos-20261110-152000', 'aos', [PASS])
            info = {'TC-028': {'tab': '기본 기능', 'no': 'TC-028', 'path': '쿠키 인벤토리 › 분류', 'expected': '탭', 'labels': {}}}
            scenario_run.write_tc_report(out, 'aos', info, 'basic', '기본 기능 14.50')
            with open(os.path.join(out, 'results.json'), encoding='utf-8') as f:
                res = json.load(f)
            self.assertEqual(res['kind'], 'basic')
            self.assertEqual(res['cases'][0]['scenario']['no'], 'TC-028')
            with open(os.path.join(out, 'report.md'), encoding='utf-8') as f:
                md = f.read()
            self.assertTrue(md.startswith('# 기본 기능 14.50 [AOS]'))
            self.assertNotIn('시나리오: `scenarios/', md)


class ScenarioTest(unittest.TestCase):
    TCS = [{'id': 'TC-001', 'area': '실행', 'sub': '앱'}, {'id': 'TC-002', 'area': '실행', 'sub': '실행'},
           {'id': 'TC-072', 'area': '모드리스트', 'sub': '떼탈출'}, {'id': 'TC-088', 'area': '모드리스트', 'sub': '쿠키의 도전'},
           {'id': 'TC-073', 'area': '모드리스트', 'sub': '떼탈출'}]

    def test_groups_by_area_and_split_only_listed_area_by_sub(self):
        g = basic_scenario.groups(self.TCS, {'모드리스트'})
        self.assertEqual([(a, s, [t['id'] for t in ts]) for a, s, ts in g],
                         [('실행', '', ['TC-001', 'TC-002']), ('모드리스트', '떼탈출', ['TC-072', 'TC-073']), ('모드리스트', '쿠키의 도전', ['TC-088'])])
        self.assertTrue(basic_scenario.scenario_path('실행', '', '/r').endswith('/r/실행.json'))
        self.assertTrue(basic_scenario.scenario_path('모드리스트', '특별 이벤트/A', '/r').endswith('/r/모드리스트/특별 이벤트_A.json'))

    def test_segments_continue_on_screen_and_resume_after_failure(self):
        setup = [{'do': 'state', 'path': 'x', 'value': 1}]
        entry = [{'do': 'tap', 'target': '_btnA'}]
        data = {'area': '쿠키', 'start': 'lobby', 'setup': setup, 'entry': entry, 'segments': [
            {'tc': 'TC-1', 'steps': []},                                   # 비어 있음 — 돌리지 않음
            {'tc': 'TC-2', 'steps': [{'do': 'checkpoint', 'name': 'a'}]},   # 첫 구간 — 진입부터
            {'tc': 'TC-3', 'steps': [{'do': 'checkpoint', 'name': 'b'}]},   # 이어서
            {'tc': 'TC-4', 'steps': [{'do': 'checkpoint', 'name': 'c'}], 'fresh': True}]}
        c = {x['id']: x for x in basic_scenario.build_cases(data, '/r/쿠키.json')}
        self.assertEqual((c['TC-1']['auto'], c['TC-1']['reason']), (False, '아직 자동화 단계가 없다'))
        self.assertEqual(c['TC-2']['start'], 'lobby')
        self.assertEqual([s['do'] for s in c['TC-2']['steps']], ['state', 'tap', 'checkpoint'])
        self.assertEqual(c['TC-3']['start'], 'here')
        self.assertEqual([s['do'] for s in c['TC-3']['steps']], ['checkpoint'])
        self.assertEqual(c['TC-3']['resume'], {'start': 'lobby', 'steps': setup + entry})
        self.assertEqual((c['TC-4']['start'], len(c['TC-4']['steps'])), ('lobby', 3))
        self.assertEqual(c['TC-2']['answersDir'], '/r/쿠키')

    def test_check_flags_tc_from_other_group(self):
        by = {t['id']: t for t in self.TCS}
        errs = basic_scenario.check({'area': '모드리스트', 'sub': '떼탈출', 'segments': [{'tc': 'TC-072'}, {'tc': 'TC-088'}]}, 'x.json', by)
        self.assertEqual(len(errs), 1)
        self.assertIn('TC-088', errs[0])
        self.assertEqual(basic_scenario.check({'area': '실행', 'sub': '', 'segments': [{'tc': 'TC-001'}, {'tc': 'TC-002'}]}, 'x.json', by), [])

    def test_built_suite_passes_case_runner_validation(self):
        import case_runner
        data = {'area': '쿠키', 'start': 'lobby', 'entry': [{'do': 'tap', 'target': '_b'}], 'segments': [
            {'tc': 'TC-1', 'steps': [{'do': 'checkpoint', 'name': 'a'}]}, {'tc': 'TC-2', 'steps': [{'do': 'checkpoint', 'name': 'b'}]},
            {'tc': 'TC-3', 'steps': []}]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'x.json')
            write(path, data)
            self.assertEqual(case_runner.validate(basic_scenario.build_suite([path], [])), [])

    def test_not_run_cases_leave_sheet_cells_alone(self):
        with tempfile.TemporaryDirectory() as d:
            run = make_run(d, 'basic-14.50-aos-20261110-152000', 'aos', [PASS, {'id': 'TC-035', 'verdict': 'NOT_RUN', 'reason': '다른 계정'}])
            _, rows = basic_sheet.result_rows(run)
            self.assertEqual(sorted(rows), ['TC-028'])


if __name__ == '__main__':
    unittest.main()
