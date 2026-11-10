#!/usr/bin/env python3
"""마카롱 couchbase 문서의 필드 하나를 바꾼다 — 테스트 계정 상태 만들기용(2026-11-03 사용자 승인).

  python3 macaron_edit.py peek <path> --target <키트 Chrome targetId> --key member:<MID>   # 편집기 없이 조회 API 로 1초 안에 본다
  python3 macaron_edit.py get <path> --target <키트 Chrome targetId> [--out-dir DIR]
  python3 macaron_edit.py set <path> <new JSON value> --target <키트 Chrome targetId> --key member:<MID>
                          [--expect <old JSON value>] [--out-dir DIR]

<path> 는 점으로 잇는다(예: wallet.my_cookie_icing_gacha_token.amt, 배열은 숫자).
탭은 `web/chrome_cdp.mjs open "https://macaron.gb-qa-<N>.stove.devspie.com/couchbase_modifier/?bucket=gb-member&key=member%3A<MID>"` 로
미리 조회해 둔다. 순서:
  1. 편집기 전체를 받아 백업(<out-dir>/<key>-<시각>-before.json)
  2. 텍스트에서 그 값의 위치만 찾아 기대값과 비교(다르면 멈춤)
  3. 편집기의 그 범위만 바꾼다(문서 전체를 다시 쓰지 않는다 — int64 를 JS 로 왕복시키지 않는다)
  4. Save → 같은 주소를 새 탭으로 다시 조회해 「그 필드만 바뀌었는지」 Python 으로 비교
--key 와 탭의 키가 같아야 한다(엉뚱한 문서에 쓰지 않게). 서버는 dev 마카롱(gb-*)만, 계정 제한은 없다(2026-11-03 사용자 결정 — 전부 테스트 계정).
exit: 0 성공, 2 사용법, 3 도구 실패, 6 기대값 불일치, 7 저장 뒤 검증 실패
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ASIDE = os.path.join(HERE, 'web', 'chrome_cdp.mjs')
DEC = json.JSONDecoder()
WS = ' \t\n\r'


def aside(*args, env=None):
    r = subprocess.run(['node', ASIDE, *args], capture_output=True, text=True, env=env)
    try:
        data = json.loads(r.stdout) if r.stdout.strip() else {}
    except ValueError:
        data = {'raw': r.stdout[-300:]}
    return r.returncode, data, r.stderr[-300:]


def skip(s, i):
    while s[i] in WS:
        i += 1
    return i


def locate(s, path, i=0):
    """문서 텍스트 s 에서 path 값의 [start, end) 를 찾는다."""
    i = skip(s, i)
    if not path:
        return i, DEC.raw_decode(s, i)[1]
    head, rest = path[0], path[1:]
    if s[i] == '{':
        i += 1
        while True:
            i = skip(s, i)
            if s[i] == '}':
                raise KeyError(head)
            key, i = json.decoder.scanstring(s, i + 1)
            i = skip(s, i)
            assert s[i] == ':'
            i = skip(s, i + 1)
            if key == head:
                return locate(s, rest, i)
            i = skip(s, DEC.raw_decode(s, i)[1])
            if s[i] == ',':
                i += 1
    if s[i] == '[':
        want, n = int(head), 0
        i += 1
        while True:
            i = skip(s, i)
            if s[i] == ']':
                raise KeyError(head)
            if n == want:
                return locate(s, rest, i)
            i = skip(s, DEC.raw_decode(s, i)[1])
            if s[i] == ',':
                i += 1
            n += 1
    raise KeyError(head)


def get_in(doc, path):
    for p in path:
        doc = doc[int(p)] if isinstance(doc, list) else doc[p]
    return doc


def set_in(doc, path, value):
    for p in path[:-1]:
        doc = doc[int(p)] if isinstance(doc, list) else doc[p]
    last = path[-1]
    if isinstance(doc, list):
        doc[int(last)] = value
    else:
        doc[last] = value


def fetch(target, out, timeout=60):
    # 큰 문서는 탭을 연 뒤 편집기에 올라오기까지 시간이 걸린다. 비어 있으면(exit 5) 기다렸다 다시 읽는다
    end = time.time() + timeout
    while True:
        code, data, err = aside('macaron-get', target, out)
        if code == 0:
            return data, open(out, encoding='utf-8').read()
        if code != 5 or time.time() > end:
            raise SystemExit(f'macaron-get 실패({code}): {data} {err}')
        time.sleep(3)


def element_lines(text, path):
    """배열 항목 path 의 줄 범위 → (첫 줄 번호, 빼는 텍스트 시작, 끝). 항목 뒤에 쉼표가 있어야 한다(마지막 항목은 거부)."""
    start, end = locate(text, path)
    ls = text.rfind('\n', 0, start) + 1
    if text[ls:start].strip():
        raise ValueError('항목이 줄 처음에서 시작하지 않는다 — 줄 단위로 뺄 수 없다')
    i = skip(text, end)
    if text[i] != ',':
        raise ValueError('배열의 마지막 항목은 빼지 않는다(앞 항목의 쉼표가 바뀐다) — 다른 항목을 고른다')
    nl = text.find('\n', i)
    if text[i + 1:nl].strip():
        raise ValueError('쉼표 뒤에 다른 글자가 있다')
    return text.count('\n', 0, ls), ls, nl + 1


def apply_edit(a, meta, before, backup, row, row_end, removed, added, expected, stamp):
    """편집기의 [row,0)~[row_end,0) 를 removed → added 로 바꾸고 저장·확인 창 대조·재조회 비교까지 한다."""
    key = meta.get('key', '')
    code, data, err = aside('macaron-replace', a.target, '--row', str(row), '--row-end', str(row_end), '--col-start', '0',
                            '--col-end', '0', '--expect', removed, '--new', added)
    if code:
        return 3, {'ok': False, 'stage': 'replace', 'exit': code, 'result': data, 'backup': backup}
    code, data, err = aside('macaron-save', a.target)
    if code:
        return 3, {'ok': False, 'stage': 'save', 'exit': code, 'result': data, 'backup': backup}
    diff = data.get('diff') or ''
    shown = [x.strip() for x in diff.splitlines()
             if x.strip() and x.strip() not in ('Confirm changes', '...', 'CloseSave', 'Close', 'Save')]
    want = [x.strip() for x in (removed or added).splitlines() if x.strip()]
    # 줄 비교 도구는 같은 모양의 경계 줄({·}, 등)을 기준으로 블록을 한두 줄 밀어서 보여 준다 — 순서만 돌아간 같은 블록은 같은 변경이다
    rotated = len(shown) == len(want) and any(shown == want[k:] + want[:k] for k in range(len(want)))
    if not rotated:
        return 7, {'ok': False, 'stage': 'diff', 'shown': shown[:20], 'expected': want, 'backup': backup,
                   'note': '확인 창을 열어 둔 채 멈췄다. 저장되지 않았다 — 탭을 닫거나 Close'}
    diff_file = os.path.join(a.out_dir, f'{key.replace(":", "_")}-{stamp}-diff.txt')
    with open(diff_file, 'w', encoding='utf-8') as f:
        f.write(diff)
    code, data, err = aside('macaron-confirm', a.target, '--diff-file', diff_file)
    if code:
        return 3, {'ok': False, 'stage': 'confirm', 'exit': code, 'result': data, 'backup': backup}
    code, opened, err = aside('open', meta['url'])
    time.sleep(5)
    try:
        _, after = fetch(opened['targetId'], os.path.join(a.out_dir, f'{key.replace(":", "_")}-{stamp}-after.json'))
    finally:
        aside('close', opened.get('targetId', ''))
    ok = json.loads(after) == expected
    return (0 if ok else 7), {'ok': ok, 'key': key, 'backup': backup, 'onlyThisChanged': ok}


def resolve(doc, tokens):
    """'inventory.pets.@id=201800' 의 @키=값 토큰을 배열 인덱스로 바꾼다(계정마다 위치가 달라서)."""
    out, cur = [], doc
    for t in tokens:
        if t.startswith('@') and '=' in t and isinstance(cur, list):
            k, v = t[1:].split('=', 1)
            hits = [i for i, x in enumerate(cur) if isinstance(x, dict) and str(x.get(k)) == v]
            if len(hits) != 1:
                raise KeyError(f'{t}: {len(hits)}개가 맞는다(1개여야 한다)')
            t = str(hits[0])
        out.append(t)
        cur = cur[int(t)] if isinstance(cur, list) else cur[t]
    return out


def structural(a):
    """remove <배열 항목 경로>: 항목을 빼고 되돌리기용 파일(.removed.json)을 남긴다.
    insert <같은 경로> --saved <파일>: 뺀 항목을 같은 줄에 그대로 다시 넣는다."""
    if not a.key:
        print('remove·insert 에는 --key 가 필요하다', file=sys.stderr)
        return 2
    path = a.path.split('.')
    os.makedirs(a.out_dir, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    meta, before = fetch(a.target, os.path.join(a.out_dir, f'tab-{stamp}.json'))
    key = meta.get('key', '')
    if a.key != key:
        print(json.dumps({'ok': False, 'error': f'탭의 키({key})가 --key({a.key})와 다르다'}, ensure_ascii=False))
        return 2
    backup = os.path.join(a.out_dir, f'{key.replace(":", "_")}-{stamp}-before.json')
    os.replace(os.path.join(a.out_dir, f'tab-{stamp}.json'), backup)
    doc = json.loads(before)
    if a.cmd == 'remove':
        try:
            path = resolve(doc, path)
        except KeyError as e:
            if ': 0개' in str(e):
                # 이미 없다 — 원하는 상태(빠진 상태)이므로 성공으로 본다
                os.remove(backup) if os.path.exists(backup) else None
                print(json.dumps({'ok': True, 'already': True, 'path': a.path, 'note': '이미 없는 항목'}, ensure_ascii=False))
                return 0
            print(json.dumps({'ok': False, 'error': f'경로를 찾지 못했다: {e}'}, ensure_ascii=False))
            return 2
        except (IndexError, ValueError) as e:
            print(json.dumps({'ok': False, 'error': f'경로를 찾지 못했다: {e}'}, ensure_ascii=False))
            return 2
        a.path = '.'.join(path)
        item = get_in(doc, path)
        if a.max_refs and isinstance(item, dict) and 'id' in item:
            # 문서 구조에서 그 id 와 같은 값(숫자·문자열)을 센다 — 글자 검색은 다른 숫자 속 우연한 일치까지 센다
            def count(o):
                if isinstance(o, dict):
                    return sum(count(v) for v in o.values())
                if isinstance(o, list):
                    return sum(count(v) for v in o)
                return 1 if (o == item['id'] or o == str(item['id'])) and not isinstance(o, bool) else 0
            refs = count(doc)
            if refs > a.max_refs:
                print(json.dumps({'ok': False, 'error': f'id {item["id"]} 가 문서에 {refs}번 나온다(최대 {a.max_refs}) — 장착 등에서 참조 중이라 빼지 않는다'},
                                 ensure_ascii=False))
                return 6
    parent, idx = path[:-1], int(path[-1])
    if a.cmd == 'remove':
        try:
            row, ls, le = element_lines(before, path)
        except (ValueError, KeyError) as e:
            print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))
            return 2
        removed = before[ls:le]
        item = get_in(doc, path)
        expected = json.loads(before)
        get_in(expected, parent).pop(idx)
        saved = os.path.join(a.out_dir, f'{key.replace(":", "_")}-{stamp}.removed.json')
        with open(saved, 'w', encoding='utf-8') as f:
            json.dump({'key': key, 'path': a.path, 'row': row, 'text': removed, 'item': item}, f, ensure_ascii=False)
        code, res = apply_edit(a, meta, before, backup, row, row + removed.count('\n'), removed, '', expected, stamp)
        res.update({'path': a.path, 'removed': item, 'saved': saved})
    else:
        if not a.saved:
            print('insert 에는 --saved 가 필요하다', file=sys.stderr)
            return 2
        sv = json.load(open(a.saved, encoding='utf-8'))
        if sv['key'] != key or sv['path'] != a.path:
            print(json.dumps({'ok': False, 'error': '저장 파일의 키·경로가 다르다'}, ensure_ascii=False))
            return 2
        lines = before.split('\n')
        row = sv['row']
        # 같은 줄 위치가 그대로인지(그 사이 다른 변경이 없었는지) 확인: 넣을 자리의 다음 줄이 원래 다음 항목이어야 한다
        expected = json.loads(before)
        arr = get_in(expected, parent)
        if idx > len(arr):
            print(json.dumps({'ok': False, 'error': '배열 길이가 맞지 않는다 — 그 사이 문서가 바뀌었다'}, ensure_ascii=False))
            return 6
        arr.insert(idx, sv['item'])
        if not lines[row].strip().startswith('{'):
            print(json.dumps({'ok': False, 'error': f'{row} 줄이 항목 시작이 아니다 — 그 사이 문서가 바뀌었다', 'line': lines[row][:80]},
                             ensure_ascii=False))
            return 6
        code, res = apply_edit(a, meta, before, backup, row, row, '', sv['text'], expected, stamp)
        res.update({'path': a.path, 'inserted': sv['item']})
    print(json.dumps(res, ensure_ascii=False))
    return code


def peek(a):
    """읽기 전용: 편집기 없이 조회 API 로 문서를 받아 path 값을 본다. 탭은 같은 dev 마카롱의 아무 페이지면 된다.
    path 의 @키=값(배열 항목)도 푼다. 없으면 exists=false. 백업 파일은 남기지 않는다(쓰지 않으므로)."""
    if not a.key:
        print('peek 에는 --key 가 필요하다', file=sys.stderr)
        return 2
    os.makedirs(a.out_dir, exist_ok=True)
    tmp = os.path.join(a.out_dir, f'peek-{os.getpid()}-{time.time_ns()}.json')
    try:
        code, data, err = aside('macaron-api-get', a.target, '--bucket', a.bucket, '--key', a.key, '--out', tmp)
        if code:
            print(json.dumps({'ok': False, 'stage': 'api-get', 'exit': code, 'result': data, 'err': err}, ensure_ascii=False))
            return 3
        doc = json.loads(open(tmp, encoding='utf-8').read())
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    try:
        path = resolve(doc, a.path.split('.'))
        value = get_in(doc, path)
    except KeyError as e:
        if ': 0개' in str(e) or not str(e).startswith("'@"):
            print(json.dumps({'ok': True, 'key': a.key, 'path': a.path, 'exists': False, 'note': str(e)}, ensure_ascii=False))
            return 0
        print(json.dumps({'ok': False, 'error': f'경로를 찾지 못했다: {e}'}, ensure_ascii=False))
        return 2
    except (IndexError, ValueError, TypeError) as e:
        print(json.dumps({'ok': True, 'key': a.key, 'path': a.path, 'exists': False, 'note': str(e)}, ensure_ascii=False))
        return 0
    print(json.dumps({'ok': True, 'key': a.key, 'path': '.'.join(path), 'exists': True, 'value': value}, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['peek', 'get', 'set', 'remove', 'insert'])
    ap.add_argument('path')
    ap.add_argument('value', nargs='?')
    ap.add_argument('--target', required=True)
    ap.add_argument('--key')
    ap.add_argument('--expect')
    ap.add_argument('--out-dir', default=os.path.join(os.getcwd(), 'macaron-backup'))
    ap.add_argument('--saved', help='insert: remove 가 남긴 항목 파일(.removed.json)')
    ap.add_argument('--max-refs', type=int, help='remove: 항목 id 가 문서 전체에 이보다 많이 나오면(장착 등에서 참조) 빼지 않는다')
    ap.add_argument('--bucket', default='gb-member', help='peek: 조회 API 의 버킷')
    a = ap.parse_args()
    if a.cmd == 'peek':
        return peek(a)
    if a.cmd in ('remove', 'insert'):
        return structural(a)
    path = a.path.split('.')
    os.makedirs(a.out_dir, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    meta, before = fetch(a.target, os.path.join(a.out_dir, f'tab-{stamp}.json'))
    key = meta.get('key', '')
    doc = json.loads(before)
    start, end = locate(before, path)
    old_text = before[start:end]
    if a.cmd == 'get':
        os.remove(os.path.join(a.out_dir, f'tab-{stamp}.json'))
        print(json.dumps({'ok': True, 'key': key, 'path': a.path, 'value': json.loads(old_text)}, ensure_ascii=False))
        return 0
    if a.value is None or not a.key:
        print('set 에는 새 값과 --key 가 필요하다', file=sys.stderr)
        return 2
    if a.key != key:
        print(json.dumps({'ok': False, 'error': f'탭의 키({key})가 --key({a.key})와 다르다'}, ensure_ascii=False))
        return 2
    backup = os.path.join(a.out_dir, f'{key.replace(":", "_")}-{stamp}-before.json')
    os.replace(os.path.join(a.out_dir, f'tab-{stamp}.json'), backup)
    if a.expect is not None and json.loads(old_text) != json.loads(a.expect):
        print(json.dumps({'ok': False, 'error': '현재 값이 기대와 다르다', 'current': json.loads(old_text), 'backup': backup},
                         ensure_ascii=False))
        return 6
    new_value = json.loads(a.value)
    new_text = json.dumps(new_value, ensure_ascii=False)
    if '\n' in old_text or '\n' in new_text:
        print('여러 줄 값(객체·배열)은 바꾸지 않는다 — 잎(leaf) 경로를 준다', file=sys.stderr)
        return 2
    row = before.count('\n', 0, start)
    line_start = before.rfind('\n', 0, start) + 1
    prefix = before[line_start:start]
    if any(ord(ch) > 0xFFFF for ch in prefix):
        print('줄 앞부분에 BMP 밖 문자가 있어 열 위치가 어긋날 수 있다 — 멈춘다', file=sys.stderr)
        return 3
    c1, c2 = len(prefix), len(prefix) + len(old_text)
    env = dict(os.environ)
    code, data, err = aside('macaron-replace', a.target, '--row', str(row), '--col-start', str(c1), '--col-end', str(c2),
                            '--expect', old_text, '--new', new_text, env=env)
    if code:
        print(json.dumps({'ok': False, 'stage': 'replace', 'exit': code, 'result': data, 'backup': backup}, ensure_ascii=False))
        return 3
    code, data, err = aside('macaron-save', a.target, env=env)
    if code:
        print(json.dumps({'ok': False, 'stage': 'save', 'exit': code, 'result': data, 'backup': backup}, ensure_ascii=False))
        return 3
    # 「Confirm changes」 창의 변경 줄이 정확히 이 필드의 이전 줄 → 새 줄 하나씩인지 본다
    diff = data.get('diff') or ''
    line_end = before.find('\n', start)
    old_line = before[line_start:line_end if line_end >= 0 else len(before)]
    new_line = old_line[:c1] + new_text + old_line[c2:]
    shown = [x.strip() for x in diff.splitlines()
             if x.strip() and x.strip() not in ('Confirm changes', '...', 'CloseSave', 'Close', 'Save')]
    if shown != [old_line.strip(), new_line.strip()]:
        print(json.dumps({'ok': False, 'stage': 'diff', 'shown': shown[:10], 'expected': [old_line.strip(), new_line.strip()],
                          'backup': backup, 'note': '확인 창을 열어 둔 채 멈췄다. 저장되지 않았다 — 탭을 닫거나 Close'}, ensure_ascii=False))
        return 7
    diff_file = os.path.join(a.out_dir, f'{key.replace(":", "_")}-{stamp}-diff.txt')
    with open(diff_file, 'w', encoding='utf-8') as f:
        f.write(diff)
    code, data, err = aside('macaron-confirm', a.target, '--diff-file', diff_file, env=env)
    if code:
        print(json.dumps({'ok': False, 'stage': 'confirm', 'exit': code, 'result': data, 'backup': backup}, ensure_ascii=False))
        return 3
    # 같은 주소를 새 탭으로 다시 조회해 저장 결과를 본다
    code, opened, err = aside('open', meta['url'])
    time.sleep(5)
    try:
        _, after = fetch(opened['targetId'], os.path.join(a.out_dir, f'{key.replace(":", "_")}-{stamp}-after.json'))
    finally:
        aside('close', opened.get('targetId', ''))
    expected = json.loads(before)
    set_in(expected, path, new_value)
    got = json.loads(after)
    ok = got == expected
    print(json.dumps({'ok': ok, 'key': key, 'path': a.path, 'old': json.loads(old_text), 'new': get_in(got, path),
                      'onlyThisFieldChanged': ok, 'backup': backup, 'save': data}, ensure_ascii=False))
    return 0 if ok else 7


if __name__ == '__main__':
    sys.exit(main())
