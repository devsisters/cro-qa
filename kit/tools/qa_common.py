"""케이스 실행기·정답지·판정·리포트가 함께 쓰는 것 — 노드 선택자, 기대값 판정, 게임 좌표 → 캡처 픽셀 변환, 경로."""
import json
import os
import re

TOOLS = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(TOOLS)
CASES = os.path.join(KIT, 'cases')
ANSWERS = os.path.join(KIT, 'answers')
RUNS = os.path.join(KIT, 'runs')
WORKSPACE = os.path.join(KIT, 'workspace')

PLATFORMS = ('ios', 'aos', 'mac')
DIGIT = re.compile(r'\d')

# 판정 값 — 나쁜 순서(케이스 판정은 체크포인트 중 가장 나쁜 것)
ORDER = ['ERROR', 'FAIL', 'REVIEW', 'UNSURE', 'HUMAN', 'PASS', 'NOT_RUN']  # HUMAN: 조건은 통과, 캡처를 사람이 볼 지점


def worst(verdicts):
    vs = [v for v in verdicts if v]
    return min(vs, key=ORDER.index) if vs else 'NOT_RUN'


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# --- 선택자 ---------------------------------------------------------------
# 문자열 하나면 inst·name·text 중 하나가 같은 노드. 객체면 키마다 조건:
#   inst · name · text · owner · type          같아야 한다
#   text_contains                              text 에 들어 있다
#   any                                        inst·name·text 중 하나가 같다
SELECTOR_KEYS = ('inst', 'name', 'text', 'owner', 'type', 'text_contains', 'any')


def normalize(sel):
    if isinstance(sel, str):
        return {'any': sel}
    if not isinstance(sel, dict) or not sel or any(k not in SELECTOR_KEYS + ('min', 'max') for k in sel):
        raise ValueError(f'선택자 형식이 틀렸다: {sel!r} (쓸 수 있는 키 {SELECTOR_KEYS})')
    return sel


def matches(node, sel):
    sel = normalize(sel)
    for k, v in sel.items():
        if k in ('min', 'max'):
            continue
        if k == 'any':
            if v not in (node.get('inst'), node.get('name'), node.get('text')):
                return False
        elif k == 'text_contains':
            if v not in (node.get('text') or ''):
                return False
        elif node.get(k) != v:
            return False
    return True


def select(nodes, sel):
    return [n for n in nodes if matches(n, sel)]


def describe(sel):
    sel = normalize(sel)
    return ' '.join(f'{k}={v}' for k, v in sel.items())


def visible(tree):
    return [n for n in tree.get('nodes', []) if n.get('clipped') is not True and not n.get('offscreen')
            and n.get('visible', True) is not False]


# --- 기대값(정답지 1층: 트리) ------------------------------------------------
def screen_order(nodes, sel):
    """선택자에 맞는 노드의 글자를 화면 순서(위 줄부터, 줄 안에서는 왼쪽부터)로. rect 원점은 왼쪽 아래다."""
    hit = [n for n in select(nodes, sel) if n.get('rect') and n.get('text') is not None]
    hit.sort(key=lambda n: (-round(n['rect'][1] + n['rect'][3]), n['rect'][0]))
    return [n['text'] for n in hit]


def check_order(item, nodes, prior):
    """expect 의 order 항목 하나 → [(check, ok, detail)].
    first: 앞에서부터 이 글자들 · notFirst: 맨 앞이 이 글자가 아니다 ·
    sameAs: 앞선 checkpoint 와 순서가 같다(ignore 글자를 둘 다에서 뺀 뒤, 겹치는 앞부분)."""
    sel = item['select']
    cur = screen_order(nodes, sel)
    shown = f'실제 {cur[:6]}'
    out = []
    if 'first' in item:
        want = list(item['first'])
        out.append((f'순서 맨 앞 {want}: {describe(sel)}', cur[:len(want)] == want, shown))
    for t in item.get('notFirst', []):
        out.append((f'순서 맨 앞이 「{t}」 아님: {describe(sel)}', bool(cur) and cur[0] != t, shown))
    if item.get('sameAs'):
        ref = (prior or {}).get(item['sameAs'])
        ign = set(item.get('ignore', []))
        if ref is None:
            out.append((f'순서 = {item["sameAs"]}', False, f'앞선 checkpoint 「{item["sameAs"]}」 가 없다'))
        else:
            a = [t for t in cur if t not in ign]
            b = [t for t in screen_order(ref, sel) if t not in ign]
            n = min(len(a), len(b))
            ok = n > 0 and a[:n] == b[:n]
            out.append((f'순서 = {item["sameAs"]}' + (f' (뺀 것 {sorted(ign)})' if ign else '') + f': {describe(sel)}', ok,
                        f'앞 {n}개 비교 · 이번 {a[:n]} · {item["sameAs"]} {b[:n]}' if not ok else f'앞 {n}개 같음'))
    return out


def check_when(when, nodes):
    """단계의 when 조건({"present": 선택자} / {"absent": 선택자}) → 이 단계를 할지."""
    if 'present' in when and not select(nodes, when['present']):
        return False
    if 'absent' in when and select(nodes, when['absent']):
        return False
    return True


def check_expect(expect, scene, nodes, prior=None):
    """expect 를 트리로 판정한다 → [{'check','ok','detail'}]. 모델을 쓰지 않는다.
    prior: 같은 케이스에서 앞서 지난 checkpoint 이름 → 그때의 노드(order 의 sameAs 에 쓴다)."""
    out = []

    def add(check, ok, detail=''):
        out.append({'check': check, 'ok': bool(ok), 'detail': detail})

    if not expect:
        return out
    want = expect.get('scene')
    if want:
        names = [want] if isinstance(want, str) else list(want)
        add(f'scene ∈ {names}', scene in names, f'실제 {scene}')
    for sel in expect.get('present', []):
        hit = select(nodes, sel)
        add(f'있음: {describe(sel)}', hit, f'{len(hit)}개')
    for sel in expect.get('absent', []):
        hit = select(nodes, sel)
        add(f'없음: {describe(sel)}', not hit, f'{len(hit)}개' + (f' 예: {hit[0].get("text") or hit[0].get("inst")}' if hit else ''))
    for sel in expect.get('tappable', []):
        hit = select(nodes, sel)
        ok = [n for n in hit if n.get('receiver') and not n.get('blockedBy') and n.get('enabled') is not False]
        why = '' if ok else ('없음' if not hit else
                             '; '.join(f'receiver={n.get("receiver")} blockedBy={n.get("blockedByDesc") or n.get("blockedBy")} '
                                       f'enabled={n.get("enabled")}' for n in hit[:2]))
        add(f'누를 수 있음: {describe(sel)}', ok, why)
    for sel in expect.get('disabled', []):
        hit = select(nodes, sel)
        add(f'비활성: {describe(sel)}', hit and all(n.get('enabled') is False for n in hit),
            '없음' if not hit else f'enabled={[n.get("enabled") for n in hit[:3]]}')
    for sel in expect.get('count', []):
        sel = normalize(sel)
        hit = select(nodes, sel)
        lo, hi = sel.get('min', 0), sel.get('max', 10 ** 9)
        add(f'개수 {lo}~{hi if hi < 10 ** 9 else ""}: {describe(sel)}', lo <= len(hit) <= hi, f'{len(hit)}개')
    for item in expect.get('text', []):
        # {"select": 선택자, "equals": "..."} 또는 "contains"
        hit = select(nodes, item['select'])
        texts = [n.get('text') for n in hit if n.get('text') is not None]
        if 'equals' in item:
            ok = item['equals'] in texts
            add(f'글자 = 「{item["equals"]}」: {describe(item["select"])}', ok, f'실제 {texts[:3]}')
        if 'contains' in item:
            ok = any(item['contains'] in t for t in texts)
            add(f'글자 ⊃ 「{item["contains"]}」: {describe(item["select"])}', ok, f'실제 {texts[:3]}')
    for item in expect.get('order', []):
        for check, ok, detail in check_order(item, nodes, prior):
            add(check, ok, detail)
    return out


# --- 좌표 -----------------------------------------------------------------
def to_pixels(rect, geometry, image_size):
    """게임 좌표 rect [x,y,w,h](원점 왼쪽 아래) → 캡처 픽셀 [x,y,w,h](원점 왼쪽 위).
    캡처는 프레임 전체다. 게임 화면(visibleSize)은 비율을 지킨 채 가운데 놓인다(iPad 는 위아래 레터박스)."""
    vx, vy = geometry.get('visibleOrigin', [0, 0])
    vw, vh = geometry['visibleSize']
    iw, ih = image_size
    s = min(iw / vw, ih / vh)
    ox, oy = (iw - vw * s) / 2, (ih - vh * s) / 2
    x, y, w, h = rect
    return [round(ox + (x - vx) * s), round(oy + (vh - (y - vy) - h) * s), round(w * s), round(h * s)]


def text_signature(nodes, exclude_selectors=()):
    """정답지와 비교할 글자 목록. 숫자가 든 글자(재화·시간·MID·개수)는 데이터라서 뺀다.
    exclude_selectors(바뀌는 영역 mask)에 걸리는 노드의 글자도 뺀다 — 목록 내용이 달라도 되는 영역이다."""
    skip = set()
    for sel in exclude_selectors:
        skip.update(id(n) for n in select(nodes, sel))
    out = set()
    for n in nodes:
        t = n.get('text')
        if t and not DIGIT.search(t) and id(n) not in skip:
            out.add(f'{n.get("owner") or "-"} | {t}')
    return sorted(out)


def dynamic_masks(nodes, extra_selectors=()):
    """마스크할 게임 좌표 rect — 숫자가 든 글자 노드 + 케이스가 지정한 노드."""
    rects = []
    for n in nodes:
        if n.get('rect') and n.get('text') and DIGIT.search(n['text']):
            rects.append(n['rect'])
    for sel in extra_selectors:
        rects += [n['rect'] for n in select(nodes, sel) if n.get('rect')]
    return rects
