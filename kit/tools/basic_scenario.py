#!/usr/bin/env python3
"""기본 기능 시나리오 — 대분류 하나가 시나리오 하나다. basic/sheet.json 의 splitBySub 에 든 대분류(모드리스트)만 중분류마다 하나다.

  python3 tools/basic_scenario.py list                                 # 묶음별 TC 수·시나리오 유무
  python3 tools/basic_scenario.py new "<대분류>" ["<중분류>"] [--by 이름] # 빈 시나리오(TC 구간만 있는 것)를 만든다. 중분류는 나누는 대분류일 때만
  python3 tools/basic_scenario.py check <시나리오.json> [...]           # 형식 검사(기기 없음)

위치: basic/scenarios/<대분류>.json, 나누는 대분류는 basic/scenarios/<대분류>/<중분류>.json — 이름의 / \\ : 는 _ 로 바꾼다. 형식은 basic/README.md 「시나리오 파일」.
시나리오 안은 TC 구간(segments)으로 나뉜다. 진입(entry)은 첫 구간 앞에서 한 번만 하고, 다음 구간은 그 화면에서 이어 간다.
구간 하나가 진행에 실패하면 그 TC 만 Block 이 되고, 다음 구간은 시작 화면부터 다시 들어간다(case_runner 의 resume).
exit: 0 · 2 형식 오류 · 4 파일을 읽지 못함
"""
import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_common as qc  # noqa: E402

REPO = os.path.dirname(qc.KIT)
BASIC = os.path.join(REPO, 'basic')
SCEN_DIR = os.path.join(BASIC, 'scenarios')
TC_FILE = os.path.join(BASIC, 'tc.json')
SHEET_FILE = os.path.join(BASIC, 'sheet.json')


def split_areas():
    """중분류마다 시나리오를 나누는 대분류 — 기본은 모드리스트(TC 99개라 하나로는 너무 크다)"""
    info = qc.load_json(SHEET_FILE) if os.path.exists(SHEET_FILE) else {}
    return set(info.get('splitBySub', ['모드리스트']))


def safe(name):
    return re.sub(r'[/\\:]', '_', str(name)).strip() or '_'


def scenario_path(area, sub='', root=None):
    if sub:
        return os.path.join(root or SCEN_DIR, safe(area), safe(sub) + '.json')
    return os.path.join(root or SCEN_DIR, safe(area) + '.json')


def scenario_name(area, sub=''):
    return f'{area} › {sub}' if sub else area


def load_tcs(path=None):
    path = path or TC_FILE
    return qc.load_json(path).get('tcs', []) if os.path.exists(path) else []


def groups(tcs, split=None):
    """TC 목록 → [(대분류, 중분류 또는 '', [TC])] — 시트 순서대로. 나누지 않는 대분류는 중분류가 ''"""
    split = split_areas() if split is None else split
    order, by = [], {}
    for t in tcs:
        k = (t.get('area', ''), t.get('sub', '') if t.get('area', '') in split else '')
        if k not in by:
            by[k] = []
            order.append(k)
        by[k].append(t)
    return [(a, s, by[(a, s)]) for a, s in order]


def skeleton(area, sub, tcs, by=''):
    return {'area': area, 'sub': sub, 'start': 'lobby', 'setup': [], 'entry': [],
            'segments': [{'tc': t['id'], 'steps': []} for t in tcs],
            'notes': [], 'createdBy': by, 'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%S')}


def runnable(seg):
    return bool(seg.get('steps'))


def build_cases(data, path, tcs_by_id=None):
    """시나리오 하나 → case_runner 케이스 목록(TC 구간마다 하나).
    첫 구간: start → setup(마카롱 상태 등) → entry(이 화면까지 들어가기) → 구간 단계.
    다음 구간: 앞 구간이 끝난 화면에서 이어 간다(start: here). 앞 구간이 진행에 실패했으면 resume 으로 start → setup → entry 부터.
    fresh: true 인 구간은 앞 구간과 상관없이 처음부터 들어간다."""
    tcs_by_id = tcs_by_id or {}
    start = data.get('start', 'lobby')
    head = list(data.get('setup') or []) + list(data.get('entry') or [])
    answers = os.path.splitext(os.path.abspath(path))[0]
    cases, entered = [], False
    for seg in data.get('segments') or []:
        tc = tcs_by_id.get(seg.get('tc'), {})
        case = {'id': seg.get('tc'), 'title': f'{scenario_name(data.get("area", ""), data.get("sub", ""))} · {seg.get("tc")}',
                'answersDir': answers, 'sheet': {'expected': tc.get('check', '')}}
        if not runnable(seg):
            case.update({'auto': False, 'reason': seg.get('reason') or '아직 자동화 단계가 없다', 'steps': []})
        elif seg.get('fresh') or not entered or start == 'here':
            case.update({'auto': True, 'start': start, 'steps': head + list(seg['steps'])})
            entered = True
        else:
            case.update({'auto': True, 'start': 'here', 'steps': list(seg['steps']), 'resume': {'start': start, 'steps': head}})
        for k in ('spends', 'partial'):
            if seg.get(k):
                case[k] = seg[k]
        cases.append(case)
    return cases


def build_suite(files, tcs=None):
    tcs_by_id = {t['id']: t for t in (tcs if tcs is not None else load_tcs())}
    cases, server, time_ok = [], '', False
    for path in files:
        data = qc.load_json(path)
        cases += build_cases(data, path, tcs_by_id)
        server = server or data.get('server', '')
        time_ok = time_ok or bool(data.get('time_ok'))
    suite = {'suite': 'basic', 'kind': 'outgame', 'cases': cases}
    if server:
        suite['server'] = server
    if time_ok:
        suite['time_ok'] = True
    return suite


def check(data, path, tcs_by_id=None):
    errs = []
    where = os.path.relpath(path, REPO) if os.path.isabs(path) else path
    if not data.get('area'):
        errs.append(f'{where}: area 가 필요')
    ids = [s.get('tc') for s in data.get('segments') or []]
    if not ids:
        errs.append(f'{where}: segments 가 비어 있다')
    if len(set(ids)) != len(ids):
        errs.append(f'{where}: 같은 TC 구간이 두 번 있다')
    if tcs_by_id:
        for i in ids:
            t = tcs_by_id.get(i)
            if not t:
                errs.append(f'{where}: {i} 가 TC 탭에 없다')
            elif t.get('area') != data.get('area') or (data.get('sub') and t.get('sub') != data.get('sub')):
                errs.append(f'{where}: {i} 는 「{scenario_name(t.get("area"), t.get("sub"))}」 TC 다')
    return errs


def info_for(files, tcs=None):
    """리포트용 TC 정보 — 케이스 id(TC) → 시나리오 이름·TC 문구"""
    tcs_by_id = {t['id']: t for t in (tcs if tcs is not None else load_tcs())}
    out = {}
    for path in files:
        data = qc.load_json(path)
        name = scenario_name(data.get('area', ''), data.get('sub', ''))
        for seg in data.get('segments') or []:
            t = tcs_by_id.get(seg.get('tc'), {})
            out[seg.get('tc')] = {'tab': name, 'no': seg.get('tc'), 'section': data.get('area', ''), 'path': name,
                                  'expected': t.get('check', ''), 'judge': t.get('judge', ''),
                                  'file': os.path.relpath(os.path.abspath(path), REPO), 'labels': {}}
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list')
    p = sub.add_parser('new')
    p.add_argument('area')
    p.add_argument('sub', nargs='?', default='')
    p.add_argument('--by', default='')
    p = sub.add_parser('check')
    p.add_argument('files', nargs='+')
    a = ap.parse_args()
    tcs = load_tcs()
    by_id = {t['id']: t for t in tcs}
    if a.cmd == 'list':
        rows = []
        for area, s, ts in groups(tcs):
            path = scenario_path(area, s)
            data = qc.load_json(path) if os.path.exists(path) else None
            auto = [x['tc'] for x in (data or {}).get('segments', []) if runnable(x)]
            rows.append({'area': area, 'sub': s, 'name': scenario_name(area, s), 'tcs': [t['id'] for t in ts], 'file': os.path.relpath(path, REPO) if data else '',
                         'auto': auto})
        print(json.dumps({'ok': True, 'groups': rows}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == 'new':
        split = a.area in split_areas()
        if split != bool(a.sub):
            print(json.dumps({'ok': False, 'error': f'「{a.area}」 는 ' + ('중분류마다 나눈다 — 중분류를 준다' if split else '대분류 하나가 시나리오 하나다 — 중분류를 주지 않는다')},
                             ensure_ascii=False))
            return 2
        ts = [t for t in tcs if t.get('area') == a.area and (not a.sub or t.get('sub') == a.sub)]
        if not ts:
            print(json.dumps({'ok': False, 'error': f'「{scenario_name(a.area, a.sub)}」 TC 가 없다'}, ensure_ascii=False))
            return 2
        path = scenario_path(a.area, a.sub)
        if os.path.exists(path):
            print(json.dumps({'ok': False, 'error': f'이미 있다: {os.path.relpath(path, REPO)}'}, ensure_ascii=False))
            return 2
        os.makedirs(os.path.dirname(path), exist_ok=True)
        qc.save_json(path, skeleton(a.area, a.sub, ts, a.by))
        print(json.dumps({'ok': True, 'file': os.path.relpath(path, REPO), 'tcs': [t['id'] for t in ts]}, ensure_ascii=False))
        return 0
    errs = []
    for f in a.files:
        try:
            errs += check(qc.load_json(f), f, by_id)
        except (OSError, ValueError) as e:
            errs.append(f'{f}: 읽지 못했다 — {e}')
    if not errs:
        import case_runner
        errs = case_runner.validate(build_suite(a.files, tcs))
    print(json.dumps({'ok': not errs, 'errors': errs}, ensure_ascii=False, indent=1))
    return 0 if not errs else 2


if __name__ == '__main__':
    sys.exit(main())
