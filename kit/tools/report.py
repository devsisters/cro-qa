#!/usr/bin/env python3
"""실행 결과를 리포트로 묶는다.

  python3 tools/report.py runs/<run-ios> runs/<run-aos> [--out DIR]
  python3 tools/report.py --latest <suite>        # 그 묶음의 플랫폼별 최신 실행을 묶는다

출력(기본 runs/report-<suite>-<시각>/)
  report.md    사람이 읽는 보고서 — 요약 표, 결함 의심·확인 필요·실패 상세(근거 캡처 경로), 자동화하지 않은 케이스
  results.csv  시트에 붙여 넣을 표(케이스 id · 시트 행 · 제목 · 플랫폼별 판정 · 비고). UTF-8 BOM(엑셀·구글 시트 호환)
  results.tsv  같은 내용을 탭 구분으로 — 시트 칸에 바로 붙여 넣기 좋다
  sheet-update.json  원본 시트의 결과 칸(AOS·iOS)과 comment 에 쓸 값(케이스 파일에 layout·sheetTab·statusMap 이 있을 때)
판정 표기: PASS 통과 · FAIL 기대와 다름(결함 의심) · REVIEW 정답지와 차이(아직 판정 전) · UNSURE 판정 모델이 확신 못 함(사람 확인)
          · ERROR 진행 실패(화면 이동·연결) · NOT_RUN 돌리지 않음(이유 표기)
exit: 0 성공, 2 사용법
"""
import argparse
import csv
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_common as qc  # noqa: E402

LABEL = {'PASS': '통과', 'FAIL': '실패', 'REVIEW': '확인 필요', 'UNSURE': '확인 필요', 'HUMAN': '사람 확인', 'ERROR': '진행 실패',
         'NOT_RUN': '미실행'}


def latest_runs(suite):
    best = {}
    if not os.path.isdir(qc.RUNS):
        return []
    for d in sorted(os.listdir(qc.RUNS)):
        p = os.path.join(qc.RUNS, d, 'results.json')
        if d.startswith(suite + '-') and os.path.exists(p):
            r = qc.load_json(p)
            if r.get('suite') == suite:
                best[r['platform']] = os.path.join(qc.RUNS, d)
    return [best[k] for k in sorted(best)]


def note_for(c):
    if c['verdict'] == 'NOT_RUN':
        return c.get('reason', '')
    if c.get('error'):
        e = c['error']
        return f'{e["kind"]} at {e["step"]}: {e["detail"]}'
    notes = [c['reason']] if c.get('reason') else []
    for cp in c.get('checkpoints', []):
        bad = [x['check'] + f' ({x["detail"]})' for x in cp.get('checks', []) if not x['ok']]
        if bad:
            notes.append(f'{cp["name"]}: ' + '; '.join(bad))
        j = cp.get('judged')
        if j and j['verdict'] != 'ALLOWED':
            notes.append(f'{cp["name"]}: 판정 {j["verdict"]}/{j["category"]} — {j["reason"]}')
        if cp.get('verdict') == 'REVIEW':
            notes.append(f'{cp["name"]}: 정답지와 차이 — 판정 전')
        if cp.get('verdict') == 'HUMAN':
            notes.append(f'{cp["name"]}: 사람 확인 — {cp.get("human") or ""}')
    return ' / '.join(notes)


def write_sheet_update(runs, rows, platforms, meta, suite_cases_file, out):
    """시트에 다시 쓸 칸 목록(sheet-update.json). 케이스 파일에 layout·sheetTab·statusMap 이 있을 때만 만든다.
    쓰는 것: 플랫폼 결과 칸(NOT_RUN 은 쓰지 않는다 — 사람이 직접 볼 케이스로 남긴다), comment 칸에 덧붙일 한 줄.
    comment 는 덮어쓰지 않는다 — 쓰는 쪽이 기존 값을 읽고 줄을 덧붙인다."""
    if not suite_cases_file or not os.path.exists(suite_cases_file):
        return None
    suite = qc.load_json(suite_cases_file)
    layout, tab, smap = suite.get('layout'), suite.get('sheetTab'), suite.get('statusMap')
    if not (layout and tab and smap):
        return None
    cols = layout.get('resultColumns', {})
    day = time.strftime('%m/%d')
    cells, comments = [], []
    for r in rows:
        row = r['row']
        if not row:
            continue
        for p in platforms:
            v = r['verdicts'].get(p)
            col = cols.get(p)
            if col and v in smap:
                cells.append({'range': f"'{tab}'!{col}{row}", 'value': smap[v], 'case': r['id'], 'platform': p})
        if r['notes'] and cols.get('comment'):
            comments.append({'range': f"'{tab}'!{cols['comment']}{row}", 'append': f'[자동 {day}] {r["notes"]}'[:300], 'case': r['id']})
    # 「자동화」 탭(케이스별 자동화 구분·근거)이 있으면 근거·마지막 실행 칸도 쓴다
    auto = suite.get('automationTab')
    if auto:
        stamp = time.strftime('%Y-%m-%d %H:%M')
        for r in rows:
            if not r['row'] or all(r['verdicts'].get(p) in ('', 'NOT_RUN') for p in platforms):
                continue
            ar = r['row'] + auto.get('rowOffset', 0)
            cells.append({'range': f"'{auto['name']}'!{auto['lastRun']}{ar}", 'value': stamp, 'case': r['id'], 'platform': 'all'})
            if r['notes']:
                cells.append({'range': f"'{auto['name']}'!{auto['evidence']}{ar}", 'value': r['notes'][:500], 'case': r['id'],
                              'platform': 'all'})
    data = {'sheet': suite.get('sheet', ''), 'tab': tab, 'statusMap': smap, 'cells': cells, 'commentAppends': comments,
            'how': '결과 칸은 value 로 쓴다. comment 는 기존 값을 읽고 빈 줄이 아니면 줄바꿈 뒤에 append 를 덧붙인다. '
                   'USER_ENTERED 로 쓰면 N/T 같은 값이 그대로 들어간다. 쓰고 나서 다시 읽어 확인한다'}
    qc.save_json(os.path.join(out, 'sheet-update.json'), data)
    return data


def build(run_dirs, out):
    runs = [qc.load_json(os.path.join(d, 'results.json')) | {'_dir': d} for d in run_dirs]
    suite = runs[0]['suite']
    platforms = [r['platform'] for r in runs]
    suite_cases = []
    sf = runs[0].get('suiteFile')
    if sf and os.path.exists(sf):
        suite_cases = qc.load_json(sf).get('cases', [])
    meta = {c['id']: c for c in suite_cases}
    order = [c['id'] for c in suite_cases] or []
    for r in runs:
        for c in r['cases']:
            if c['id'] not in order:
                order.append(c['id'])
    by = {(r['platform'], c['id']): c for r in runs for c in r['cases']}
    os.makedirs(out, exist_ok=True)

    rows = []
    for cid in order:
        m = meta.get(cid, {})
        title = m.get('title') or next((by[(p, cid)]['title'] for p in platforms if (p, cid) in by), '')
        verdicts = {p: by[(p, cid)]['verdict'] if (p, cid) in by else '' for p in platforms}
        per = {p: note_for(by[(p, cid)]) for p in platforms if (p, cid) in by and note_for(by[(p, cid)])}
        if len(set(per.values())) == 1 and len(per) == len(platforms) and len(platforms) > 1:
            notes = next(iter(per.values()))
        else:
            notes = ' | '.join(f'[{p}] {n}' for p, n in per.items())
        rows.append({'id': cid, 'row': m.get('sheet_row', ''), 'title': title, 'verdicts': verdicts, 'notes': notes})

    header = ['케이스', '시트 행', '제목'] + [p.upper() for p in platforms] + ['비고']
    with open(os.path.join(out, 'results.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([r['id'], r['row'], r['title']] + [LABEL.get(r['verdicts'][p], '') for p in platforms] + [r['notes']])
    with open(os.path.join(out, 'results.tsv'), 'w', encoding='utf-8') as f:
        f.write('\t'.join(header) + '\n')
        for r in rows:
            cells = [r['id'], str(r['row']), r['title']] + [LABEL.get(r['verdicts'][p], '') for p in platforms] + [r['notes']]
            f.write('\t'.join(x.replace('\t', ' ').replace('\n', ' ') for x in cells) + '\n')

    counts = {p: {} for p in platforms}
    for r in rows:
        for p in platforms:
            v = r['verdicts'][p]
            if v:
                counts[p][v] = counts[p].get(v, 0) + 1
    write_sheet_update(runs, rows, platforms, meta, suite_cases_file=sf, out=out)
    L = [f'# 자동화 테스트 결과 — {suite}', '']
    sheet = runs[0].get('sheet')
    if sheet:
        L.append(f'- 테스트 시트: {sheet}')
    for r in runs:
        L.append(f'- {r["platform"].upper()}: 시작 {r["started"]} · 끝 {r.get("finished", "(중단됨)")} · 기기 {r.get("device") or "devices.json"}'
                 f' · 결과 `{r["_dir"]}`')
    L += ['', '## 요약', '', '| 판정 | ' + ' | '.join(p.upper() for p in platforms) + ' |', '|---|' + '---|' * len(platforms)]
    for v in qc.ORDER:
        L.append(f'| {v} {LABEL[v]} | ' + ' | '.join(str(counts[p].get(v, 0)) for p in platforms) + ' |')
    cps = {p: [cp for c in r['cases'] for cp in c.get('checkpoints', [])] for p, r in zip(platforms, runs)}
    L += ['', '정답지 비교: ' + ' · '.join(
        f'{p.upper()} {sum(1 for cp in cps[p] if cp.get("baseline") not in (None, "none"))}/{len(cps[p])} 체크포인트'
        for p in platforms) + ' (나머지는 정답지가 없어 expect 조건으로만 판정했다 — 사람이 캡처를 보고 승인하면 다음부터 비교된다)']
    L += ['', '## 케이스별', '', '| 케이스 | 제목 | ' + ' | '.join(p.upper() for p in platforms) + ' |',
          '|---|---|' + '---|' * len(platforms)]
    for r in rows:
        L.append(f'| {r["id"]} | {r["title"]} | ' + ' | '.join(r['verdicts'][p] or '-' for p in platforms) + ' |')

    def section(title, pick):
        items = [(p, by[(p, cid)]) for cid in order for p in platforms if (p, cid) in by and pick(by[(p, cid)])]
        if not items:
            return
        L.extend(['', f'## {title}', ''])
        for p, c in items:
            L.append(f'### {c["id"]} [{p.upper()}] {c.get("title", "")}')
            if c.get('error'):
                e = c['error']
                L.append(f'- {e["kind"]} at `{e["step"]}`: {e["detail"]}')
                if e.get('shot'):
                    L.append(f'- 실패 캡처: `{e["shot"]}`')
            for cp in c.get('checkpoints', []):
                if cp.get('shotError'):
                    L.append(f'- 체크포인트 `{cp["name"]}` 캡처 못 가져옴: {cp["shotError"]}')
                if cp['verdict'] == 'PASS':
                    continue
                L.append(f'- 체크포인트 `{cp["name"]}` → **{cp["verdict"]}** (scene {cp.get("scene")})')
                for x in cp.get('checks', []):
                    if not x['ok']:
                        L.append(f'  - 기대 불일치: {x["check"]} — {x["detail"]}')
                d = cp.get('diff') or {}
                if d.get('texts'):
                    L.append(f'  - 글자 차이: 없어짐 {d["texts"]["missing"][:8]} · 생김 {d["texts"]["added"][:8]}')
                if d.get('image'):
                    L.append(f'  - 화면 차이 {d["image"]["changed"] * 100:.1f}% · 큰 덩어리 {len(d["image"].get("significant", []))}개')
                    for cr in d['image'].get('crops', [])[:3]:
                        L.append(f'    - 정답 `{cr["expected"]}` · 실제 `{cr["actual"]}`')
                j = cp.get('judged')
                if j:
                    L.append(f'  - 판정({j["by"]}): {j["verdict"]} / {j["category"]} — {j["reason"]}')
                if cp.get('shot'):
                    L.append(f'  - 캡처: `{cp["shot"]}`')
            L.append('')

    section('실패 — 기대와 다름(결함 의심)', lambda c: c['verdict'] == 'FAIL')
    section('확인 필요 — 정답지와 차이, 판정 미완 또는 불확실', lambda c: c['verdict'] in ('REVIEW', 'UNSURE'))
    section('사람 확인 — 조건은 통과, 캡처를 보고 판단', lambda c: c['verdict'] == 'HUMAN')
    section('진행 실패 — 화면 이동·연결', lambda c: c['verdict'] == 'ERROR')
    section('캡처 못 가져옴 — 판정은 위와 같고 화면 비교가 빠졌다',
            lambda c: c['verdict'] in ('PASS', 'NOT_RUN') and any(cp.get('shotError') for cp in c.get('checkpoints', [])))
    nr = [(cid, by[(p, cid)].get('reason', '')) for cid in order for p in platforms[:1]
          if (p, cid) in by and by[(p, cid)]['verdict'] == 'NOT_RUN']
    if nr:
        L += ['', '## 미실행 케이스', '', '| 케이스 | 이유 |', '|---|---|'] + [f'| {cid} | {why} |' for cid, why in nr]
    L += ['', '---', '판정 기준: expect(트리 조건) → 정답지 비교(숫자 마스크) → 차이만 낮은 모델 판정. '
          '「통과」는 자동 판정 결과이며 사람 확인을 대신하지 않는다.']
    with open(os.path.join(out, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs', nargs='*')
    ap.add_argument('--latest')
    ap.add_argument('--out')
    a = ap.parse_args()
    runs = latest_runs(a.latest) if a.latest else a.runs
    if not runs:
        ap.print_usage(sys.stderr)
        return 2
    suite = qc.load_json(os.path.join(runs[0], 'results.json'))['suite']
    out = a.out or os.path.join(qc.RUNS, f'report-{suite}-{time.strftime("%Y%m%d-%H%M%S")}')
    build(runs, out)
    print(f'{{"ok": true, "report": "{os.path.join(out, "report.md")}", "csv": "{os.path.join(out, "results.csv")}"}}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
