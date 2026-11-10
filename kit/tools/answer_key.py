#!/usr/bin/env python3
"""정답지(사람이 맞다고 승인한 화면) 관리.

  python3 tools/answer_key.py approve runs/<run> [--case TC-01,TC-02] [--checkpoint NAME] --by <승인자> [--note ...]
  python3 tools/answer_key.py list [--suite NAME]
  python3 tools/answer_key.py drop <suite> <platform> <case> [--checkpoint NAME]

정답지는 answers/<suite>/<platform>/<case>/<checkpoint>.png 와 .json(글자 목록·마스크·화면 좌표·빌드 정보).
**사람이 실행 결과 캡처를 보고 「맞다」고 한 체크포인트만** 승인한다. Claude 가 스스로 승인하지 않는다.
- 승인할 수 있는 체크포인트: expect 를 통과한 것(FAIL·ERROR 는 거부)
- 이미 정답지가 있으면 덮어쓰고 이전 것은 answers/.history/ 로 옮긴다
exit: 0 성공, 2 사용법, 4 승인할 것이 없음
"""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_common as qc  # noqa: E402


def approve(run_dir, cases, checkpoint, by, note):
    results = qc.load_json(os.path.join(run_dir, 'results.json'))
    done, refused = [], []
    for c in results['cases']:
        if cases and c['id'] not in cases:
            continue
        for cp in c.get('checkpoints', []):
            if checkpoint and cp['name'] != checkpoint:
                continue
            if not cp.get('tree'):   # 조건 기기가 아니라 판정하지 않은 줄 — 화면을 남기지 않았다
                continue
            if not all(x['ok'] for x in cp.get('checks', [])):
                refused.append(f'{c["id"]}/{cp["name"]}: expect 실패 — 정답지로 쓸 수 없다')
                continue
            dump = qc.load_json(cp['tree'])
            dest = os.path.join(qc.ANSWERS, results['suite'], results['platform'], c['id'])
            png, js = os.path.join(dest, f'{cp["name"]}.png'), os.path.join(dest, f'{cp["name"]}.json')
            if os.path.exists(js):
                hist = os.path.join(qc.ANSWERS, '.history', results['suite'], results['platform'], c['id'],
                                    time.strftime('%Y%m%d-%H%M%S'))
                os.makedirs(hist, exist_ok=True)
                for p in (png, js):
                    if os.path.exists(p):
                        shutil.move(p, hist)
            os.makedirs(dest, exist_ok=True)
            if cp.get('shot'):
                shutil.copy2(cp['shot'], png)
            qc.save_json(js, {
                'suite': results['suite'], 'platform': results['platform'], 'case': c['id'], 'checkpoint': cp['name'],
                'scene': dump['scene'], 'geometry': dump['geometry'], 'imageSize': dump['imageSize'],
                'texts': dump['texts'], 'masks': dump['masks'],
                'approved': {'by': by, 'at': time.strftime('%Y-%m-%d %H:%M'), 'run': os.path.abspath(run_dir),
                             'device': results.get('device', ''), 'note': note or ''},
            })
            done.append(f'{c["id"]}/{cp["name"]}')
    print(json.dumps({'ok': bool(done), 'approved': done, 'refused': refused}, ensure_ascii=False, indent=1))
    return 0 if done else 4


def list_answers(suite=None):
    rows = []
    if os.path.isdir(qc.ANSWERS):
        for s in sorted(os.listdir(qc.ANSWERS)):
            if s.startswith('.') or (suite and s != suite) or not os.path.isdir(os.path.join(qc.ANSWERS, s)):
                continue
            for p in sorted(os.listdir(os.path.join(qc.ANSWERS, s))):
                pdir = os.path.join(qc.ANSWERS, s, p)
                if not os.path.isdir(pdir):
                    continue
                for c in sorted(os.listdir(pdir)):
                    for f in sorted(os.listdir(os.path.join(pdir, c))):
                        if f.endswith('.json'):
                            meta = qc.load_json(os.path.join(pdir, c, f))
                            rows.append({'suite': s, 'platform': p, 'case': c, 'checkpoint': f[:-5],
                                         'approved': meta.get('approved', {})})
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


def drop(suite, platform, case, checkpoint):
    d = os.path.join(qc.ANSWERS, suite, platform, case)
    if not os.path.isdir(d):
        print(json.dumps({'ok': False, 'error': f'없음 {d}'}, ensure_ascii=False))
        return 4
    hist = os.path.join(qc.ANSWERS, '.history', suite, platform, case, time.strftime('%Y%m%d-%H%M%S') + '-dropped')
    os.makedirs(hist, exist_ok=True)
    moved = []
    for f in os.listdir(d):
        if not checkpoint or f.rsplit('.', 1)[0] == checkpoint:
            shutil.move(os.path.join(d, f), hist)
            moved.append(f)
    print(json.dumps({'ok': bool(moved), 'movedTo': hist, 'files': moved}, ensure_ascii=False))
    return 0 if moved else 4


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')
    p = sub.add_parser('approve')
    p.add_argument('run')
    p.add_argument('--case')
    p.add_argument('--checkpoint')
    p.add_argument('--by', required=True, help='승인한 사람(이름 또는 역할)')
    p.add_argument('--note')
    p = sub.add_parser('list')
    p.add_argument('--suite')
    p = sub.add_parser('drop')
    p.add_argument('suite')
    p.add_argument('platform')
    p.add_argument('case')
    p.add_argument('--checkpoint')
    a = ap.parse_args()
    if a.cmd == 'approve':
        return approve(a.run, set(a.case.split(',')) if a.case else None, a.checkpoint, a.by, a.note)
    if a.cmd == 'list':
        return list_answers(a.suite)
    if a.cmd == 'drop':
        return drop(a.suite, a.platform, a.case, a.checkpoint)
    ap.print_help(sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
