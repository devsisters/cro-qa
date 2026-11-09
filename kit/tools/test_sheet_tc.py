import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_tc  # noqa: E402

M = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def cell(ref, text):
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def sheet(rows):
    body = ''.join(f'<row r="{r}">' + ''.join(cell(f'{c}{r}', v) for c, v in cells.items()) + '</row>' for r, cells in rows.items())
    return f'<worksheet xmlns="{M}"><sheetData>{body}</sheetData></worksheet>'


def book(path, tabs):
    with zipfile.ZipFile(path, 'w') as z:
        sheets = ''.join(f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"{" state=\"hidden\"" if h else ""}/>' for i, (n, h, _) in enumerate(tabs))
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{M}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{sheets}</sheets></workbook>')
        rels = ''.join(f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(tabs)))
        z.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for i, (_, _, rows) in enumerate(tabs):
            z.writestr(f'xl/worksheets/sheet{i + 1}.xml', sheet(rows))


class SheetTcTest(unittest.TestCase):
    def test_reads_qa_format(self):
        tc_tab = {
            2: {'D': '떼탈출'},
            9: {'B': 'No', 'C': 'Priority', 'D': 'Main', 'E': 'Sub-1', 'F': 'Sub-2', 'G': 'Sub-3', 'H': 'Expectation Result', 'I': 'AOS', 'J': 'iOS', 'N': 'Comment'},
            10: {'D': '1. 진입'},
            11: {'B': '2', 'C': 'Critical', 'D': '입장하기', 'E': '모드리스트', 'F': '출력', 'H': '버튼이 출력된다.', 'I': 'N/T', 'J': 'Pass'},
            12: {'B': '3', 'C': 'Normal', 'F': '해금조건', 'G': '_x0008_미달성', 'H': '자물쇠가 출력된다.', 'I': 'Fail', 'J': 'N/T', 'N': '메모'},
            13: {'D': '2. 화면'},
            14: {'B': '4', 'C': 'Normal', 'D': '상단', 'H': '타이틀이 나온다.'},
        }
        other = {9: {'B': 'No', 'C': 'Priority', 'D': 'Main', 'E': 'Sub1', 'H': 'Expectation Result', 'I': 'Android', 'J': 'iOS', 'K': 'Comment'},
                 10: {'B': '1', 'D': '뽑기', 'E': '진입', 'H': '화면이 전환된다.', 'I': 'Block', 'K': '코멘트'}}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'CRO Test Case.xlsx')
            book(path, [('Overview', False, {1: {'A': '요약'}}), ('떼탈출', False, tc_tab), ('뽑기상점', False, other), ('숨김', True, tc_tab)])
            tabs, skipped = sheet_tc.read_book(path)
        self.assertEqual(skipped, ['Overview'])
        self.assertEqual([t['name'] for t in tabs], ['떼탈출', '뽑기상점'], '숨김 탭은 기본으로 뺀다')
        a, b, c = tabs[0]['tcs']
        self.assertEqual((a['section'], a['main'], a['sub1'], a['sub2'], a['ios']), ('1. 진입', '입장하기', '모드리스트', '출력', 'Pass'))
        self.assertEqual((b['main'], b['sub1'], b['sub2'], b['sub3']), ('입장하기', '모드리스트', '해금조건', '미달성'), '병합 칸은 위 값을 잇고 제어 문자는 버린다')
        self.assertEqual(b['comment'], '메모')
        self.assertEqual((c['section'], c['main'], c['sub1']), ('2. 화면', '상단', ''), '구간이 바뀌면 분류를 새로 시작한다')
        self.assertEqual(len({x['key'] for x in tabs[0]['tcs']}), 3)
        o = tabs[1]['tcs'][0]
        self.assertEqual((o['aos'], o['comment']), ('Block', '코멘트'), '열 이름이 달라도(Android·Sub1·Comment 위치) 읽는다')

    def test_key_ignores_number_but_follows_text(self):
        tc = {'main': 'A', 'sub1': 'B', 'sub2': '', 'sub3': '', 'expected': '보인다.'}
        k1 = sheet_tc.tc_key('탭', tc)
        self.assertEqual(k1, sheet_tc.tc_key('탭', dict(tc, no='99')))
        self.assertEqual(k1, sheet_tc.tc_key('탭', dict(tc, expected='보인다.  ')), '앞뒤 공백·줄바꿈 차이는 같은 TC')
        self.assertNotEqual(k1, sheet_tc.tc_key('탭', dict(tc, expected='안 보인다.')))


if __name__ == '__main__':
    unittest.main()
