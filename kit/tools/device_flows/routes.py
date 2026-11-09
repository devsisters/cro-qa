"""여러 플로우가 함께 쓰는 경로. 새 플로우는 여기 있는 경로로 화면 근처까지 간 뒤 자기 단계만 적는다.
경로를 더할 때는 SCREENS.md 의 대응표도 함께 고친다."""
import time

from flowlib import FlowFailure

PRESET = 'gb-qa-126'
LOBBY = 'SceneNavigator'


def to_lobby(dev, preset=None, timeout=1800):
    """앱을 띄운 직후 어디서든 로비까지: 프리셋 → 다운로드 확인 → 약관(필수만) → 튜토리얼(Super User + Skip)
    → 첫 실행 팝업·이벤트 화면 닫기. 리소스 다운로드가 길어 timeout 이 크다."""
    preset = preset or PRESET
    end = time.time() + timeout
    calm = 0
    unknown = {}
    while time.time() < end:
        sc = dev.scene()
        if sc == 'PopServerSelect':
            # 재시작 직후에는 프리셋 목록이 아직 비어 있을 수 있다 — 이름이 나올 때까지 기다린다
            select_preset(dev, preset)
            dev.tap('시작!', 'preset start')
        elif sc == 'PopBrownOneButton':
            # 다운로드 확인(「확인」)과 서버 응답 시간 초과(「OK」)가 같은 팝업이다 — 글자 말고 버튼 이름으로 누른다
            if dev.find(inst='_btnConfirm'):
                dev.tap('_btnConfirm', 'one-button popup')
            elif dev.close_popup(sc) is None:
                time.sleep(2)
        elif sc == 'PopGameAgreeKor':
            dev.tap('checkBtn1', 'agree terms'); dev.tap('checkBtn2', 'agree privacy'); dev.tap('시작', 'agree start')
        elif sc == 'SceneTutorialMaster':
            _skip_tutorial(dev)
        elif sc == 'Title':
            skip_title_movie(dev)
        elif sc == LOBBY:
            # 공지·이벤트 팝업은 로비가 뜨고 몇 초 뒤에 올라온다. 로비가 한동안 그대로일 때만 도착으로 본다
            calm += 1
            if calm >= 4:
                return
            time.sleep(2)
            continue
        elif sc and sc not in ('Title', None):
            # 팝업이 열리는 중이면 닫기 버튼이 아직 트리에 없다. 같은 화면에서 몇 번 더 본 뒤에 포기한다
            if dev.close_popup(sc) is None:
                unknown[sc] = unknown.get(sc, 0) + 1
                if unknown[sc] >= 5:
                    raise FlowFailure('NOT_REACHED', 'to_lobby', f'닫는 법을 모르는 화면 {sc}')
        calm = 0
        time.sleep(3)
    raise FlowFailure('NOT_REACHED', 'to_lobby', f'{timeout}s 안에 로비에 오지 못했다 (scene={dev.scene()})')


def select_preset(dev, preset, timeout=30):
    """서버 선택 창에서 프리셋을 고른다. 목록은 화면 밖 항목까지 트리에 있으므로, 목록 영역 안에 들어올 때까지
    목록을 끌어 올리거나 내린 뒤 누른다. 목록은 서버 응답이 오면 다시 그려진다 — 위치가 두 번 연속 같을 때만 누르고,
    누른 뒤 선택된 항목(불투명 255)이 그 프리셋인지 확인한다. 다른 칸이 눌렸으면 다시 고른다."""
    def read():
        ns = dev.tree().get('nodes', [])
        items = [n for n in ns if n.get('name') == 'preset']
        target = next((n for n in items if n.get('text') == preset), None)
        area = next((n for n in ns if n.get('inst') == '_gNodePresetList'), None)
        chosen = next((n.get('text') for n in items if n.get('opacity') == 255), None)
        return target, area, chosen

    end = time.time() + timeout
    prev = None
    for _ in range(60):
        target, area, chosen = read()
        if chosen == preset and target:
            return
        if not (target and area):
            if time.time() > end:
                raise FlowFailure('NAME_MISSING', 'preset list', f'프리셋 「{preset}」이(가) 서버 선택 목록에 없다')
            time.sleep(1.5)
            continue
        ax, ay, aw, ah = area['rect']
        tx, ty, tw, th = target['rect']
        cy = ty + th / 2
        if ay + th / 2 <= cy <= ay + ah - th / 2:
            if prev == target['rect']:
                dev.tap_node(target, f'preset {preset}')
                time.sleep(0.8)
            prev = target['rect']
            time.sleep(0.5)
            continue
        prev = None
        # 좌표는 아래가 0 이다. 항목이 영역 아래에 있으면 목록을 위로 끌어 올린다. 관성이 붙지 않게 천천히 끈다
        step = min(abs(cy - (ay + ah / 2)), ah * 0.7)
        x = ax + aw / 2
        y1, y2 = (ay + ah * 0.15, ay + ah * 0.15 + step) if cy < ay else (ay + ah * 0.85, ay + ah * 0.85 - step)
        dev.swipe(x, y1, x, y2, ms=900)
        time.sleep(0.8)
    raise FlowFailure('NOT_REACHED', 'preset list', f'프리셋 「{preset}」을(를) 고르지 못했다')


def skip_title_movie(dev):
    """제목 화면 영상 — 「다시 보지 않기」가 꺼져 있으면 켜서 다음 실행부터 나오지 않게 하고, 재생 중이면 화면을 눌러 넘긴다.
    체크 표시(_spriteDontShowAgainCheck)는 꺼져 있으면 트리에 나오지 않는다. 영상이 없는 빌드·서버면 버튼도 없다."""
    ns = dev.nodes()
    has = lambda inst: any(n.get('inst') == inst for n in ns)
    if has('_btnDontShowAgain') and not has('_spriteDontShowAgainCheck'):
        dev.tap('_btnDontShowAgain', 'title movie dont-show-again')
    if any('VideoPlayer' in str(n.get('type')) for n in ns):
        w, h = dev.visible_size()
        dev.tap_xy(w / 2, h / 2, 'title movie skip')


def _skip_tutorial(dev):
    """튜토리얼 디버그 토글 두 개를 켠다(opacity 255 = 켜짐) 뒤 「탈출시키기」."""
    ns = dev.nodes()
    for inst in ('_btnSuperUser', '_btnSkipTutorial'):
        n = next((x for x in ns if x.get('inst') == inst), None)
        if n and n.get('opacity') != 255:
            dev.tap(inst, f'tutorial {inst}')
    dev.tap('_btnEscape', 'tutorial escape')
    time.sleep(8)


def lobby_to_gacha(dev, tab_inst):
    """로비 → 뽑기 → 왼쪽 탭(tab_inst: _btnTresure·_btnSkin·_btnJellySkin·_btnSpell·_btnIcing)."""
    for attempt in range(3):
        sc = dev.scene()
        if sc != LOBBY:
            # 늦게 뜬 팝업이 있으면 닫고 다시 시도한다
            if dev.close_popup(sc) is None:
                raise FlowFailure('NOT_REACHED', 'lobby → gacha', f'닫는 법을 모르는 화면 {sc}')
            time.sleep(2)
            continue
        try:
            dev.tap('_btnShopGacha', 'lobby → gacha')
            dev.wait(lambda: dev.find(inst=tab_inst), 10, 'gacha open', tab_inst)
            break
        except FlowFailure:
            if attempt == 2:
                raise
            time.sleep(2)
    dev.tap(tab_inst, f'gacha tab {tab_inst}')
    time.sleep(3)


def back_to_lobby(dev):
    """팝업을 닫고 상태바의 홈 버튼으로 로비로 간다. 로비면 홈 버튼이 없거나 눌러도 그대로다."""
    for _ in range(5):
        sc = dev.scene()
        if sc == LOBBY:
            break
        if dev.close_popup(sc) is None:
            raise FlowFailure('NOT_REACHED', 'back_to_lobby', f'닫는 법을 모르는 화면 {sc}')
        time.sleep(2)
    if dev.find(inst='_btnHome'):
        dev.tap('_btnHome', 'home')
        time.sleep(3)

    def ready():
        # 홈으로 오면 이벤트 화면(점핑 이벤트 등)이 다시 뜰 수 있다 — 닫으면서 기다린다
        sc = dev.scene()
        if sc != LOBBY:
            dev.close_popup(sc)
            time.sleep(2)
            return False
        b = dev.find(inst='_btnShopGacha')
        return b and not b[0].get('blockedBy')
    dev.wait(ready, 30, 'back_to_lobby', '덮이지 않은 로비 뽑기 버튼')


def refresh_user_info(dev):
    """서버 계정 데이터를 앱에 다시 읽힌다(재시작 없이). 화면을 대각선으로 드래그하면 디버그 콘솔(PopDebugSetting)이
    열리고 「유저 정보 갱신」을 누른다. 콘솔은 다른 버튼이 없는 배경을 눌러 닫는다 — logout 등 위험한 버튼이 있어
    아무 데나 누르지 않는다."""
    w, h = dev.visible_size()
    dev.swipe(20, 20, w - 20, h - 20, 600)
    dev.wait(lambda: dev.find(owner='PopDebugSetting', text='유저 정보 갱신'), 10, 'debug console', '「유저 정보 갱신」')
    dev.tap('유저 정보 갱신', 'refresh user info')
    time.sleep(3)
    ns = dev.nodes()
    rec = [n for n in ns if n.get('owner') == 'PopDebugSetting' and n.get('receiver') and n.get('rect')]
    background = [n for n in rec if n['rect'][2] >= w * 0.9]
    others = [n for n in rec if n not in background]

    def free(x, y):
        return not any(r['rect'][0] <= x <= r['rect'][0] + r['rect'][2] and r['rect'][1] <= y <= r['rect'][1] + r['rect'][3]
                       for r in others)
    point = next(((x, y) for y in (5, 15, 25) for x in range(int(w / 2), int(w) - 10, 20) if free(x, y)), None)
    if not background or point is None:
        raise FlowFailure('NOT_REACHED', 'close debug console', '닫을 빈 자리를 찾지 못했다')
    dev.tap_xy(point[0], point[1], 'close debug console')
    dev.wait(lambda: not dev.find(owner='PopDebugSetting'), 10, 'close debug console', '디버그 콘솔 닫힘')
