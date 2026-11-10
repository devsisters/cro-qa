#!/usr/bin/env python3
"""기본 기능 시트(CRO_버젼별 기본기능) — TC 탭 읽기와 버전 결과 탭 쓰기 계획.

  python3 tools/basic_sheet.py tc <시트.xlsx> [--out ../basic/tc.json]     # TC 탭을 읽어 저장소 사본을 만든다
  python3 tools/basic_sheet.py add-tab --version 14.50                     # 결과 탭을 만드는 요청(addSheet)
  python3 tools/basic_sheet.py create --version 14.50 --sheet-id N         # 새 결과 탭에 쓸 값과 서식 요청
  python3 tools/basic_sheet.py update --run runs/<실행> [--run …] --ids <A:D열.json> --cols <H:M열.json>
                                                                          # 결과 칸에 쓸 범위와 값
  python3 tools/basic_sheet.py rows --run runs/<실행>                      # 실행 결과를 TC 별 결과 칸 값으로(확인용)
  python3 tools/basic_sheet.py shots --run runs/<실행>                     # 결과 칸에 붙일 캡처(Drive 에 올릴 파일·sha256)

이 도구는 시트에 직접 쓰지 않는다. 시트 읽기·쓰기는 Google Sheets 연결 도구로 에이전트가 하고,
이 도구는 「어느 칸에 무엇을 쓸지」만 정한다. 절차는 basic/README.md 「결과 쓰기」.
--ids · --cols 는 get_values 결과(JSON)를 그대로 저장한 파일이다. --ids 는 '<버전>'!A1:D(ID·담당자), --cols 는 '<버전>'!H1:M.
결과 칸(AOS 결과·iOS 결과)에는 캡처 링크만 쓴다(시트의 Apps Script 가 그 그림을 붙인다). 실행자는 담당자 칸에 쓴다. 캡처는 shots 로 고른 파일을 Drive 에 올리고
그 id 를 실행 폴더의 drive.json {"files": {"<rel>": "<fileId>"}} 에 적으면 링크가 된다(없으면 실행 폴더 경로).
exit: 0 · 2 사용법 · 4 파일을 읽지 못함
"""
import argparse
import glob
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
RESULT_HEADER = ['ID', '대분류', '중분류', '담당자', '중요도', '확인 내용', '자동화 구분',
                 'AOS', 'AOS 근거', 'AOS 결과', 'iOS', 'iOS 근거', 'iOS 결과', 'QA 메모']
PLATFORM_COLS = {'aos': ('H', 'J'), 'ios': ('K', 'M')}   # 판정·근거·결과(캡처) 세 칸의 처음과 끝
OWNER_COL = 'D'          # 담당자 — 테스트를 돌린 계정
FIRST_RESULT_COL = 'H'   # --cols 는 이 열부터 읽은 값이다
DRIVE_FILE = 'drive.json'   # 실행 폴더 안 — 캡처를 Drive 에 올린 파일 id {"files": {"<실행 폴더 기준 경로>": "<fileId>"}}
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
    by = ''
    stamp = ''   # 시각 · 실행자 · 기기 · 실행 폴더 — 시트에는 쓰지 않는다(rows 확인용)


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


def merge_lines(row, old_reason, old_result):
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
    merged, kept_names = {}, set()
    for name, (st, text) in row.lines.items():
        if st == 'SKIP' and old.get(name, ('SKIP',))[0] != 'SKIP':
            merged[name] = old[name]
            kept_names.add(name)
        else:
            merged[name] = (st, text)
    if not kept_names:
        return list(row)
    sts = [s for s, _ in merged.values()]
    status = 'Fail' if 'FAIL' in sts else 'Pass' if all(s == 'PASS' for s in sts) and not row.partial else 'Check'
    lines = [t for _, t in merged.values()] + ([f'일부만 자동 확인: {row.partial}'] if row.partial else [])
    # 결과 칸(캡처 링크): 이번 실행 캡처 + 가져온 줄의 앞 실행 캡처
    old_shots = [ln for ln in (old_result or '').splitlines() if ln.partition(': ')[0] in kept_names]
    result = '\n'.join([x for x in [row[2]] if x] + old_shots)
    return [status, _cut('\n'.join(lines)), result]


def shot_files(run_dir):
    """실행 폴더의 캡처 — 결과 칸에 붙일 것: 채점 지점 캡처, 진행 실패 화면. [(TC, 이름, 실행 폴더 기준 경로)]"""
    results = qc.load_json(os.path.join(run_dir, 'results.json'))
    out = []
    for c in results.get('cases', []):
        if c.get('verdict') == 'NOT_RUN':
            continue
        for cp in c.get('checkpoints', []):
            if cp.get('shot') and os.path.exists(cp['shot']):
                out.append((c['id'], cp['name'], os.path.relpath(cp['shot'], run_dir)))
        shot = (c.get('error') or {}).get('shot')
        if shot and os.path.exists(shot):
            out.append((c['id'], '진행 실패 화면', os.path.relpath(shot, run_dir)))
    return out


UPLOAD_MAX = 960   # 올리는 캡처의 긴 변(px) — 시트 그림(Apps Script insertImage)은 2MB 를 넘으면 넣지 못한다


def upload_copy(src, dst_base):
    """올릴 캡처 — 긴 변 UPLOAD_MAX 의 JPEG 사본(macOS sips). 만들지 못하면 원본을 그대로 올린다."""
    import subprocess
    dst = os.path.splitext(dst_base)[0] + '.jpg'
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        r = subprocess.run(['sips', '-Z', str(UPLOAD_MAX), '-s', 'format', 'jpeg', '-s', 'formatOptions', '80', src, '--out', dst],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and os.path.exists(dst):
            return dst
    except (OSError, subprocess.SubprocessError):
        pass
    return src


def shot_entries(run_dir):
    """올릴 캡처 목록 — (실행 메타, [{tc, name, rel, path, sha256, uploaded, mime, title}]). 사본(upload/)을 만들고 drive.json 으로 올린 것을 가른다."""
    import hashlib
    meta = run_meta(run_dir)
    done = (qc.load_json(os.path.join(run_dir, DRIVE_FILE)) if os.path.exists(os.path.join(run_dir, DRIVE_FILE)) else {}).get('files', {})
    files = []
    for tc, name, rel in shot_files(run_dir):
        path = upload_copy(os.path.abspath(os.path.join(run_dir, rel)), os.path.join(os.path.abspath(run_dir), 'upload', rel))
        with open(path, 'rb') as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        files.append({'tc': tc, 'name': name, 'rel': rel, 'path': path, 'sha256': digest, 'uploaded': rel in done,
                      'mime': 'image/jpeg' if path.endswith('.jpg') else 'image/png',
                      'title': f'{meta.get("version", "")}_{meta.get("platform", "")}_{tc}_{name}_{os.path.basename(os.path.normpath(run_dir))[-15:]}'
                               + os.path.splitext(path)[1]})
    return meta, files


CAPTURE_BASE_GLOB = os.path.expanduser('~/Library/CloudStorage/GoogleDrive-*')   # Google Drive 데스크톱이 만드는 폴더(계정마다 이름이 다르다)
DRIVE_ID_ATTR = 'com.google.drivefs.item-id#S'                                  # 동기화된 파일의 Drive id 가 든 확장 속성


def capture_dir(info):
    """Drive 데스크톱에 보이는 캡처 폴더 — sheet.json 의 captureDrivePath(공유 드라이브 아래 경로). 없으면 None.
    환경변수 QA_CAPTURE_DIR 이 있으면 그 폴더를 쓴다(경로가 다른 컴퓨터용)."""
    env = os.environ.get('QA_CAPTURE_DIR')
    if env:
        return env if os.path.isdir(env) else None
    rel = info.get('captureDrivePath') or ''
    for base in sorted(glob.glob(CAPTURE_BASE_GLOB)):
        path = os.path.join(base, rel)
        if rel and os.path.isdir(path):
            return path
    return None


def drive_item_id(path):
    """동기화된 파일의 Drive id — 올라가기 전에는 비어 있다."""
    import subprocess
    try:
        r = subprocess.run(['xattr', '-p', DRIVE_ID_ATTR, path], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ''
    return r.stdout.strip() if r.returncode == 0 else ''


def upload_run(run_dir, base_dir, id_of=drive_item_id, wait=180, interval=2):
    """아직 안 올린 캡처를 Drive 데스크톱 폴더(base_dir/<버전>/)에 복사하고, Drive 가 올린 뒤 생기는 파일 id 를 drive.json 에 적는다.
    같은 이름이 이미 있으면 덮어쓰지 않고 그 파일의 id 를 쓴다. 하나 끝날 때마다 저장해 중간에 끊겨도 이어간다."""
    import shutil
    meta, files = shot_entries(run_dir)
    dest = os.path.join(base_dir, str(meta.get('version', '')))
    os.makedirs(dest, exist_ok=True)
    drive_path = os.path.join(run_dir, DRIVE_FILE)
    drive = qc.load_json(drive_path) if os.path.exists(drive_path) else {}
    drive.setdefault('files', {})
    out = {'ok': True, 'run': run_dir, 'folder': dest, 'copied': 0, 'existed': 0, 'skipped': 0, 'failed': [], 'driveFile': drive_path}
    pending = []
    for f in files:
        if f['uploaded']:
            out['skipped'] += 1
            continue
        target = os.path.join(dest, f['title'])
        if os.path.exists(target):
            out['existed'] += 1
        else:
            shutil.copy2(f['path'], target)
            out['copied'] += 1
        pending.append((f, target))
    deadline = time.time() + wait
    while pending:
        for item in list(pending):
            fid = id_of(item[1])
            if fid:
                drive['files'][item[0]['rel']] = fid
                pending.remove(item)
                with open(drive_path, 'w', encoding='utf-8') as fh:
                    json.dump(drive, fh, ensure_ascii=False, indent=1)
        if not pending or time.time() > deadline:
            break
        time.sleep(interval)
    out['failed'] = [{'rel': f['rel'], 'error': f'{wait}초 안에 Drive 가 파일 id 를 주지 않았다 — Google Drive 앱의 동기화 상태를 본다'} for f, _ in pending]
    out['ok'] = not out['failed']
    return out


def shot_lines(run_dir, tc_id):
    """결과 칸에 쓸 캡처 줄 — Drive 에 올렸으면 링크, 아니면 실행 폴더 안 경로"""
    path = os.path.join(run_dir, DRIVE_FILE)
    drive = (qc.load_json(path) if os.path.exists(path) else {}).get('files', {})
    lines = []
    for tc, name, rel in shot_files(run_dir):
        if tc == tc_id:
            fid = drive.get(rel)
            lines.append(f'{name}: ' + (f'https://drive.google.com/file/d/{fid}/view' if fid else f'(올리지 않음) {rel}'))
    return lines


def result_rows(run_dir):
    """실행 폴더 → {TC ID: [판정, 근거, 결과(캡처 링크)]}. 각 값의 .by 는 돌린 계정(담당자 칸), .stamp 는 실행 기록(시트에 쓰지 않음)"""
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
        row = Row([STATUS.get(c.get('verdict'), 'Check'), reason_of(c), '\n'.join(shot_lines(run_dir, c['id']))])
        row.stamp = stamp
        row.by = who
        if not c.get('error') and any(cp.get('device') for cp in c.get('checkpoints', [])):
            row.lines = {cp['name']: cp_line(c, cp) for cp in c.get('checkpoints', [])}
            row.partial = c.get('partial') or ''
        out[c['id']] = row
    return meta.get('platform'), out


def owner_value(cur, who):
    """담당자 칸 — 비어 있으면 돌린 계정, 다른 사람이 있으면 덧붙인다(지우지 않는다)"""
    names = [x.strip() for x in (cur or '').split(',') if x.strip()]
    if not who or who in names:
        return None
    return ', '.join(names + [who])


def values_of(get_values_json):
    data = get_values_json if isinstance(get_values_json, dict) else {}
    return data.get('values') or []


def plan_update(tab, runs, ids_values, cols_values, tcs=None):
    """결과 탭의 지금 값(A:D열 — ID·담당자, H:M열)과 실행 결과로 쓸 범위를 정한다.
    사람이 적은 결과(판정 칸이 N/T·빈칸이 아닌데 결과 칸이 비어 있음)는 덮어쓰지 않고 skipped 에 남긴다.
    담당자 칸에는 돌린 계정을 적는다(이미 다른 사람이 있으면 덧붙인다)."""
    tcs = tcs or {}
    ids = [(r[0] if r else '') for r in ids_values]
    owners = {i + 1: (r[3] if len(r) > 3 else '') for i, r in enumerate(ids_values)}
    row_of = {v: i + 1 for i, v in enumerate(ids) if v}
    last = len(ids)
    writes = {}   # 행 번호 → {열 글자: 값}
    appended = []
    skipped = []
    for platform, rows in runs:
        first_col, _ = PLATFORM_COLS[platform]
        off = ord(first_col) - ord(FIRST_RESULT_COL)   # cols_values 는 H 열부터
        for tc_id, vals in rows.items():
            r = row_of.get(tc_id)
            if r is None:
                last += 1
                r = last
                row_of[tc_id] = r
                tc = tcs.get(tc_id, {})
                writes.setdefault(r, {}).update(zip('ABCDEFG', [tc_id, tc.get('area', ''), tc.get('sub', ''), '', tc.get('priority', ''),
                                                               tc.get('check', ''), tc.get('class', '')]))
                appended.append(tc_id)
            else:
                cur = cols_values[r - 1] if r - 1 < len(cols_values) else []
                res = cur[off] if len(cur) > off else ''
                why = cur[off + 1] if len(cur) > off + 1 else ''
                shots = cur[off + 2] if len(cur) > off + 2 else ''
                auto = bool(why or shots)   # 자동 실행은 근거 칸을 늘 채운다
                if res not in ('', 'N/T') and not auto:
                    skipped.append({'id': tc_id, 'platform': platform, 'row': r, 'value': res,
                                    'why': '사람이 적은 결과로 보인다(근거·결과 칸이 비어 있다) — 덮어쓰지 않았다'})
                    continue
                if getattr(vals, 'lines', None) and auto:
                    # 기기 조건 줄 — 다른 기기에서 먼저 쓴 줄 결과를 살려 합친다
                    vals = merge_lines(vals, why, shots)
            owner = owner_value(writes.get(r, {}).get(OWNER_COL, owners.get(r, '')), getattr(rows.get(tc_id), 'by', ''))
            if owner:
                writes.setdefault(r, {})[OWNER_COL] = owner
            writes.setdefault(r, {}).update(zip([first_col, chr(ord(first_col) + 1), chr(ord(first_col) + 2)], vals))
    # 한 행의 칸을 이어진 열 묶음으로 나누고, 같은 열 묶음이 바로 윗행에도 있으면 한 범위로 합친다
    blocks = []      # [lo, hi, 첫 행, 끝 행, values]
    open_by = {}     # (lo, hi) → 끝 행이 바로 위인 블록
    for r in sorted(writes):
        cols = sorted(writes[r])
        segs, seg = [], [cols[0]]
        for c in cols[1:]:
            if ord(c) == ord(seg[-1]) + 1:
                seg.append(c)
            else:
                segs.append(seg)
                seg = [c]
        segs.append(seg)
        for seg in segs:
            lo, hi = seg[0], seg[-1]
            row_vals = [writes[r][c] for c in seg]
            b = open_by.get((lo, hi))
            if b and b[3] == r - 1:
                b[3] = r
                b[4].append(row_vals)
            else:
                b = [lo, hi, r, r, [row_vals]]
                blocks.append(b)
                open_by[(lo, hi)] = b
    updates = [{'range': f'{quote_tab(tab)}!{lo}{r0}' + (f':{hi}{r1}' if (lo, r0) != (hi, r1) else ''), 'values': vals}
               for lo, hi, r0, r1, vals in blocks]
    links = [(r, c, v) for r in sorted(writes) for c, v in sorted(writes[r].items()) if isinstance(v, str) and URL_RE.search(v)]
    return {'updates': updates, 'appended': appended, 'skipped': skipped, 'links': links}


URL_RE = re.compile(r'https?://\S+')


def link_requests(sheet_id, links):
    """URL 이 든 칸을 같은 글자 + 링크 서식(textFormatRuns)으로 다시 쓰는 updateCells 요청 — 값만 쓰면 글 중간 URL 은 눌리지 않는다.
    위치는 UTF-16 단위다(Sheets API)."""
    def u16(s):
        return len(s.encode('utf-16-le')) // 2
    reqs = []
    for r, c, text in links:
        runs, end = [], 0
        for m in URL_RE.finditer(text):
            runs.append({'startIndex': u16(text[:m.start()]), 'format': {'link': {'uri': m.group(0)}}})
            end = m.end()
            if end < len(text):
                runs.append({'startIndex': u16(text[:end]), 'format': {}})
        if runs and runs[0]['startIndex'] > 0:
            runs.insert(0, {'startIndex': 0, 'format': {}})
        col = ord(c) - ord('A')
        reqs.append({'updateCells': {'range': {'sheetId': sheet_id, 'startRowIndex': r - 1, 'endRowIndex': r, 'startColumnIndex': col, 'endColumnIndex': col + 1},
                                     'rows': [{'values': [{'userEnteredValue': {'stringValue': text}, 'textFormatRuns': runs}]}],
                                     'fields': 'userEnteredValue,textFormatRuns'}})
    return reqs


# ---------- 결과 탭 만들기 ----------

def create_payload(version, sheet_id, tcs):
    tab = str(version)
    values = [RESULT_HEADER] + [[t['id'], t.get('area', ''), t.get('sub', ''), '', t.get('priority', ''), t.get('check', ''),
                                 t.get('class', ''), 'N/T', '', '', 'N/T', '', '', ''] for t in tcs]
    n = len(values)
    ncol = len(RESULT_HEADER)                                   # A~N
    aos, ios = (ord(PLATFORM_COLS[p][0]) - ord('A') for p in ('aos', 'ios'))   # 판정 칸 열 번호(0부터)
    sc = ncol + 1                                               # 한 칸 띄우고 요약(P~R)
    col = lambda i: chr(ord('A') + i)
    summary = [['결과', 'AOS', 'iOS']] + [[s, f'=COUNTIF(${col(aos)}$2:${col(aos)},{col(sc)}{i + 2})',
                                          f'=COUNTIF(${col(ios)}$2:${col(ios)},{col(sc)}{i + 2})']
                                         for i, s in enumerate(STATUS_VALUES)]
    # RESULT_HEADER 순서. 결과 칸은 캡처 그림 두 장이 나란히 들어갈 너비(basic/apps-script/캡처넣기.gs 의 그림 너비 200)
    widths = [70, 100, 100, 100, 70, 300, 80, 60, 260, 420, 60, 260, 420, 220]
    rng = lambda r0, r1, c0, c1: {'sheetId': sheet_id, 'startRowIndex': r0, 'endRowIndex': r1, 'startColumnIndex': c0, 'endColumnIndex': c1}
    width = lambda c0, c1, px: {'updateDimensionProperties': {'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': c0, 'endIndex': c1},
                                                             'properties': {'pixelSize': px}, 'fields': 'pixelSize'}}
    status_rule = {'condition': {'type': 'ONE_OF_LIST', 'values': [{'userEnteredValue': s} for s in STATUS_VALUES]},
                   'strict': True, 'showCustomUi': True}
    color = {'Pass': (0.85, 0.94, 0.85), 'Fail': (0.98, 0.83, 0.83), 'Block': (0.99, 0.91, 0.78), 'Check': (1.0, 0.96, 0.75)}
    requests = [
        {'repeatCell': {'range': rng(0, n + 50, 0, ncol), 'cell': {'userEnteredFormat': {'wrapStrategy': 'WRAP', 'verticalAlignment': 'TOP',
                        'textFormat': {'fontFamily': 'Arial', 'fontSize': 10}}},
                        'fields': 'userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment,userEnteredFormat.textFormat.fontFamily,userEnteredFormat.textFormat.fontSize'}},
        {'repeatCell': {'range': rng(0, 1, 0, ncol), 'cell': {'userEnteredFormat': {'textFormat': {'bold': True, 'fontFamily': 'Arial', 'fontSize': 10},
                        'backgroundColorStyle': {'rgbColor': {'red': 0.85, 'green': 0.88, 'blue': 0.93}}}},
                        'fields': 'userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColorStyle'}},
        {'repeatCell': {'range': rng(0, 1, sc, sc + 3), 'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}}, 'fields': 'userEnteredFormat.textFormat.bold'}},
    ] + [width(i, i + 1, px) for i, px in enumerate(widths)] + [
        {'setDataValidation': {'range': rng(1, n + 50, aos, aos + 1), 'rule': status_rule}},
        {'setDataValidation': {'range': rng(1, n + 50, ios, ios + 1), 'rule': status_rule}},
    ]
    for s, (r, g, b) in color.items():
        requests.append({'addConditionalFormatRule': {'rule': {'ranges': [rng(1, n + 50, aos, aos + 1), rng(1, n + 50, ios, ios + 1)],
                         'booleanRule': {'condition': {'type': 'TEXT_EQ', 'values': [{'userEnteredValue': s}]},
                                         'format': {'backgroundColorStyle': {'rgbColor': {'red': r, 'green': g, 'blue': b}}}}}, 'index': 0}})
    return {'tab': tab, 'values': {'range': f'{quote_tab(tab)}!A1:{col(ncol - 1)}{n}', 'values': values},
            'summary': {'range': f'{quote_tab(tab)}!{col(sc)}1:{col(sc + 2)}{len(summary)}', 'values': summary},
            'requests': requests}


def add_tab_request(version, rows):
    return {'addSheet': {'properties': {'title': str(version), 'gridProperties': {'rowCount': rows + 60, 'columnCount': 18,
                                                                                    'frozenRowCount': 1, 'frozenColumnCount': 1}}}}


def capture_folder(info, version):
    """버전 탭의 캡처 폴더 — {tab, id, parent} 와 id 가 없을 때 할 일(search → 있으면 그 폴더, 없으면 create)"""
    folder = {'tab': version, 'id': (info.get('captureFolders') or {}).get(version, ''), 'parent': info.get('captureFolderId', '')}
    if not folder['id']:
        name = version.replace('\\', '\\\\').replace("'", "\\'")
        folder['search'] = (f"parentId = '{folder['parent']}' and title = '{name}' "
                            "and mimeType = 'application/vnd.google-apps.folder' and trashed = false")
        folder['todo'] = (f'먼저 Google Drive search_files 로 search 의 질의를 찾는다. 결과가 있으면 그 폴더 id 를 쓴다'
                          f'(여럿이면 만든 시각이 가장 이른 것). 없을 때만 캡처 폴더({folder["parent"]}) 아래에 「{version}」 폴더를 만든다'
                          f'(create_file, application/vnd.google-apps.folder). 쓴 id 는 basic/sheet.json 의 captureFolders["{version}"] 에 적는다')
    return folder


def load_tcs():
    if not os.path.exists(TC_FILE):
        raise OSError(f'TC 사본이 없다: {TC_FILE} — QA 앱 「기본 기능」 탭에서 「시트에서 다시 읽기」를 먼저 한다')
    return qc.load_json(TC_FILE).get('tcs', [])


def emit(obj, save=None):
    """결과 JSON 을 출력한다. save 를 주면 파일에 쓰고 요약만 출력한다 — 179행 탭처럼 출력이 길면
    셸 리다이렉트(>)나 python3 -c 로 살펴보지 않고 이 파일을 Read 로 읽게 한다(앱 안 Claude 의 허용 목록 밖 명령이 줄어든다)"""
    if not save:
        print(json.dumps(obj, ensure_ascii=False))
        return
    os.makedirs(os.path.dirname(os.path.abspath(save)), exist_ok=True)
    with open(save, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write('\n')
    summary = {}
    for k, v in obj.items():
        if isinstance(v, list):
            summary[k] = f'{len(v)}개'
        elif isinstance(v, dict):
            summary[k] = {kk: (f'{len(vv)}개' if isinstance(vv, list) else vv) for kk, vv in v.items()}
        else:
            summary[k] = v
    print(json.dumps({'saved': save, 'summary': summary}, ensure_ascii=False))


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
    p.add_argument('--save', help='결과를 이 파일에 쓰고 요약만 출력한다(출력이 길 때)')
    p = sub.add_parser('update')
    p.add_argument('--run', action='append', required=True)
    p.add_argument('--ids', required=True)
    p.add_argument('--cols', required=True)
    p.add_argument('--version')
    p.add_argument('--sheet-id', type=int, help='버전 탭 sheetId — 주면 캡처 링크 칸의 링크 서식 요청(linkRequests)을 만든다')
    p.add_argument('--save', help='결과를 이 파일에 쓰고 요약만 출력한다(출력이 길 때)')
    p = sub.add_parser('rows')
    p.add_argument('--run', required=True)
    p = sub.add_parser('shots')
    p.add_argument('--run', required=True)
    p = sub.add_parser('upload')
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
            emit(out, a.save)
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
            links = plan.pop('links')
            if a.sheet_id is not None:
                # 캡처 링크가 든 칸 — updates 를 쓴 뒤 이 요청을 update_spreadsheet 로 보내 링크를 눌리게 한다
                plan['linkRequests'] = link_requests(a.sheet_id, links)
            elif links:
                plan['note'] = '캡처 링크 칸이 있다 — --sheet-id 를 주면 링크 서식 요청(linkRequests)도 만든다'
            plan.update({'ok': True, 'spreadsheetId': info.get('spreadsheetId'), 'tab': str(version)})
            emit(plan, a.save)
        elif a.cmd == 'shots':
            meta, files = shot_entries(a.run)
            # 올릴 폴더 — 캡처 폴더 아래 버전 탭 이름의 폴더. id 를 모르면 먼저 찾고(다른 사람·다른 컴퓨터가 이미 만들었을 수 있다),
            # 없을 때만 만든다. 찾았거나 만든 id 는 sheet.json captureFolders 에 적는다
            version = str(meta.get('version', ''))
            folder = capture_folder(info, version)
            print(json.dumps({'ok': True, 'run': a.run, 'folder': folder, 'driveFile': os.path.join(a.run, DRIVE_FILE), 'files': files},
                             ensure_ascii=False, indent=1))
        elif a.cmd == 'upload':
            base = capture_dir(info)
            if not base:
                print(json.dumps({'ok': False, 'error': 'Drive 데스크톱의 캡처 폴더가 보이지 않는다 — Google Drive 앱을 설치·로그인하고 공유 드라이브 「QA」를 볼 수 있어야 한다'
                                  f'(찾는 경로: …/{info.get("captureDrivePath", "(sheet.json 에 captureDrivePath 없음)")}). 앱의 「준비」 탭을 본다'}, ensure_ascii=False))
                return 4
            res = upload_run(a.run, base)
            print(json.dumps(res, ensure_ascii=False, indent=1))
            return 0 if res['ok'] else 3
        elif a.cmd == 'rows':
            platform, rows = result_rows(a.run)
            print(json.dumps({'platform': platform, 'version': run_meta(a.run).get('version'), 'rows': rows}, ensure_ascii=False))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))
        return 4
    return 0


if __name__ == '__main__':
    sys.exit(main())
