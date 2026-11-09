#!/usr/bin/env python3
"""QA 테스트 시트(xlsx)를 탭별 TC 목록으로 읽는다. 파이썬 기본 기능만 쓴다(xlsx 는 zip 안의 XML).

  python3 tools/sheet_tc.py <시트.xlsx> [--out <결과.json>] [--hidden]

QA 시트 형식(CRO_xx.xxN Test Case):
  - 탭마다 헤더 줄이 있다(보통 9번째 줄). 「No」 와 「Expectation Result」 가 있는 줄을 헤더로 본다
  - 열 이름이 탭마다 조금 다르다 — Sub-1/Sub1, AOS/Android, Comment 위치. 위치가 아니라 이름으로 찾는다
  - Main·Sub 칸은 병합 셀이라 비어 있으면 위 줄 값을 이어받는다. 위 단계가 새로 나오면 아래 단계는 비운다
  - No 없이 Main 만 있는 줄(「1. 진입」)은 구간 제목이다
  - 헤더가 없는 탭(Overview·환경·TC History)은 TC 탭이 아니다. 숨김 탭은 --hidden 일 때만 넣는다
출력: {"ok": true, "tabs": [{"name", "hidden", "tcs": [{"key", "no", "priority", "section", "main", "sub1", "sub2", "sub3",
       "expected", "aos", "ios", "jira", "comment", "row"}]}], "skipped": [탭 이름]}
key — 탭 이름 + 분류(Main~Sub3) + 기대 결과로 만든 12자리. 시나리오 파일이 TC 를 찾는 열쇠다. 번호(No)는 탭 안에서
      겹치기도 하고(한 번호 아래 기대 결과를 여러 줄로 적음) 다음 버전 시트에서 밀리기도 해서 열쇠로 쓰지 않는다
exit: 0 성공, 2 사용법, 4 xlsx 를 읽지 못함
"""
import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'}
R_ID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'

# 헤더 글자(공백·하이픈 없이 소문자) → 필드
HEADER = {
    'no': 'no', 'priority': 'priority', 'main': 'main',
    'sub1': 'sub1', 'sub2': 'sub2', 'sub3': 'sub3',
    'expectationresult': 'expected', 'expectedresult': 'expected',
    'aos': 'aos', 'android': 'aos', 'ios': 'ios',
    'jiralink': 'jira', 'jira': 'jira', 'comment': 'comment',
}
LEVELS = ('main', 'sub1', 'sub2', 'sub3')


def clean(text):
    # xlsx 는 제어 문자를 _xHHHH_ 로 적는다(예: _x0008_) — 풀어서 제어 문자는 버린다
    text = re.sub(r'_x([0-9A-Fa-f]{4})_', lambda m: chr(int(m.group(1), 16)), text)
    return ''.join(ch for ch in text if ch in '\n\t' or ord(ch) >= 32).strip()


def tc_key(tab, tc):
    norm = lambda v: re.sub(r'\s+', ' ', v or '').strip()
    raw = '\x1f'.join([norm(tab)] + [norm(tc[k]) for k in LEVELS] + [norm(tc['expected'])])
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]


def col_index(ref):
    letters = re.match(r'[A-Z]+', ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def shared_strings(z):
    if 'xl/sharedStrings.xml' not in z.namelist():
        return []
    out = []
    for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS):
        out.append(''.join(t.text or '' for t in si.iter(f'{{{NS["m"]}}}t')))
    return out


def sheet_rows(z, path, strings, limit_cols=40):
    """행 번호(1부터) → {열 번호: 글자}. 큰 시트도 메모리를 아끼려고 iterparse 로 읽는다."""
    rows = {}
    with z.open(path) as f:
        for _, el in ET.iterparse(f):
            if el.tag != f'{{{NS["m"]}}}c':
                continue
            ref = el.get('r')
            if not ref:
                continue
            ci = col_index(ref)
            if ci >= limit_cols:
                el.clear()
                continue
            t = el.get('t')
            v = el.find('m:v', NS)
            if t == 's' and v is not None:
                text = strings[int(v.text)]
            elif t == 'inlineStr':
                text = ''.join(x.text or '' for x in el.iter(f'{{{NS["m"]}}}t'))
            elif v is not None:
                text = v.text or ''
                if re.fullmatch(r'-?\d+\.0', text):
                    text = text[:-2]
            else:
                text = ''
            text = clean(text)
            if text:
                rows.setdefault(int(re.search(r'\d+', ref).group(0)), {})[ci] = text
            el.clear()
    return rows


def find_header(rows):
    for r in sorted(rows)[:40]:
        cells = rows[r]
        keys = {re.sub(r'[\s\-_]', '', v).lower(): c for c, v in cells.items()}
        if 'no' in keys and any(k.startswith('expect') for k in keys):
            cols = {}
            for k, c in keys.items():
                f = HEADER.get(k)
                if f and f not in cols:
                    cols[f] = c
            return r, cols
    return None, None


def read_tab(rows):
    head, cols = find_header(rows)
    if head is None or 'expected' not in cols:
        return None
    get = lambda cells, f: cells.get(cols[f], '') if f in cols else ''
    carry = {k: '' for k in LEVELS}
    section = ''
    tcs = []
    for r in sorted(x for x in rows if x > head):
        cells = rows[r]
        no = get(cells, 'no')
        expected = get(cells, 'expected')
        if not no:
            # 구간 제목 줄 — No·기대 결과가 없고 Main(또는 그 앞쪽 칸)에만 글자가 있다
            if not expected:
                title = get(cells, 'main') or next((v for c, v in sorted(cells.items()) if c < cols.get('expected', 99)), '')
                if title:
                    section = title
                    carry = {k: '' for k in LEVELS}
            continue
        for i, level in enumerate(LEVELS):
            value = get(cells, level)
            if value:
                carry[level] = value
                for deeper in LEVELS[i + 1:]:
                    carry[deeper] = ''
        tcs.append({'no': no, 'priority': get(cells, 'priority'), 'section': section,
                    **{k: carry[k] for k in LEVELS}, 'expected': expected,
                    'aos': get(cells, 'aos'), 'ios': get(cells, 'ios'),
                    'jira': get(cells, 'jira'), 'comment': get(cells, 'comment'), 'row': r})
    return tcs


def read_book(path, include_hidden=False):
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        target = {r.get('Id'): r.get('Target') for r in rels.findall('rel:Relationship', NS)}
        strings = shared_strings(z)
        tabs, skipped = [], []
        for sh in wb.find('m:sheets', NS).findall('m:sheet', NS):
            name = sh.get('name')
            hidden = sh.get('state') in ('hidden', 'veryHidden')
            if hidden and not include_hidden:
                continue
            t = target.get(sh.get(R_ID), '')
            part = t.lstrip('/') if t.startswith('/') else 'xl/' + t
            tcs = read_tab(sheet_rows(z, part, strings)) if part in z.namelist() else None
            if tcs is None:
                skipped.append(name)
                continue
            seen = {}
            for tc in tcs:
                k = tc_key(name, tc)
                seen[k] = seen.get(k, 0) + 1
                tc['key'] = k if seen[k] == 1 else f'{k}-{seen[k]}'   # 분류·문구가 똑같은 줄이 또 있으면 순번을 붙인다
            tabs.append({'name': name, 'hidden': hidden, 'tcs': tcs})
        return tabs, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx')
    ap.add_argument('--out')
    ap.add_argument('--hidden', action='store_true', help='숨김 탭도 읽는다')
    a = ap.parse_args()
    try:
        tabs, skipped = read_book(a.xlsx, a.hidden)
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as e:
        print(json.dumps({'ok': False, 'error': f'xlsx 를 읽지 못했다: {e}'}, ensure_ascii=False))
        return 4
    result = {'ok': True, 'title': os.path.splitext(os.path.basename(a.xlsx))[0], 'tabs': tabs, 'skipped': skipped}
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False)
        print(json.dumps({'ok': True, 'out': a.out, 'tabs': len(tabs), 'tcs': sum(len(t['tcs']) for t in tabs),
                          'skipped': skipped}, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
