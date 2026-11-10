"""계정 상태 레시피 — 마카롱(couchbase_modifier)으로 테스트 계정 필드를 바꾸고 되돌린다.

전제: 키트 Chrome 이 CDP 포트로 떠 있고(`node tools/web/chrome_cdp.mjs launch`) 마카롱에 로그인돼 있다. 쓰기는 `../macaron_edit.py` 가 한다.
서버는 dev 마카롱(gb-*) 전부, 계정 제한은 없다. 바꾸기 전 문서 전체를 백업하고, 저장 뒤 그 필드만 바뀌었는지 비교한다.
바꾼 뒤 앱에 반영하려면 routes.refresh_user_info(dev) 를 부른다.

  with field(env, mid, 'wallet.my_cookie_icing_gacha_token.amt', 50, out_dir) as old:
      ...   # 블록을 나오면(예외여도) 원래 값으로 되돌린다
"""
import contextlib
import fcntl
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

from flowlib import FlowFailure

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASIDE = os.path.join(TOOLS, 'web', 'chrome_cdp.mjs')
EDIT = os.path.join(TOOLS, 'macaron_edit.py')

RECIPES = {
    # 이름: (경로, 값) — 플로우가 이름으로 부른다
    'icing_token_lack': ('wallet.my_cookie_icing_gacha_token.amt', 50),
}


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    try:
        return r.returncode, json.loads(r.stdout) if r.stdout.strip().startswith('{') and len(lines) > 1 else json.loads(lines[-1])
    except (ValueError, IndexError):
        return r.returncode, {'raw': r.stdout[-300:], 'err': r.stderr[-300:]}


def _ensure_chrome():
    """키트 Chrome(CDP 포트)이 꺼져 있으면 띄운다 — 새 컴퓨터·재부팅·창을 닫은 뒤에는 꺼져 있다(안 띄우면 fetch failed).
    처음 한 번은 사람이 그 창에서 stove·마카롱에 로그인해야 한다(SETUP.md). 로그인은 프로필에 남는다."""
    code, data = _run(['node', ASIDE, 'status'])
    if code == 0 and data.get('cdp'):
        return
    code, data = _run(['node', ASIDE, 'launch'])
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', 'macaron open', f'키트 Chrome 을 띄우지 못했다: {data} — `node tools/web/chrome_cdp.mjs launch` 를 직접 돌려 보고, '
                          'Node.js·Chrome 설치와 키트 Chrome 창의 stove·마카롱 로그인(SETUP.md)을 확인한다')


def _open(env, mid):
    _ensure_chrome()
    url = (f'https://macaron.{env}.stove.devspie.com/couchbase_modifier/?bucket=gb-member&key='
           + urllib.parse.quote(f'member:{mid}'))
    code, data = _run(['node', ASIDE, 'open', url])
    if code or 'targetId' not in data:
        raise FlowFailure('BRIDGE', 'macaron open', f'키트 Chrome 탭을 열지 못했다: {data}')
    # 뒤에 있는 탭은 브라우저가 스크립트를 늦춰 큰 문서가 편집기에 올라오지 않는다. 앞으로 가져온다
    port = os.environ.get('QA_CDP_PORT', '9444')
    urllib.request.urlopen(f'http://127.0.0.1:{port}/json/activate/{data["targetId"]}', timeout=5).read()
    time.sleep(2)   # 편집기에 문서가 올라올 때까지는 macaron_edit 의 fetch 가 다시 읽으며 기다린다
    return data['targetId']


LOCK_FILE = os.path.join(os.path.dirname(TOOLS), 'workspace', 'macaron.lock')
LOCK_WAIT = 600   # 초 — 편집기로 저장하는 마카롱 단계 하나는 10~20초(8.4MB 문서를 편집기에 올리는 데 약 11초, 2026-11-10 측정).
#                  예전에 잰 91초는 chrome_cdp.mjs 가 응답 뒤에도 90초 타이머를 남겨 node 가 늦게 끝난 것이었다(고침)


@contextlib.contextmanager
def _session(env, mid):
    """마카롱 탭 하나를 열고 닫는 동안 이 컴퓨터의 다른 실행(다른 기기)은 기다린다.
    키트 Chrome 은 하나라 두 기기가 동시에 탭을 앞으로 가져오면 뒤로 밀린 탭이 문서를 다 받지 못해 실패한다.
    잠금은 파일 잠금(flock)이라 실행이 죽으면 저절로 풀린다."""
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    with open(LOCK_FILE, 'a') as lock:
        deadline = time.time() + LOCK_WAIT
        told = False
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not told:
                    print('다른 기기가 마카롱을 쓰는 중 — 끝날 때까지 기다린다', flush=True)
                    told = True
                if time.time() > deadline:
                    raise FlowFailure('BRIDGE', 'macaron lock', f'{LOCK_WAIT}초 동안 다른 실행이 마카롱을 놓지 않았다 — 멈춘 실행이 있는지 본다')
                time.sleep(1)
        print('마카롱 차례 — 계정 문서를 편집기로 여는 중(큰 문서는 10~20초)', flush=True)
        try:
            target = _open(env, mid)
            try:
                yield target
            finally:
                _run(['node', ASIDE, 'close', target])
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            print('마카롱 끝 — 다음 기기 차례', flush=True)


def peek(env, mid, path, out_dir):
    """편집기를 열지 않고 조회 API 로 path 값을 본다(1~2초) → {'exists': bool, 'value': …}.
    탭은 문서 없는 마카롱 페이지라 앞으로 가져올 필요도, 다른 기기를 기다릴 필요도 없다(잠금 없음)."""
    code, data = _run(['node', ASIDE, 'open', f'https://macaron.{env}.stove.devspie.com/couchbase_modifier/'])
    if code or 'targetId' not in data:
        raise FlowFailure('BRIDGE', 'macaron open', f'키트 Chrome 탭을 열지 못했다: {data}')
    try:
        code, res = _run(['python3', EDIT, 'peek', path, '--target', data['targetId'], '--key', f'member:{mid}', '--out-dir', out_dir])
    finally:
        _run(['node', ASIDE, 'close', data['targetId']])
    if code or not res.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron peek {path}', json.dumps(res, ensure_ascii=False)[:300])
    return res


def set_field(env, mid, path, value, out_dir, expect=None):
    with _session(env, mid) as target:
        cmd = ['python3', EDIT, 'set', path, json.dumps(value), '--target', target, '--key', f'member:{mid}', '--out-dir', out_dir]
        if expect is not None:
            cmd += ['--expect', json.dumps(expect)]
        code, data = _run(cmd)
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron set {path}', json.dumps(data, ensure_ascii=False)[:300])
    return data


def get_field(env, mid, path, out_dir):
    data = peek(env, mid, path, out_dir)
    if not data.get('exists'):
        raise FlowFailure('BRIDGE', f'macaron get {path}', f'문서에 없는 경로다: {data.get("note")}')
    return data['value']


@contextlib.contextmanager
def field(env, mid, path, value, out_dir):
    """필드를 value 로 바꾸고, 블록이 끝나면 원래 값으로 되돌린다."""
    old = get_field(env, mid, path, out_dir)
    set_field(env, mid, path, value, out_dir, expect=old)
    try:
        yield old
    finally:
        set_field(env, mid, path, old, out_dir, expect=value)


def remove_item(env, mid, path, out_dir, max_refs=None):
    """배열 항목을 뺀다(예: inventory.pets.@id=201800). 되돌리기 정보(saved 파일·실제 경로)를 돌려준다.
    먼저 조회 API 로 본다 — 이미 없으면 편집기를 열지 않는다(상태는 되돌리지 않는 것이 기본이라 두 번째 실행부터 거의 이렇다)."""
    if not peek(env, mid, path, out_dir).get('exists'):
        return {'ok': True, 'already': True, 'path': path, 'note': '이미 없는 항목(조회 API 로 확인)'}
    with _session(env, mid) as target:
        code, data = _run(['python3', EDIT, 'remove', path, '--target', target, '--key', f'member:{mid}', '--out-dir', out_dir]
                          + (['--max-refs', str(max_refs)] if max_refs else []))
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron remove {path}', json.dumps(data, ensure_ascii=False)[:300])
    return data


def insert_item(env, mid, path, saved, out_dir):
    """remove_item 이 뺀 항목을 같은 자리에 다시 넣는다."""
    with _session(env, mid) as target:
        code, data = _run(['python3', EDIT, 'insert', path, '--saved', saved, '--target', target, '--key', f'member:{mid}',
                           '--out-dir', out_dir])
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron insert {path}', json.dumps(data, ensure_ascii=False)[:300])
    return data
