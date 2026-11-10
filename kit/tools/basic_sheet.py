#!/usr/bin/env python3
"""기본 기능 시트(CRO_버젼별 기본기능) — TC 탭 읽기와 버전 결과 탭 쓰기 계획.

  python3 tools/basic_sheet.py tc <시트.xlsx> [--out ../basic/tc.json]     # TC 탭을 읽어 저장소 사본을 만든다
  python3 tools/basic_sheet.py add-tab --version 14.50                     # 결과 탭을 만드는 요청(addSheet)
  python3 tools/basic_sheet.py create --version 14.50 --sheet-id N         # 새 결과 탭에 쓸 값과 서식 요청
  python3 tools/basic_sheet.py update --run runs/<실행> [--run …] --ids <A열.json> --cols <G:L열.json>
                                                                          # 결과 칸에 쓸 범위와 값
  python3 tools/basic_sheet.py rows --run runs/<실행>                      # 실행 결과를 TC 별 결과 칸 값으로(확인용)

이 도구는 시트에 직접 쓰지 않는다. 시트 읽기·쓰기는 Google Sheets 연결 도구로 에이전트가 하고,
이 도구는 「어느 칸에 무엇을 쓸지」만 정한다. 절차는 basic/README.md 「결과 쓰기」.
--ids · --cols 는 get_values 결과(JSON)를 그대로 저장한 파일이다. --ids 는 '<버전>'!A1:A, --cols 는 '<버전>'!G1:L.
exit: 0 · 2 사용법 · 4 파일을 읽지 못함
"""
import argparse
import json
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_common as qc  # noqa: E402
import sheet_tc  # noqa: E402

REPO = os.path.dirname(qc.KIT)
BASIC = os.path.join(REPO, 'basic')
SHEET_FILE = os.path.join(BASIC, 'sheet.json')
TC_FILE = os.path.join(BASIC, 'tc.json')

# TC 탭 — 헤더 글자 → 필드
TC_HEADER = {'ID': 'id', '대분류': 'area', '중분류': 'sub', '중요도': 'priority', '확인 내용': 'check',
             '판정 항목': 'judge', '자동화 구분': 'class', '사전 조건': 'needs', '비고': 'note'}
# 결과 탭 — 열 순서가 곧 형식이다. 바꾸면 이미 만든 버전 탭과 어긋난다
RESULT_HEADER = ['ID', '대분류', '중분류', '중요도', '확인 내용', '자동화 구분',
                 'AOS', 'AOS 근거', 'AOS 실행', 'iOS', 'iOS 근거', 'iOS 실행', 'QA 메모']
PLATFORM_COLS = {'aos': ('G', 'I'), 'ios': ('J', 'L')}   # 결과·근거·실행 세 칸의 처음과 끝
STATUS = {'PASS': 'Pass', 'FAIL': 'Fail', 'ERROR': 'Block', 'REVIEW': 'Check', 'UNSURE': 'Check', 'HUMAN': 'Check',
          'NOT_RUN': 'N/T'}
STATUS_VALUES = ['Pass', 'Fail', 'Block', 'Check', 'N/T']
REASON_MAX = 450


def sheet_info():
    return qc.load_json(SHEET_FILE) if os.path.exists(SHEET_FILE) else {}


def quote_tab(name):
    return "'" + str(name).replace("'", "''") + "'"


# ---------- TC 탭 읽기 ----------

def read_tc_xlsx(path, tab='TC'):
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        target = {r.get('Id'): r.get('Target') for r in rels.findall('rel:Relationship', sheet_tc.NS)}
        strings = sheet_tc.shared_strings(z)
        for sh in wb.find('m:sheets', sheet_tc.NS).findall('m:sheet', sheet_tc.NS):
            if sh.get('name') != tab:
                continue
            t = target.get(sh.get(sheet_tc.R_ID), '')
            part = t.lstrip('/') if t.startswith('/') else 'xl/' + t
            return parse_tc_rows(sheet_tc.sheet_rows(z, part, strings))
    raise KeyError(f'「{tab}」 탭이 없다')


def parse_tc_rows(rows):
    """{행: {열: 글자}} → TC 목록. 헤더는 「ID」 가 있는 첫 줄이다"""
    head = next((r for r in sorted(rows)[:10] if 'ID' in rows[r].values()), None)
    if head is None:
        raise KeyError('「ID」 헤더 줄이 없다')
    cols = {TC_HEADER[v]: c for c, v in rows[head].items() if v in TC_HEADER}
    out = []
    for r in sorted(x for x in rows if x > head):
        cells = rows[r]
        tc = {f: cells.get(c, '') for f, c in cols.items()}
        if not re.match(r'^TC-\d+', tc.get('id', '')):
            continue
        tc['row'] = r
        out.append(tc)
    return out


# ---------- 실행 결과 → 결과 칸 ----------

def run_meta(run_dir):
    meta = qc.load_json(os.path.join(run_dir, 'basic.json')) if os.path.exists(os.path.join(run_dir, 'basic.json')) else {}
    if not meta.get('platform'):
        m = re.search(r'-(ios|aos)-\d{8}-\d{6}$', os.path.basename(os.path.normpath(run_dir)))
        meta['platform'] = m.group(1) if m else ''
    return meta


SKIP_TEXT = '확인 안 함 — '   # 조건 기기가 아니라 판정하지 않은 줄의 근거 머리


class Row(list):
    """결과 칸 세 개 [결과, 근거, 실행]. 기기 조건 줄이 있는 TC 는 lines(줄 이름 → (상태, 근거 줄))·partial 을 함께 든다
    — 시트에 쓸 때 다른 기기에서 먼저 쓴 줄 결과를 덮어쓰지 않고 합치는 데 쓴다."""
    lines = None
    partial = ''


def _cut(text):
    return text if len(text) <= REASON_MAX else text[:REASON_MAX - 1] + '…'


def cp_line(c, cp):
    """checkpoint 하나 → (상태, 근거 줄). 상태: PASS · FAIL · HUMAN · SKIP(조건 기기 아님) · 그 밖의 판정"""
    if cp.get('verdict') == 'NOT_RUN' and cp.get('device'):
        return 'SKIP', f'{cp["name"]}: {SKIP_TEXT}{cp["device"]}'
    bad = [f'{x["check"]} ({x.get("detail", "")})' for x in cp.get('checks', []) if not x.get('ok')]
    if bad:
        return 'FAIL', f'{cp["name"]}: ✗ ' + '; '.join(bad)
    if cp.get('verdict') == 'HUMAN':
        return 'HUMAN', f'{cp["name"]}: 사람 확인 — {cp.get("human") or "캡처를 보고 판단"}'
    if cp.get('verdict') == 'PASS':
        n = len(cp.get('checks', []))
        on = {x['name']: x['device'] for x in c.get('deviceChecked', [])}.get(cp['name'])
        return 'PASS', (f'{cp["name"]}: 조건 {n}개 통과' if n else f'{cp["name"]}: 통과') + (f' ({on})' if on else '')
    return cp.get('verdict') or '', ''


def reason_of(c):
    """판정 근거 — 사람이 시트에서 읽고 바로 이해할 한두 줄"""
    v = c.get('verdict')
    lines = []
    if c.get('error'):
        e = c['error']
        lines.append(f'진행 실패: {e.get("kind", "")} at {e.get("step", "")} — {e.get("detail", "")}'.strip())
    skipped = False
    for cp in c.get('checkpoints', []):
        st, text = cp_line(c, cp)
        skipped = skipped or st == 'SKIP'
        if text:
            lines.append(text)
    for x in c.get('actions', []):
        if x.get('verdict') == 'FAILED':
            lines.append(f'액션 실패: {x.get("label", "")} — {x.get("detail", "")}')
    if c.get('partial'):
        lines.append(f'일부만 자동 확인: {c["partial"]}')
    elif c.get('reason') and (not lines or (v == 'UNSURE' and not skipped)):   # Check 는 왜 Pass 가 아닌지 함께 적는다
        lines.append(c['reason'])
    if v == 'NOT_RUN' and not lines:
        lines.append('실행하지 않음(자동화 단계 없음)')
    return _cut('\n'.join(lines))


def merge_lines(row, old_reason, old_stamp):
    """기기 조건 줄이 있는 TC — 이번 실행에서 「확인 안 함」인 줄은 시트에 이미 있는 그 줄의 자동 결과를 살린다.
    줄을 합친 뒤 결과를 다시 정한다: 실패 줄이 있으면 Fail, 확인 안 한 줄·사람 확인 줄·partial 이 있으면 Check, 모두 통과면 Pass.
    합칠 것이 없으면 row 그대로."""
    old = {}
    for ln in (old_reason or '').splitlines():
        name, sep, rest = ln.partition(': ')
        if not sep or name not in row.lines:
            continue
        st = ('SKIP' if rest.startswith(SKIP_TEXT) else 'FAIL' if rest.startswith('✗') else
              'HUMAN' if rest.startswith('사람 확인') else 'PASS' if '통과' in rest else '')
        if st:
            old[name] = (st, ln)
    merged, kept = {}, False
    for name, (st, text) in row.lines.items():
        if st == 'SKIP' and old.get(name, ('SKIP',))[0] != 'SKIP':
            merged[name] = old[name]
            kept = True
        else:
            merged[name] = (st, text)
    if not kept:
        return list(row)
    sts = [s for s, _ in merged.values()]
    status = 'Fail' if 'FAIL' in sts else 'Pass' if all(s == 'PASS' for s in sts) and not row.partial else 'Check'
    lines = [t for _, t in merged.values()] + ([f'일부만 자동 확인: {row.partial}'] if row.partial else [])
    stamp = row[2] + (f'\n(앞 실행에서 가져온 줄: {old_stamp.splitlines()[0]})' if old_stamp else '')
    return [status, _cut('\n'.join(lines)), stamp]


def result_rows(run_dir):
    """실행 폴더 → {TC ID: [결과, 근거, 실행]}"""
    results = qc.load_json(os.path.join(run_dir, 'results.json'))
    meta = run_meta(run_dir)
    at = (meta.get('at') or results.get('started') or '')[:16].replace('T', ' ')
    run_rel = os.path.relpath(os.path.abspath(run_dir), qc.KIT)
    who = meta.get('by') or ''
    di = results.get('deviceInfo') or {}
    dev = ' '.join(x for x in (di.get('model'), f'OS {di["os"]}' if di.get('os') else '') if x)
    stamp = ' · '.join(x for x in (at, who, dev, run_rel) if x)
    out = {}
    for c in results.get('cases', []):
        if c.get('verdict') == 'NOT_RUN':
            continue   # 돌리지 않은 TC(자동화 단계 없음·재화 사용 등) — 칸을 건드리지 않는다(N/T 그대로, 사람이 적은 결과도 그대로)
        row = Row([STATUS.get(c.get('verdict'), 'Check'), reason_of(c), stamp])
        if not c.get('error') and any(cp.get('device') for cp in c.get('checkpoints', [])):
            row.lines = {cp['name']: cp_line(c, cp) for cp in c.get('checkpoints', [])}
            row.partial = c.get('partial') or ''
        out[c['id']] = row
    return meta.get('platform'), out


def values_of(get_values_json):
    data = get_values_json if isinstance(get_values_json, dict) else {}
    return data.get('values') or []


def plan_update(tab, runs, ids_values, cols_values, tcs=None):
    """결과 탭의 지금 값(A열, G:L열)과 실행 결과로 쓸 범위를 정한다.
    사람이 적은 결과(결과 칸이 N/T·빈칸이 아닌데 실행 칸이 비어 있음)는 덮어쓰지 않고 skipped 에 남긴다."""
    tcs = tcs or {}
    ids = [(r[0] if r else '') for r in ids_values]
    row_of = {v: i + 1 for i, v in enumerate(ids) if v}
    last = len(ids)
    writes = {}   # 행 번호 → {열 글자: 값}
    appended = []
    skipped = []
    for platform, rows in runs:
        first_col, _ = PLATFORM_COLS[platform]
        off = ord(first_col) - ord('G')          # cols_values 는 G 열부터
        for tc_id, vals in rows.items():
            r = row_of.get(tc_id)
            if r is None:
                last += 1
                r = last
                row_of[tc_id] = r
                tc = tcs.get(tc_id, {})
                writes.setdefault(r, {}).update(zip('ABCDEF', [tc_id, tc.get('area', ''), tc.get('sub', ''), tc.get('priority', ''),
                                                              tc.get('check', ''), tc.get('class', '')]))
                appended.append(tc_id)
            else:
                cur = cols_values[r - 1] if r - 1 < len(cols_values) else []
                res = cur[off] if len(cur) > off else ''
                ran = cur[off + 2] if len(cur) > off + 2 else ''
                if res not in ('', 'N/T') and not ran:
                    skipped.append({'id': tc_id, 'platform': platform, 'row': r, 'value': res,
                                    'why': '사람이 적은 결과로 보인다(실행 칸이 비어 있다) — 덮어쓰지 않았다'})
                    continue
                if getattr(vals, 'lines', None) and ran:
                    # 기기 조건 줄 — 다른 기기에서 먼저 쓴 줄 결과를 살려 합친다
                    vals = merge_lines(vals, cur[off + 1] if len(cur) > off + 1 else '', ran)
            writes.setdefault(r, {}).update(zip([first_col, chr(ord(first_col) + 1), chr(ord(first_col) + 2)], vals))
    updates = []
    # 같은 열 묶음을 가진 연속 행은 한 범위로 합친다
    for r in sorted(writes):
        cols = sorted(writes[r])
        lo, hi = cols[0], cols[-1]
        span = [chr(c) for c in range(ord(lo), ord(hi) + 1)]
        if any(c not in writes[r] for c in span):
            for c in cols:   # 띄엄띄엄이면 칸마다
                updates.append({'range': f'{quote_tab(tab)}!{c}{r}', 'values': [[writes[r][c]]]})
            continue
        row_vals = [writes[r][c] for c in span]
        prev = updates[-1] if updates else None
        m = prev and re.match(r"^(.*)!([A-Z])(\d+):([A-Z])(\d+)$", prev['range'])
        if m and m.group(2) == lo and m.group(4) == hi and int(m.group(5)) == r - 1:
            prev['range'] = f'{m.group(1)}!{lo}{m.group(3)}:{hi}{r}'
            prev['values'].append(row_vals)
        else:
            updates.append({'range': f'{quote_tab(tab)}!{lo}{r}:{hi}{r}', 'values': [row_vals]})
    return {'updates': updates, 'appended': appended, 'skipped': skipped}


# ---------- 결과 탭 만들기 ----------

def create_payload(version, sheet_id, tcs):
    tab = str(version)
    values = [RESULT_HEADER] + [[t['id'], t.get('area', ''), t.get('sub', ''), t.get('priority', ''), t.get('check', ''),
                                 t.get('class', ''), 'N/T', '', '', 'N/T', '', '', ''] for t in tcs]
    n = len(values)
    summary = [['결과', 'AOS', 'iOS']] + [[s, f'=COUNTIF($G$2:$G,O{i + 2})', f'=COUNTIF($J$2:$J,O{i + 2})']
                                         for i, s in enumerate(STATUS_VALUES)]
    rng = lambda r0, r1, c0, c1: {'sheetId': sheet_id, 'startRowIndex': r0, 'endRowIndex': r1, 'startColumnIndex': c0, 'endColumnIndex': c1}
    width = lambda c0, c1, px: {'updateDimensionProperties': {'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': c0, 'endIndex': c1},
                                                             'properties': {'pixelSize': px}, 'fields': 'pixelSize'}}
    status_rule = {'condition': {'type': 'ONE_OF_LIST', 'values': [{'userEnteredValue': s} for s in STATUS_VALUES]},
                   'strict': True, 'showCustomUi': True}
    color = {'Pass': (0.85, 0.94, 0.85), 'Fail': (0.98, 0.83, 0.83), 'Block': (0.99, 0.91, 0.78), 'Check': (1.0, 0.96, 0.75)}
    requests = [
        {'repeatCell': {'range': rng(0, n + 50, 0, 13), 'cell': {'userEnteredFormat': {'wrapStrategy': 'WRAP', 'verticalAlignment': 'TOP',
                        'textFormat': {'fontFamily': 'Arial', 'fontSize': 10}}},
                        'fields': 'userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment,userEnteredFormat.textFormat.fontFamily,userEnteredFormat.textFormat.fontSize'}},
        {'repeatCell': {'range': rng(0, 1, 0, 13), 'cell': {'userEnteredFormat': {'textFormat': {'bold': True, 'fontFamily': 'Arial', 'fontSize': 10},
                        'backgroundColorStyle': {'rgbColor': {'red': 0.85, 'green': 0.88, 'blue': 0.93}}}},
                        'fields': 'userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColorStyle'}},
        {'repeatCell': {'range': rng(0, 1, 14, 17), 'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}}, 'fields': 'userEnteredFormat.textFormat.bold'}},
        width(0, 1, 70), width(1, 3, 100), width(3, 4, 70), width(4, 5, 300), width(5, 6, 80),
        width(6, 7, 60), width(7, 8, 260), width(8, 9, 200), width(9, 10, 60), width(10, 11, 260), width(11, 12, 200), width(12, 13, 220),
        {'setDataValidation': {'range': rng(1, n + 50, 6, 7), 'rule': status_rule}},
        {'setDataValidation': {'range': rng(1, n + 50, 9, 10), 'rule': status_rule}},
    ]
    for s, (r, g, b) in color.items():
        requests.append({'addConditionalFormatRule': {'rule': {'ranges': [rng(1, n + 50, 6, 7), rng(1, n + 50, 9, 10)],
                         'booleanRule': {'condition': {'type': 'TEXT_EQ', 'values': [{'userEnteredValue': s}]},
                                         'format': {'backgroundColorStyle': {'rgbColor': {'red': r, 'green': g, 'blue': b}}}}}, 'index': 0}})
    return {'tab': tab, 'values': {'range': f'{quote_tab(tab)}!A1:M{n}', 'values': values},
            'summary': {'range': f'{quote_tab(tab)}!O1:Q{len(summary)}', 'values': summary},
            'requests': requests}


def add_tab_request(version, rows):
    return {'addSheet': {'properties': {'title': str(version), 'gridProperties': {'rowCount': rows + 60, 'columnCount': 17,
                                                                                    'frozenRowCount': 1, 'frozenColumnCount': 1}}}}


def load_tcs():
    if not os.path.exists(TC_FILE):
        raise OSError(f'TC 사본이 없다: {TC_FILE} — QA 앱 「기본 기능」 탭에서 「시트에서 다시 읽기」를 먼저 한다')
    return qc.load_json(TC_FILE).get('tcs', [])


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('tc')
    p.add_argument('xlsx')
    p.add_argument('--out', default=TC_FILE)
    p.add_argument('--tab', default='TC')
    p.add_argument('--url', default='')
    p = sub.add_parser('add-tab')
    p.add_argument('--version', required=True)
    p = sub.add_parser('create')
    p.add_argument('--version', required=True)
    p.add_argument('--sheet-id', type=int, required=True)
    p = sub.add_parser('update')
    p.add_argument('--run', action='append', required=True)
    p.add_argument('--ids', required=True)
    p.add_argument('--cols', required=True)
    p.add_argument('--version')
    p = sub.add_parser('rows')
    p.add_argument('--run', required=True)
    a = ap.parse_args()
    info = sheet_info()
    try:
        if a.cmd == 'tc':
            tcs = read_tc_xlsx(a.xlsx, a.tab)
            data = {'url': a.url or info.get('url', ''), 'spreadsheetId': info.get('spreadsheetId', ''), 'tab': a.tab,
                    'readAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'tcs': [{k: v for k, v in t.items() if k != 'row'} for t in tcs]}
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            with open(a.out, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
                f.write('\n')
            print(json.dumps({'ok': True, 'out': a.out, 'tcs': len(tcs)}, ensure_ascii=False))
        elif a.cmd == 'add-tab':
            print(json.dumps({'spreadsheetId': info.get('spreadsheetId'), 'requests': [add_tab_request(a.version, len(load_tcs()))]},
                             ensure_ascii=False))
        elif a.cmd == 'create':
            out = create_payload(a.version, a.sheet_id, load_tcs())
            out['spreadsheetId'] = info.get('spreadsheetId')
            print(json.dumps(out, ensure_ascii=False))
        elif a.cmd == 'update':
            runs, version = [], a.version
            for d in a.run:
                platform, rows = result_rows(d)
                if platform not in PLATFORM_COLS:
                    print(json.dumps({'ok': False, 'error': f'플랫폼을 모르는 실행 폴더: {d}'}, ensure_ascii=False))
                    return 2
                runs.append((platform, rows))
                version = version or run_meta(d).get('version')
            if not version:
                print(json.dumps({'ok': False, 'error': '버전을 모른다 — --version 을 준다'}, ensure_ascii=False))
                return 2
            tcs = {t['id']: t for t in load_tcs()} if os.path.exists(TC_FILE) else {}
            plan = plan_update(str(version), runs, values_of(qc.load_json(a.ids)), values_of(qc.load_json(a.cols)), tcs)
            plan.update({'ok': True, 'spreadsheetId': info.get('spreadsheetId'), 'tab': str(version)})
            print(json.dumps(plan, ensure_ascii=False))
        elif a.cmd == 'rows':
            platform, rows = result_rows(a.run)
            print(json.dumps({'platform': platform, 'version': run_meta(a.run).get('version'), 'rows': rows}, ensure_ascii=False))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))
        return 4
    return 0


if __name__ == '__main__':
    sys.exit(main())
