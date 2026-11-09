"""마이쿠키 아이싱 뽑기 — Figma 2610_마이쿠키뽑기 [FLOW] 페이지.

FIGMA = https://www.figma.com/design/bVLOgyqRuFNRa14PnujLbU/2610_%EB%A7%88%EC%9D%B4%EC%BF%A0%ED%82%A4%EB%BD%91%EA%B8%B0?node-id=0-1
  1:45 1-1 상시 뽑기 · 2:4 1-2 일반 픽업 · 2:10 1-3 스페셜 픽업 · 1:10 기능설명(내역·확률·셀 토스트·재화)
처음 작성 2026-11-03 (macOS·iPad·Android 실측 통과). 데이터 조건으로 못 보는 단계는 SKIPS 에 둔다.
"""
import os
import re
import time

import routes
import states as account_states
from flowlib import FlowFailure

NAME = 'mycookie_icing_gacha'
FIGMA = __doc__.split('FIGMA = ')[1].split()[0]
SKIPS = [
    '1-2 일반 픽업 화면 — QA 서버에 일반 픽업 배너가 있을 때만',
    '재화 부족 공통 팝업 — --states 를 주면 마카롱으로 재화를 50 으로 바꿔 확인하고 되돌린다',
    '아이싱 보유 상한 팝업 — 보유량이 상한 이상인 계정에서만',
    '5회 뽑기 — 재화 500 을 쓴다. --pull5 로만',
]
OWNER_POT = ('CCBShopGachaIcingPotContentPickUp', 'CCBShopGachaIcingPotContentCommon')


def _title(dev):
    return [n.get('text') for n in dev.nodes() if n.get('inst') == '_labelTitle' and n.get('owner') in OWNER_POT]


def _dismiss_toast(dev):
    title = [n for n in dev.nodes() if n.get('inst') == '_labelTitle' and n.get('owner') in OWNER_POT]
    if title:
        dev.tap_node(title[0], 'dismiss toast')
        time.sleep(1)


def _mid(dev):
    # 디버그 빌드의 빌드 정보 라벨(화면마다 이름이 다르다 — labelMid · _labelBuildInfo)에서 읽는다
    label = next((n.get('text') for n in dev.nodes() if (n.get('text') or '').startswith('MID : ')), '')
    m = re.search(r'MID : (\w+)', label)
    if not m:
        raise FlowFailure('NAME_MISSING', 'read MID', 'MID 라벨(「MID : 」)이 트리에 없다')
    return m.group(1)


def run(dev, check, pull=True, states=False):
    """check(step, ok, detail, shot=None) 로 결과를 남긴다. 실패 분류는 flowlib.FlowFailure 가 맡는다."""
    routes.to_lobby(dev)
    routes.lobby_to_gacha(dev, '_btnIcing')
    dev.wait(lambda: _title(dev), 15, 'icing tab', '아이싱 뽑기 제목')
    banners = dev.find(inst='_gNodeBanner')
    check('아이싱 탭 진입', True, f'제목={_title(dev)} 배너={len(banners)}', dev.shot('icing-first'))

    if dev.find(inst='_btnInfo'):
        dev.tap('_btnInfo', '스페셜 안내 ⓘ')
        time.sleep(1)
        t = dev.texts(owner='ToastShopGachaIcingLimitedInfo')
        check('스페셜 픽업 안내 토스트', bool(t), repr(t[:1]), dev.shot('special-toast'))
        _dismiss_toast(dev)

    dev.tap('#itemDetailPopupButton', '아이싱 셀')
    time.sleep(1.5)
    name = dev.texts(owner='CellCommonItemDetail', inst='_labelName')
    check('셀 아이템 토스트', bool(name), repr(name), dev.shot('cell-toast'))
    _dismiss_toast(dev)

    dev.tap('_btnGachaLog', '최근 상자 내역')
    dev.wait_scene('PopSettingChestLog', 10, '최근 상자 내역')
    check('최근 상자 내역 열림', True, '', dev.shot('chestlog'))
    dev.close_popup('PopSettingChestLog')
    dev.wait_scene(routes.LOBBY, 10, '내역 닫힘')

    dev.tap('_btnProbability', '확률 정보')
    dev.wait_scene('PopShopGachaProbability', 10, '확률 정보')
    tab = dev.find(inst='_btnTabIcing')
    # 선택된 탭은 비활성(enabled false) 이다
    check('확률 정보 — 아이싱 탭 선택(아이콘 탭)', bool(tab) and tab[0].get('enabled') is False, '', dev.shot('probability'))
    dev.close_popup('PopShopGachaProbability')
    dev.wait_scene(routes.LOBBY, 10, '확률 닫힘')

    banners = dev.find(inst='_gNodeBanner')
    if len(banners) >= 2:
        dev.tap_node(banners[-1], '상시 배너')
        time.sleep(3)
        check('상시 배너 전환', _title(dev) == ['아이싱 뽑기'], repr(_title(dev)), dev.shot('normal'))

    if states:
        mid = _mid(dev)
        out = os.path.join(dev.out_dir, 'macaron')
        path, value = account_states.RECIPES['icing_token_lack']
        wallet_before = dev.texts(owner='CellStatusStateMyCookieIcingGachaToken')
        with account_states.field(routes.PRESET, mid, path, value, out):
            routes.refresh_user_info(dev)
            check('재화 부족 상태 반영(마카롱 → 유저 정보 갱신)', dev.texts(owner='CellStatusStateMyCookieIcingGachaToken') == [str(value)],
                  repr(dev.texts(owner='CellStatusStateMyCookieIcingGachaToken')))
            dev.tap('_nodeBuyOnce', '재화 부족 상태 1회 뽑기')
            dev.wait_scene('PopBrownTwoButton', 10, '재화 부족 팝업')
            texts = dev.texts(owner='PopBrownTwoButton')
            check('재화 부족 팝업', any('부족' in t for t in texts), repr(texts), dev.shot('lack-popup'))
            dev.tap('_btnNo', '재화 부족 팝업 닫기')
            dev.wait_scene(routes.LOBBY, 10, '재화 부족 팝업 닫힘')
        routes.refresh_user_info(dev)
        check('재화 복원', dev.texts(owner='CellStatusStateMyCookieIcingGachaToken') == wallet_before,
              f'{wallet_before} → {dev.texts(owner="CellStatusStateMyCookieIcingGachaToken")}')

    if pull:
        wallet0 = dev.texts(owner='CellStatusStateMyCookieIcingGachaToken')
        dev.tap('_nodeBuyOnce', '1회 뽑기')
        dev.wait_text('도안을 그려보세요!', 30, '그리기 단계')
        check('재화 충분 → 그리기 연출', True, '', dev.shot('draw'))
        w, h = dev.visible_size()
        dev.swipe(w / 2 - 90, h / 2 + 40, w / 2 + 90, h / 2 - 30, 900)
        dev.wait_text('Touch!', 40, '커튼 터치 대기')
        check('커튼 터치 대기', True, '', dev.shot('touch'))
        dev.tap_xy(w / 2, h / 2, '커튼 열기')
        dev.wait(lambda: dev.texts(owner='CellShopGachaIcingOpen'), 15, '결과', '결과 아이싱 이름')
        got = dev.texts(owner='CellShopGachaIcingOpen')
        wallet = dev.wait(lambda: dev.texts(inst='_labelWallet'), 5, '결과 재화', '결과 화면 재화 라벨')
        check('결과', bool(got), f'{got} 재화 {wallet0}→{wallet}', dev.shot('result'))
        dev.tap('확인', '결과 확인')
        time.sleep(3)
        dev.tap('_btnGachaLog', '내역 다시')
        dev.wait_scene('PopSettingChestLog', 10, '내역 다시')
        rows = dev.texts(owner='CellSettingChestLog')
        check('내역 갱신', bool(rows), repr(rows[:2]), dev.shot('chestlog-after'))
        dev.close_popup('PopSettingChestLog')
        dev.wait_scene(routes.LOBBY, 10, '내역 닫힘')

    dev.tap('옷장', '옷장')
    dev.wait_text('마이쿠키 옷장', 15, '옷장 이동')
    check('옷장 이동', True, '', dev.shot('closet'))
    dev.tap('_btnBack', '옷장 나가기')
    time.sleep(3)
