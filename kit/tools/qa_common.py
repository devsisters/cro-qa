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
ORDER = ['ERROR', 'FAIL', 'REVIEW', 'UNSURE', 'PASS', 'NOT_RUN']


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
def check_expect(expect, scene, nodes):
    """expect 를 트리로 판정한다 → [{'check','ok','detail'}]. 모델을 쓰지 않는다."""
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


def text_signature(nodes):
    """정답지와 비교할 글자 목록. 숫자가 든 글자(재화·시간·MID·개수)는 데이터라서 뺀다."""
    out = set()
    for n in nodes:
        t = n.get('text')
        if t and not DIGIT.search(t):
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
