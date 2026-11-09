"""계정 상태 레시피 — 마카롱(couchbase_modifier)으로 테스트 계정 필드를 바꾸고 되돌린다.

전제: 키트 Chrome 이 CDP 포트로 떠 있고(`node tools/web/chrome_cdp.mjs launch`) 마카롱에 로그인돼 있다. 쓰기는 `../macaron_edit.py` 가 한다.
서버는 dev 마카롱(gb-*) 전부, 계정 제한은 없다. 바꾸기 전 문서 전체를 백업하고, 저장 뒤 그 필드만 바뀌었는지 비교한다.
바꾼 뒤 앱에 반영하려면 routes.refresh_user_info(dev) 를 부른다.

  with field(env, mid, 'wallet.my_cookie_icing_gacha_token.amt', 50, out_dir) as old:
      ...   # 블록을 나오면(예외여도) 원래 값으로 되돌린다
"""
import contextlib
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


def _open(env, mid):
    url = (f'https://macaron.{env}.stove.devspie.com/couchbase_modifier/?bucket=gb-member&key='
           + urllib.parse.quote(f'member:{mid}'))
    code, data = _run(['node', ASIDE, 'open', url])
    if code or 'targetId' not in data:
        raise FlowFailure('BRIDGE', 'macaron open', f'키트 Chrome 탭을 열지 못했다: {data}')
    # 뒤에 있는 탭은 브라우저가 스크립트를 늦춰 큰 문서가 편집기에 올라오지 않는다. 앞으로 가져온다
    port = os.environ.get('QA_CDP_PORT', '9444')
    urllib.request.urlopen(f'http://127.0.0.1:{port}/json/activate/{data["targetId"]}', timeout=5).read()
    time.sleep(8)
    return data['targetId']


def set_field(env, mid, path, value, out_dir, expect=None):
    target = _open(env, mid)
    try:
        cmd = ['python3', EDIT, 'set', path, json.dumps(value), '--target', target, '--key', f'member:{mid}', '--out-dir', out_dir]
        if expect is not None:
            cmd += ['--expect', json.dumps(expect)]
        code, data = _run(cmd)
    finally:
        _run(['node', ASIDE, 'close', target])
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron set {path}', json.dumps(data, ensure_ascii=False)[:300])
    return data


def get_field(env, mid, path, out_dir):
    target = _open(env, mid)
    try:
        code, data = _run(['python3', EDIT, 'get', path, '--target', target, '--out-dir', out_dir])
    finally:
        _run(['node', ASIDE, 'close', target])
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron get {path}', json.dumps(data, ensure_ascii=False)[:300])
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
    """배열 항목을 뺀다(예: inventory.pets.@id=201800). 되돌리기 정보(saved 파일·실제 경로)를 돌려준다."""
    target = _open(env, mid)
    try:
        code, data = _run(['python3', EDIT, 'remove', path, '--target', target, '--key', f'member:{mid}', '--out-dir', out_dir]
                          + (['--max-refs', str(max_refs)] if max_refs else []))
    finally:
        _run(['node', ASIDE, 'close', target])
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron remove {path}', json.dumps(data, ensure_ascii=False)[:300])
    return data


def insert_item(env, mid, path, saved, out_dir):
    """remove_item 이 뺀 항목을 같은 자리에 다시 넣는다."""
    target = _open(env, mid)
    try:
        code, data = _run(['python3', EDIT, 'insert', path, '--saved', saved, '--target', target, '--key', f'member:{mid}',
                           '--out-dir', out_dir])
    finally:
        _run(['node', ASIDE, 'close', target])
    if code or not data.get('ok'):
        raise FlowFailure('BRIDGE', f'macaron insert {path}', json.dumps(data, ensure_ascii=False)[:300])
    return data
