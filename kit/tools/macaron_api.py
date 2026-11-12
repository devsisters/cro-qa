"""dev 마카롱(couchbase_modifier) HTTP API — 브라우저 없이 문서를 읽고 저장한다.

dev 마카롱은 로그인이 없다(서버팀 2026-11-12). 마카롱 페이지가 쓰는 것과 같은 API 를 부른다:
  GET  /api/couchbase_modifier/get/?bucket=&key=    → {bucket, key, cas, type, document(문자열)}
  POST /api/couchbase_modifier/save/  form: bucket·key·cas·type=json·document
저장은 cas 가 그 사이 바뀌었으면 400 「document is already edited by something」 으로 거부된다(2026-11-12 실측).

- 주소는 macaron.gb-*.stove.devspie.com 만 받는다(Real·운영 마카롱을 부르지 않게)
- 인증서가 *.stove.devspie.com 용이라 이 호스트 이름과 맞지 않는다. 체인 검증은 하고 호스트 이름 검사만 끈다(사용자 승인 2026-11-12, 마카롱만)
- CSRF 는 Django 의 쿠키·폼 이중 제출이다. 페이지가 쿠키를 주지 않아 같은 임의 값을 쿠키와 폼에 함께 넣는다
- create·delete API 는 두지 않는다
"""
import json
import re
import secrets
import ssl
import string
import urllib.error
import urllib.parse
import urllib.request

ENV_RE = re.compile(r'gb-[a-z0-9-]+')


class MacaronError(Exception):
    pass


class NotFound(MacaronError):
    pass


class CasConflict(MacaronError):
    """그 사이 다른 쪽(주로 접속 중인 앱)이 문서를 바꿨다. 다시 읽어 처음부터 한다."""


def base_url(env):
    if not ENV_RE.fullmatch(env or ''):
        raise MacaronError(f'dev 마카롱 서버 이름(gb-…)이 아니다: {env!r}')
    return f'https://macaron.{env}.stove.devspie.com'


def _opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def get(env, key, bucket='gb-member', timeout=60):
    """→ (문서 텍스트, cas). 문서가 없으면 NotFound."""
    url = base_url(env) + '/api/couchbase_modifier/get/?' + urllib.parse.urlencode({'bucket': bucket, 'key': key})
    try:
        with _opener().open(url, timeout=timeout) as r:
            v = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(f'{env} {bucket}/{key} 문서가 없다') from None
        raise MacaronError(f'조회 실패 HTTP {e.code}: {e.read()[:200]!r}') from None
    if v.get('type') != 'json' or not isinstance(v.get('document'), str):
        raise MacaronError(f'JSON 문서가 아니다: type={v.get("type")}')
    return v['document'], str(v['cas'])


def save(env, key, text, cas, bucket='gb-member', timeout=120):
    """cas 가 맞을 때만 저장한다 → 새 cas. 그 사이 바뀌었으면 CasConflict."""
    json.loads(text)   # 깨진 JSON 은 보내지 않는다
    base = base_url(env)
    token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
    data = urllib.parse.urlencode({'bucket': bucket, 'key': key, 'cas': cas, 'type': 'json', 'document': text,
                                   'csrfmiddlewaretoken': token}).encode()
    req = urllib.request.Request(base + '/api/couchbase_modifier/save/', data=data, method='POST',
                                 headers={'Referer': base + '/couchbase_modifier/', 'Cookie': 'csrftoken=' + token})
    try:
        with _opener().open(req, timeout=timeout) as r:
            v = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode('utf-8', 'replace')
        if e.code == 400 and 'already edited' in body:
            raise CasConflict('그 사이 문서가 바뀌었다(cas 불일치)') from None
        raise MacaronError(f'저장 실패 HTTP {e.code}: {body[:200]}') from None
    if 'cas' not in v:
        raise MacaronError(f'저장 응답에 cas 가 없다: {str(v)[:200]}')
    return str(v['cas'])
