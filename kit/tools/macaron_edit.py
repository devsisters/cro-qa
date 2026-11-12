#!/usr/bin/env python3
"""마카롱 couchbase 문서를 API 로 읽고 고친다 — 테스트 계정 상태 만들기용(2026-11-03 사용자 승인).

  python3 macaron_edit.py peek   <path> --env gb-qa-126 --key member:<MID>
  python3 macaron_edit.py set    <path> <new JSON value> --env … --key … [--expect <old JSON value>] [--out-dir DIR]
  python3 macaron_edit.py remove <배열 항목 path> --env … --key … [--max-refs N] [--out-dir DIR]
  python3 macaron_edit.py insert <같은 path> --saved <remove 가 남긴 .removed.json> --env … --key … [--out-dir DIR]

<path> 는 점으로 잇는다(예: wallet.my_cookie_icing_gacha_token.amt). 배열은 숫자 또는 @키=값(예: inventory.pets.@id=201800).
브라우저를 쓰지 않는다(macaron_api.py). 쓰기 순서:
  1. 문서 텍스트와 cas 를 받아 백업(<out-dir>/<key>-<시각>-before.json)
  2. 바꿀 값의 텍스트 범위만 바꾼다. 문서 전체를 다시 직렬화하지 않는다(int64·숫자 표기를 그대로 둔다)
  3. 보내기 전에 「바꾼 텍스트를 파싱한 것 == 원래 문서에 그 변경만 적용한 것」 인지 확인한다
  4. cas 를 붙여 저장한다. 그 사이 앱이 문서를 바꿨으면 거부되므로 1부터 다시 한다(기대값도 다시 본다)
  5. 다시 읽어 그 값이 저장됐는지 본다
서버는 dev 마카롱(gb-*)만, 계정 제한은 없다(2026-11-03 사용자 결정 — 전부 테스트 계정). 문서 삭제·생성은 하지 않는다.
exit: 0 성공, 2 사용법·경로 없음, 3 도구·통신 실패, 6 기대값 불일치·참조 중, 7 저장 뒤 검증 실패
"""
import argparse
import json
import os
import sys
import time

import macaron_api

DEC = json.JSONDecoder()
WS = ' \t\n\r'
RETRIES = 3


def skip(s, i):
    while i < len(s) and s[i] in WS:
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


# ── 텍스트 편집: 바꾼 범위 밖의 글자는 그대로 둔다 ──

def text_set(text, path, new_text):
    start, end = locate(text, path)
    return text[:start] + new_text + text[end:], text[start:end]


def text_remove(text, path):
    """배열 항목 하나를 뺀다 → (새 텍스트, 뺀 항목 텍스트)."""
    start, end = locate(text, path)
    item = text[start:end]
    i = skip(text, end)
    if text[i] == ',':                       # 뒤 항목이 있다: 항목부터 다음 항목 앞까지
        return text[:start] + text[skip(text, i + 1):], item
    j = start - 1
    while text[j] in WS:
        j -= 1
    if text[j] == ',':                       # 마지막 항목: 앞 쉼표부터 항목 끝까지
        return text[:j] + text[end:], item
    return text[:start] + text[end:], item   # 하나뿐인 항목


def text_insert(text, parent, idx, item_text):
    """parent 배열의 idx 자리에 item_text 를 넣는다. 들여쓰기는 이웃 항목 앞 공백을 따른다."""
    s, e = locate(text, parent)
    if text[s] != '[':
        raise ValueError('배열이 아니다')
    n = len(json.loads(text[s:e]))
    if idx > n:
        raise IndexError(f'배열 길이 {n} 보다 뒤({idx})에 넣을 수 없다')
    if n == 0:
        return text[:s + 1] + item_text + text[s + 1:]
    if idx < n:
        pos, _ = locate(text, parent + [str(idx)])
        k = pos
        while text[k - 1] in WS:
            k -= 1
        return text[:pos] + item_text + ',' + text[k:pos] + text[pos:]
    ls, le = locate(text, parent + [str(n - 1)])
    k = ls
    while text[k - 1] in WS:
        k -= 1
    return text[:le] + ',' + text[k:ls] + item_text + text[le:]


def count_refs(o, ident):
    """문서 구조에서 ident 와 같은 값(숫자·문자열)을 센다 — 글자 검색은 다른 숫자 속 우연한 일치까지 센다."""
    if isinstance(o, dict):
        return sum(count_refs(v, ident) for v in o.values())
    if isinstance(o, list):
        return sum(count_refs(v, ident) for v in o)
    return 1 if (o == ident or o == str(ident)) and not isinstance(o, bool) else 0


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))


def backup_path(a, stamp, tag='before'):
    return os.path.join(a.out_dir, f'{a.key.replace(":", "_")}-{stamp}-{tag}.json')


def plan(a, text, doc, stamp):
    """현재 문서로 바꿀 텍스트를 만든다 → (exit, 결과 dict, 새 텍스트 또는 None, 기대 문서)."""
    tokens = a.path.split('.')
    if a.cmd == 'set':
        try:
            path = resolve(doc, tokens)
            old = get_in(doc, path)
        except (KeyError, IndexError, ValueError, TypeError) as e:
            return 2, {'ok': False, 'error': f'경로를 찾지 못했다: {e}'}, None, None
        if a.expect is not None and old != json.loads(a.expect):
            return 6, {'ok': False, 'error': '현재 값이 기대와 다르다', 'current': old}, None, None
        new_value = json.loads(a.value)
        new_text, _ = text_set(text, path, json.dumps(new_value, ensure_ascii=False))
        expected = json.loads(text)
        set_in(expected, path, new_value)
        return 0, {'path': '.'.join(path), 'old': old, 'new': new_value}, new_text, expected
    if a.cmd == 'remove':
        try:
            path = resolve(doc, tokens)
        except KeyError as e:
            if ': 0개' in str(e):
                return 0, {'ok': True, 'already': True, 'path': a.path, 'note': '이미 없는 항목'}, None, None
            return 2, {'ok': False, 'error': f'경로를 찾지 못했다: {e}'}, None, None
        except (IndexError, ValueError, TypeError) as e:
            return 2, {'ok': False, 'error': f'경로를 찾지 못했다: {e}'}, None, None
        parent, idx = path[:-1], int(path[-1])
        if not isinstance(get_in(doc, parent), list):
            return 2, {'ok': False, 'error': '배열 항목 경로가 아니다'}, None, None
        item = get_in(doc, path)
        if a.max_refs and isinstance(item, dict) and 'id' in item:
            refs = count_refs(doc, item['id'])
            if refs > a.max_refs:
                return 6, {'ok': False, 'error': f'id {item["id"]} 가 문서에 {refs}번 나온다(최대 {a.max_refs}) — 장착 등에서 참조 중이라 빼지 않는다'}, None, None
        new_text, item_text = text_remove(text, path)
        expected = json.loads(text)
        get_in(expected, parent).pop(idx)
        saved = os.path.join(a.out_dir, f'{a.key.replace(":", "_")}-{stamp}.removed.json')
        with open(saved, 'w', encoding='utf-8') as f:
            json.dump({'key': a.key, 'path': '.'.join(path), 'text': item_text, 'item': item}, f, ensure_ascii=False)
        return 0, {'path': '.'.join(path), 'removed': item, 'saved': saved}, new_text, expected
    # insert
    with open(a.saved, encoding='utf-8') as f:
        sv = json.load(f)
    if sv['key'] != a.key or sv['path'] != a.path:
        return 2, {'ok': False, 'error': '저장 파일의 키·경로가 다르다'}, None, None
    path = a.path.split('.')
    parent, idx = path[:-1], int(path[-1])
    try:
        arr = get_in(doc, parent)
    except (KeyError, IndexError, ValueError, TypeError) as e:
        return 2, {'ok': False, 'error': f'배열을 찾지 못했다: {e}'}, None, None
    if not isinstance(arr, list) or idx > len(arr):
        return 6, {'ok': False, 'error': '배열 길이가 맞지 않는다 — 그 사이 문서가 바뀌었다'}, None, None
    if sv['item'] in arr:
        return 0, {'ok': True, 'already': True, 'path': a.path, 'note': '같은 항목이 이미 있다'}, None, None
    new_text = text_insert(text, parent, idx, sv['text'])
    expected = json.loads(text)
    get_in(expected, parent).insert(idx, sv['item'])
    return 0, {'path': a.path, 'inserted': sv['item']}, new_text, expected


def write(a):
    os.makedirs(a.out_dir, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for attempt in range(1, RETRIES + 1):
        try:
            text, cas = macaron_api.get(a.env, a.key, a.bucket)
        except macaron_api.MacaronError as e:
            out({'ok': False, 'stage': 'get', 'error': str(e)})
            return 3
        backup = backup_path(a, stamp)
        with open(backup, 'w', encoding='utf-8') as f:
            f.write(text)
        doc = json.loads(text)
        code, res, new_text, expected = plan(a, text, doc, stamp)
        if new_text is None:
            res.setdefault('backup', backup)
            out(res)
            return code
        if json.loads(new_text) != expected:
            out({'ok': False, 'stage': 'plan', 'error': '텍스트 편집 결과가 기대 문서와 다르다 — 저장하지 않았다', 'backup': backup})
            return 7
        try:
            new_cas = macaron_api.save(a.env, a.key, new_text, cas, a.bucket)
        except macaron_api.CasConflict:
            if attempt < RETRIES:
                time.sleep(1)
                continue
            out({'ok': False, 'stage': 'save', 'error': f'{RETRIES}번 모두 그 사이 문서가 바뀌었다(cas 불일치)', 'backup': backup})
            return 3
        except macaron_api.MacaronError as e:
            out({'ok': False, 'stage': 'save', 'error': str(e), 'backup': backup})
            return 3
        break
    try:
        after, after_cas = macaron_api.get(a.env, a.key, a.bucket)
    except macaron_api.MacaronError as e:
        out({'ok': False, 'stage': 'verify', 'error': str(e), 'backup': backup, 'saved': True})
        return 3
    got = json.loads(after)
    # 저장한 cas 그대로면 문서 전체가 같아야 한다. 그 사이 앱이 또 바꿨으면(cas 다름) 바꾼 경로만 본다
    if after_cas == new_cas:
        ok = got == expected
    elif a.cmd == 'set':
        ok = get_in(got, res['path'].split('.')) == res['new']
    else:
        parent = res['path'].split('.')[:-1]
        ok = get_in(got, parent) == get_in(expected, parent)
    res.update({'ok': ok, 'key': a.key, 'env': a.env, 'backup': backup, 'attempts': attempt,
                'changedAfterSave': after_cas != new_cas})
    out(res)
    return 0 if ok else 7


def peek(a):
    """읽기 전용 → {'exists': bool, 'value': …}. 백업 파일은 남기지 않는다."""
    try:
        text, _ = macaron_api.get(a.env, a.key, a.bucket)
    except macaron_api.MacaronError as e:
        out({'ok': False, 'stage': 'get', 'error': str(e)})
        return 3
    doc = json.loads(text)
    try:
        path = resolve(doc, a.path.split('.'))
        value = get_in(doc, path)
    except KeyError as e:
        if ': 0개' in str(e) or not str(e).startswith("'@"):
            out({'ok': True, 'key': a.key, 'path': a.path, 'exists': False, 'note': str(e)})
            return 0
        out({'ok': False, 'error': f'경로를 찾지 못했다: {e}'})
        return 2
    except (IndexError, ValueError, TypeError) as e:
        out({'ok': True, 'key': a.key, 'path': a.path, 'exists': False, 'note': str(e)})
        return 0
    out({'ok': True, 'key': a.key, 'path': '.'.join(path), 'exists': True, 'value': value})
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['peek', 'set', 'remove', 'insert'])
    ap.add_argument('path')
    ap.add_argument('value', nargs='?')
    ap.add_argument('--env', required=True, help='dev 서버 이름(예: gb-qa-126)')
    ap.add_argument('--key', required=True, help='예: member:<MID>')
    ap.add_argument('--bucket', default='gb-member')
    ap.add_argument('--expect')
    ap.add_argument('--out-dir', default=os.path.join(os.getcwd(), 'macaron-backup'))
    ap.add_argument('--saved', help='insert: remove 가 남긴 항목 파일(.removed.json)')
    ap.add_argument('--max-refs', type=int, help='remove: 항목 id 가 문서 전체에 이보다 많이 나오면(장착 등에서 참조) 빼지 않는다')
    a = ap.parse_args(argv)
    if a.cmd == 'peek':
        return peek(a)
    if a.cmd == 'set' and a.value is None:
        print('set 에는 새 값이 필요하다', file=sys.stderr)
        return 2
    if a.cmd == 'insert' and not a.saved:
        print('insert 에는 --saved 가 필요하다', file=sys.stderr)
        return 2
    return write(a)


if __name__ == '__main__':
    sys.exit(main())
