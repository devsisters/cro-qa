#!/usr/bin/env python3
"""테스트 시트(CSV)를 케이스 파일 뼈대로 바꾼다. 단계(steps)는 비워 두고 Claude 가 채운다.

  python3 tools/sheet_import.py <sheet.csv | 구글 시트 링크> --suite <이름> [--sheet-url URL]
                                [--map 열이름=필드 ...] [--header-row N] [--out cases/<이름>.json]

구글 시트 링크를 주면 CSV 내보내기 주소로 받아 본다 — 링크 공유가 「링크가 있는 모든 사용자」일 때만 된다.
회사 계정 전용 시트면 받지 못한다(exit 5). 그때는 사람에게 [파일 → 다운로드 → CSV] 로 받아 달라고 하거나,
Claude 의 Google Drive 연결로 읽어 CSV 로 저장한 뒤 이 도구에 준다.

열 → 필드 자동 대응(헤더 글자에 아래 낱말이 들어 있으면). 맞지 않으면 --map 으로 고친다.
  id        번호 · no · id · tc · 케이스
  priority  중요도 · 우선순위 · priority
  area      대분류 · 분류 · 카테고리 · 기능 · 콘텐츠
  sub       중분류 · 소분류 · 화면 · Sub1
  title     테스트 항목 · CheckList · 체크리스트 · 항목 · 제목 · 시나리오 · 확인 내용
  pre       사전 조건 · 전제 · 조건 · precondition
  steps     절차 · 스텝 · step · 테스트 방법 · 재현
  expected  기대 결과 · 예상 결과 · expected · 기대
  (결과·담당·비고 칸은 읽기만 해서 sheet.extra 에 둔다)
병합 셀(위 칸과 같은 대분류·중분류가 비어 있는 행)은 위 값을 이어받는다. 중분류 바로 왼쪽의 헤더 없는 열은 대분류로 본다.
--map 의 왼쪽에 「#열번호」(0부터)를 쓰면 헤더가 없는 열도 지정할 수 있다(예: --map "#2=area").
exit: 0 성공, 2 사용법, 4 헤더를 못 찾음, 5 링크로 받지 못함
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_common as qc  # noqa: E402

FIELDS = [
    ('expected', ['기대 결과', '기대결과', '예상 결과', '예상결과', 'expected', '기대']),
    ('steps', ['절차', '스텝', 'step', '테스트 방법', '방법', '재현']),
    ('pre', ['사전 조건', '사전조건', '전제', 'precondition', '조건']),
    ('id', ['번호', 'no', 'id', 'tc', '케이스']),
    ('priority', ['중요도', '우선순위', 'priority']),
    ('sub', ['중분류', '소분류', '화면', 'sub']),
    ('area', ['대분류', '분류', '카테고리', '기능', '콘텐츠']),
    ('title', ['테스트 항목', '확인 내용', '체크 내용', '체크리스트', 'checklist', '시나리오', '항목', '제목', '내용']),
]
CARRY = ('area', 'sub')


def guess(header):
    h = header.strip().lower()
    tokens = set(re.findall(r'[a-z]+', h))
    for field, words in FIELDS:
        for w in (x.lower() for x in words):
            # 짧은 영문(no·id·tc)은 낱말이 같을 때만 — note·android 같은 헤더를 잘못 잡지 않게
            if w == h or (w.isascii() and len(w) <= 4 and w in tokens) or (not (w.isascii() and len(w) <= 4) and w in h):
                return field
    return None


def fetch(url):
    m = re.search(r'/spreadsheets/d/([\w-]+)', url)
    if not m:
        raise ValueError('구글 시트 링크가 아니다')
    gid = re.search(r'[#&?]gid=(\d+)', url)
    export = f'https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv' + (f'&gid={gid.group(1)}' if gid else '')
    req = urllib.request.Request(export, headers={'User-Agent': 'qa-autotest-kit'})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        ctype = r.headers.get('Content-Type', '')
    if 'text/csv' not in ctype:
        raise PermissionError('CSV 가 아니라 로그인 화면이 왔다 — 회사 계정 전용 시트')
    return body.decode('utf-8-sig')


def find_header(rows, forced=None):
    if forced is not None:
        return forced
    for i, row in enumerate(rows[:15]):
        fields = {guess(c) for c in row if c.strip()} - {None}
        if len(fields) >= 2 and ('title' in fields or 'expected' in fields):
            return i
    return None


def convert(text, suite, sheet_url='', mapping=None, header_row=None):
    rows = list(csv.reader(io.StringIO(text)))
    h = find_header(rows, header_row)
    if h is None:
        raise LookupError('헤더 행을 찾지 못했다 — --header-row 와 --map 을 준다')
    header = rows[h]
    cols = {}
    for i, name in enumerate(header):
        f = (mapping or {}).get(name.strip()) or (mapping or {}).get(f'#{i}') or guess(name)
        if f and f not in cols:
            cols[f] = i
    # 병합된 대분류 칸은 헤더가 비어 있는 경우가 많다 — 중분류 바로 왼쪽의 이름 없는 열을 대분류로 본다
    if 'area' not in cols and 'sub' in cols and cols['sub'] > 0 and not header[cols['sub'] - 1].strip() \
            and cols['sub'] - 1 not in cols.values():
        cols['area'] = cols['sub'] - 1
    cases, last = [], {}
    for n, row in enumerate(rows[h + 1:], start=h + 2):
        if not any(c.strip() for c in row):
            continue
        get = {f: (row[i].strip() if i < len(row) else '') for f, i in cols.items()}
        for f in CARRY:
            if f in get:
                get[f] = get[f] or last.get(f, '')
                last[f] = get[f]
        if not (get.get('title') or get.get('steps') or get.get('expected')):
            continue
        extra = {header[i].strip(): row[i].strip() for i in range(min(len(header), len(row)))
                 if i not in cols.values() and header[i].strip() and row[i].strip()}
        cid = get.get('id') or f'R{n}'
        title = ' / '.join(x for x in (get.get('area'), get.get('sub'), get.get('title')) if x)
        cases.append({
            'id': cid if not cid.isdigit() else f'TC-{int(cid):03d}',
            'sheet_row': n,
            'title': title,
            'auto': None,
            'reason': '',
            'sheet': {k: get.get(k, '') for k in ('area', 'sub', 'priority', 'title', 'pre', 'steps', 'expected')} | ({'extra': extra} if extra else {}),
            'start': 'lobby',
            'steps': [],
        })
    ids = [c['id'] for c in cases]
    for c in cases:
        if ids.count(c['id']) > 1:
            c['id'] = f'{c["id"]}-R{c["sheet_row"]}'
    def letter(i):
        out = ''
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            out = chr(65 + r) + out
        return out
    # 결과를 다시 쓸 칸 — 헤더가 AOS·Android·iOS·comment 인 열
    result = {}
    for i, name in enumerate(header):
        n = name.strip().lower()
        if n in ('aos', 'android') and 'aos' not in result:
            result['aos'] = letter(i)
        elif n == 'ios' and 'ios' not in result:
            result['ios'] = letter(i)
        elif n in ('comment', '비고', 'comments') and 'comment' not in result:
            result['comment'] = letter(i)
    return {'suite': suite, 'sheet': sheet_url, 'preset': '', 'columns': {f: header[i] for f, i in cols.items()},
            'layout': {'headerRow': h + 1, 'resultColumns': result},
            'cases': cases}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('--suite', required=True)
    ap.add_argument('--sheet-url', default='')
    ap.add_argument('--map', action='append', default=[], help='열이름=필드 (필드: id area sub title pre steps expected)')
    ap.add_argument('--header-row', type=int, help='0부터 센 헤더 행 번호')
    ap.add_argument('--out')
    a = ap.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', a.suite):
        print('--suite 는 영문 소문자·숫자·-·_ (폴더 이름으로 쓴다)', file=sys.stderr)
        return 2
    mapping = dict(m.split('=', 1) for m in a.map)
    if a.source.startswith('http'):
        try:
            text = fetch(a.source)
        except (PermissionError, OSError, ValueError) as e:
            print(json.dumps({'ok': False, 'error': f'시트를 받지 못했다: {e}',
                              'next': '사람에게 [파일 → 다운로드 → 쉼표로 구분된 값(.csv)] 을 요청하거나 Google Drive 연결로 읽는다'},
                             ensure_ascii=False))
            return 5
        sheet_url = a.sheet_url or a.source
    else:
        text = open(a.source, encoding='utf-8-sig').read()
        sheet_url = a.sheet_url
    try:
        suite = convert(text, a.suite, sheet_url, mapping, a.header_row)
    except LookupError as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))
        return 4
    out = a.out or os.path.join(qc.CASES, f'{a.suite}.json')
    if os.path.exists(out):
        print(json.dumps({'ok': False, 'error': f'{out} 가 이미 있다 — 덮어쓰지 않는다. --out 으로 다른 이름을 준다'},
                         ensure_ascii=False))
        return 2
    qc.save_json(out, suite)
    print(json.dumps({'ok': True, 'out': out, 'cases': len(suite['cases']), 'columns': suite['columns']},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
