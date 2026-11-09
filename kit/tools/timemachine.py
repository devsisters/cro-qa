#!/usr/bin/env python3
"""dev 서버(gb-*) 시간 조회·변경 — 사내 타임머신(#cro_timemachine 봇과 같은 기능)을 키트 Chrome 으로 부른다.

  python3 tools/timemachine.py get <서버>
  python3 tools/timemachine.py set <서버> "2026-11-14 00:00" | 2026-11-14 | +1d | +2h30m   [--reason "케이스 TC-047"]

- 서버 이름은 프리셋 이름과 같다(예: gb-qa-126). gb- 로 시작하는 dev 서버만 받는다
- **서버 시간은 그 서버를 쓰는 모든 사람에게 바뀐다.** 다른 사람과 같이 쓰는 서버(gb-qa-* 공용)는 사람에게 먼저 묻는다.
  케이스 파일의 `server`·`time_ok` 와 실행기의 --allow-time 이 모두 있어야 실행기가 바꾼다
- 시간을 과거로 되돌리면 서버 에러가 나는 경우가 있다(채널 기록). 되돌리기는 자동으로 하지 않는다 — 필요하면 사람에게 묻는다
- 바꿀 때마다 workspace/timemachine-log.jsonl 에 전후 시간을 남긴다
- 키트 Chrome(`node tools/web/chrome_cdp.mjs launch`)이 떠 있고 stove 에 로그인돼 있어야 한다
- 슬랙으로 할 때(같은 기능): #cro_timemachine 에 `!t <서버>` 조회, `!s <서버> 2026-11-14 00:00` 또는 `!s <서버> +1d 00:12:01`
exit: 0 성공, 2 사용법·서버 이름 거부, 3 브라우저·로그인 문제, 6 바꾼 뒤 확인 실패
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_common as qc  # noqa: E402

CDP = os.path.join(HERE, 'web', 'chrome_cdp.mjs')
BASE = 'https://stove.devspie.com/app/timemachine'
SERVER = re.compile(r'^gb-[a-z0-9-]+$')
KST = dt.timezone(dt.timedelta(hours=9))
STAMP = re.compile(r'(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})')
DELTA = re.compile(r'([+-])((?:\d+[wdhms])+)$')


def page(url):
    r = subprocess.run(['node', CDP, 'page-text', url], capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
    except ValueError:
        data = {'ok': False, 'error': (r.stderr or r.stdout)[-300:]}
    return r.returncode, data


def read_time(text):
    """응답 → 'YYYY-MM-DD HH:MM:SS'(KST). API 는 {"timestamp": 초} JSON 을 준다(2026-11-04 실측)."""
    try:
        ts = json.loads(text or '').get('timestamp')
        if isinstance(ts, (int, float)):
            return dt.datetime.fromtimestamp(ts, KST).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        pass
    m = STAMP.findall(text or '')
    return m[-1].replace('T', ' ') if m else None


def get(server):
    code, data = page(f'{BASE}/get?name={urllib.parse.quote(server)}')
    if code:
        return None, data
    return read_time(data.get('text')), data


def target_from(spec, now):
    """spec → (timestamp 또는 None, delta 초 또는 None)"""
    m = DELTA.match(spec.replace(' ', ''))
    if m:
        unit = {'w': 604800, 'd': 86400, 'h': 3600, 'm': 60, 's': 1}
        sec = sum(int(n) * unit[u] for n, u in re.findall(r'(\d+)([wdhms])', m.group(2)))
        return None, sec if m.group(1) == '+' else -sec
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y%m%d'):
        try:
            return int(dt.datetime.strptime(spec, fmt).replace(tzinfo=KST).timestamp()), None
        except ValueError:
            pass
    raise ValueError(f'시간 형식을 모르겠다: {spec!r} (예: "2026-11-14 00:00", 2026-11-14, +1d, +2h30m)')


def log(entry):
    path = os.path.join(qc.WORKSPACE, 'timemachine-log.jsonl')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def set_time(server, spec, reason=''):
    ts, delta = target_from(spec, time.time())
    before, data = get(server)
    if before is None:
        return 3, {'ok': False, 'stage': 'get', **data}
    q = {'name': server, **({'timestamp': ts} if ts is not None else {'timestamp_delta': delta})}
    code, res = page(f'{BASE}/set?{urllib.parse.urlencode(q)}')
    if code:
        return 3, {'ok': False, 'stage': 'set', **res}
    time.sleep(2)
    after, _ = get(server)
    entry = {'at': dt.datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'), 'server': server, 'spec': spec, 'before': before,
             'after': after, 'response': (res.get('text') or '')[:300], 'reason': reason}
    log(entry)
    ok = after is not None and after != before
    if ok and ts is not None:
        got = dt.datetime.strptime(after, '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST).timestamp()
        ok = abs(got - ts) < 600
    return (0 if ok else 6), {'ok': ok, **entry}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['get', 'set'])
    ap.add_argument('server')
    ap.add_argument('when', nargs='?')
    ap.add_argument('--reason', default='')
    a = ap.parse_args()
    if not SERVER.match(a.server):
        print(json.dumps({'ok': False, 'error': 'gb- 로 시작하는 dev 서버 이름만 받는다'}, ensure_ascii=False))
        return 2
    if a.cmd == 'get':
        t, data = get(a.server)
        print(json.dumps({'ok': t is not None, 'server': a.server, 'time': t,
                          **({} if t else {'error': data.get('error') or '응답에서 시간을 찾지 못했다', 'text': (data.get('text') or '')[:300]})},
                         ensure_ascii=False))
        return 0 if t else 3
    if not a.when:
        print('set 에는 시간이 필요하다', file=sys.stderr)
        return 2
    try:
        code, res = set_time(a.server, a.when, a.reason)
    except ValueError as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(res, ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
