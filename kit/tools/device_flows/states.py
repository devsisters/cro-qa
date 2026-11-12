"""계정 상태 레시피 — 마카롱(couchbase_modifier) API 로 테스트 계정 필드를 바꾸고 되돌린다.

쓰기는 `../macaron_edit.py` 가 한다(브라우저 없이 API, 바꾸기 전 백업, cas 로 동시 변경 거부, 저장 뒤 재조회).
서버는 dev 마카롱(gb-*) 전부, 계정 제한은 없다. 바꾼 뒤 앱에 반영하려면 routes.refresh_user_info(dev) 를 부른다.
여러 기기가 동시에 불러도 된다. 같은 계정 문서를 동시에 바꾸면 cas 가 늦은 쪽을 거부하고 macaron_edit 이 다시 읽어 재시도한다.

  with field(env, mid, 'wallet.my_cookie_icing_gacha_token.amt', 50, out_dir) as old:
      ...   # 블록을 나오면(예외여도) 원래 값으로 되돌린다
"""
import contextlib
import json
import os
import subprocess

from flowlib import FlowFailure

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDIT = os.path.join(TOOLS, 'macaron_edit.py')

RECIPES = {
    # 이름: (경로, 값) — 플로우가 이름으로 부른다
    'icing_token_lack': ('wallet.my_cookie_icing_gacha_token.amt', 50),
}


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    try:
        return r.returncode, json.loads(lines[-1])
    except (ValueError, IndexError):
        return r.returncode, {'raw': r.stdout[-300:], 'err': r.stderr[-300:]}


def _edit(op, env, mid, path, out_dir, *extra):
    return _run(['python3', EDIT, op, path, *extra, '--env', env, '--key', f'member:{mid}', '--out-dir', out_dir])


def peek(env, mid, path, out_dir):
    """조회만 한다 → {'exists': bool, 'value': …}."""
    code, res = _edit('peek', env, mid, path, out_dir)
    if code or not res.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron peek {path}', json.dumps(res, ensure_ascii=False)[:300])
    return res


def set_field(env, mid, path, value, out_dir, expect=None):
    extra = [json.dumps(value)] + (['--expect', json.dumps(expect)] if expect is not None else [])
    code, data = _edit('set', env, mid, path, out_dir, *extra)
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
    이미 없으면 저장하지 않고 already=True 를 돌려준다(상태는 되돌리지 않는 것이 기본이라 두 번째 실행부터 거의 이렇다)."""
    code, data = _edit('remove', env, mid, path, out_dir, *(['--max-refs', str(max_refs)] if max_refs else []))
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron remove {path}', json.dumps(data, ensure_ascii=False)[:300])
    return data


def insert_item(env, mid, path, saved, out_dir):
    """remove_item 이 뺀 항목을 같은 자리에 다시 넣는다."""
    code, data = _edit('insert', env, mid, path, out_dir, '--saved', saved)
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron insert {path}', json.dumps(data, ensure_ascii=False)[:300])
    return data
