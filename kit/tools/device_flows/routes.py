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
            dev.wait(lambda: dev.find(name=preset), 20, 'preset list', f'프리셋 「{preset}」')
            dev.tap(preset, 'preset'); dev.tap('시작!', 'preset start')
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
