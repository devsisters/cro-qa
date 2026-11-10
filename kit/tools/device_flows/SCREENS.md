# 화면 ↔ ccb·노드 대응표

새 플로우를 짤 때 이미 아는 화면은 여기서 이름을 가져다 쓴다. 실측으로 확인한 것만 적는다.
`scene` 은 `gb_device.py scene` 의 `top`, `owner` 는 트리 노드의 `owner`, 이름은 `inst`(없으면 `name`·글자).
페이지 이동(로비 → 뽑기 → 옷장)은 같은 `SceneNavigator` 안에서 일어나 `scene` 으로 구분되지 않는다 — 화면 고유 노드로 확인한다.

| 화면 | scene | 확인 노드 (owner / 이름) | 주요 버튼 | 확인 날짜 · 플랫폼 |
|---|---|---|---|---|
| 프리셋 선택 | `PopServerSelect` | `_labelTxtPopupTitle`「프리셋 환경설정」 | 행 `preset`(글자 = 프리셋 이름), `_buttonStart`「시작!」 | 2026-11-03 · mac·ios·aos |
| 리소스 다운로드 확인 | `PopBrownOneButton` | `_labelDescription` | `_btnConfirm`「확인」 | 2026-11-03 · mac·ios·aos |
| 약관 동의(새 계정) | `PopGameAgreeKor` | — | `checkBtn1`(이용약관) `checkBtn2`(개인정보) `_btnAgreeDim`「시작」 — 선택 항목(`checkBtn5·6`)은 누르지 않는다 | 2026-11-03 · ios·aos |
| 튜토리얼(새 계정) | `SceneTutorialMaster` | `SceneTutorial004` | 토글 `_btnSuperUser` `_btnSkipTutorial`(opacity 255 = 켜짐), 진행 `_btnEscape`「탈출시키기」 | 2026-11-03 · ios·aos |
| 공지 | `PopNotice` | — | `_btnClose` | 2026-11-03 · 3 |
| 첫 실행 팝업들 | `PopUpdateHighlight` · `PopJukeboxSongGet` · `PopBrownTwoButton`(로비스킨) · `SceneUaJumpingEventMain` | — | 닫기(`_btnClose`·`_btnNo`·오른쪽 위 작은 버튼). `PopUpdateHighlight`(신규 유저 특별 보상)는 닫기 버튼이 없고 글자「Touch!」만 있다 → 화면 가운데 탭 | 2026-11-03 · ios·aos, 2026-11-10 ios |
| 점핑 이벤트(앱 접속 직후) | 안내 화면(`SceneUaJumpingEventMain`, JUMP 버튼 하나 — 글자 JUMP! 가 든 소유 `SceneUaJumpingEventMain` 의 버튼) → 단계 화면(`SceneUaJumpingEventMain`) → `PopUaJumpingEventJumpingRewardInfo` → `SceneLoading` → `PopUaJumpingEventJumpingReward` | 메인: 알림점 노드 `_gNodeBadge`(name `uaJumpingEventJumpReward`, 소유 `CellUaJumpingEventBtnJump`)가 보이는 JUMP 버튼. 보상 정보: `_gNodeBadge1`(`uaJumpingRewardRewardStep`) | 안내 화면의 JUMP → 단계 화면에서 **알림점이 붙은 JUMP**(STEP 1) → 보상 정보의 `_btnRewardable`「보상 받기」→ 로딩 → 「점핑 보상 획득!」의 `_btnConfirm`「확인」 → 메인으로 돌아온다. 잠긴 JUMP(STEP 2, 트로피 500개 등)는 알림점이 없어 누르지 않는다. `routes.claim_jumping_event`(to_lobby 가 부른다)가 하고, 받을 게 없으면 일반 팝업 닫기로 닫는다. **보상을 받으면 계정 상태가 바뀐다 — 테스트 계정이라 받는다(2026-11-10 결정).** 받으면 그 계정에서는 더 뜨지 않는다 | 2026-11-10 · aos(전 단계 확인)·ios |
| 로비 | `SceneNavigator` | `#parent` / `_btnShopGacha` | `_btnShopGacha`「뽑기」, `_btnPlay` | 2026-11-03 · 3 |
| 상태바(로비 밖) | — | `#parent` / `_btnBack` `_btnHome` | — | 2026-11-03 · 3 |
| 뽑기 | `SceneNavigator` | `SceneShopGacha` | 탭 `_btnTresure`(오타 그대로) `_btnSkin` `_btnJellySkin` `_btnSpell` `_btnIcing`, `_btnGachaLog`「최근 상자 내역」, `_btnProbability`「확률 정보」 | 2026-11-03 · 3 |
| 아이싱 뽑기 — 픽업 | `SceneNavigator` | `CCBShopGachaIcingPotContentPickUp` | `_btnInfo`(ⓘ), 셀 `#itemDetailPopupButton`, `_nodeBuyOnce`(1회) `_nodeBuyMulti`(5회), 배너 `_gNodeBanner`, `_btnNext` | 2026-11-03 · 3 |
| 아이싱 뽑기 — 상시 | `SceneNavigator` | `CCBShopGachaIcingPotContentCommon` | `_nodeBuyOnce` `_nodeBuyMulti` | 2026-11-03 · 3 |
| 스페셜 안내 토스트 | — | `ToastShopGachaIcingLimitedInfo` | (바깥 탭으로 닫힘) | 2026-11-03 · 3 |
| 아이템 정보 토스트 | — | `CellCommonItemDetail` / `_labelName` `_labelQuantity` `_labelDescription` | (바깥 탭으로 닫힘) | 2026-11-03 · 3 |
| 최근 상자 내역 | `PopSettingChestLog` | `CellSettingChestLog` / `_labelChestName` | 닫기 = 오른쪽 위 작은 버튼(이름 없음) | 2026-11-03 · 3 |
| 확률 정보 | `PopShopGachaProbability` | `CellShopGachaProbabilityList` | 탭 `_btnTab*`(선택된 탭은 enabled false), 닫기 = 오른쪽 위 | 2026-11-03 · 3 |
| 아이싱 뽑기 연출 | `SceneShopGachaIcingCutscene` | 글자「도안을 그려보세요!」 | `_btnSkip`「건너뛰기」, 그리기 = 화면 가운데 스와이프 | 2026-11-03 · 3 |
| 아이싱 뽑기 결과 | `SceneShopGachaIcingOpen` | 글자「Touch!」(커튼, 고정 우선순위 −1000 리스너) → `CellShopGachaIcingOpen` | 커튼 = 아무 데나 탭, `_btnBuyOnce`(한 번 더), 「확인」 | 2026-11-03 · 3 |
| 마이쿠키 옷장 | `SceneNavigator` | 글자「마이쿠키 옷장」 | `_btnBack` | 2026-11-03 · 3 |
| 디버그 콘솔 | (SceneFlow 밖) | `PopDebugSetting` | 열기 = 화면 대각선 드래그(왼쪽 아래 → 오른쪽 위), 「유저 정보 갱신」, 닫기 = 다른 버튼이 없는 배경. **logout 등 위험 버튼이 있다** | 2026-11-03 · mac |
| 재화 부족 | `PopBrownTwoButton` | 글자「초코청크 초크가 부족합니다.」 | `_btnNo`「취소」, `_btnYes`「상점으로 이동」 | 2026-11-03 · mac |
| 쿠키 인벤토리 | `SceneNavigator` | `SceneCookieList` / 탭 `CellCookieListTabBtn`(선택된 탭에 `nodeSelected`) | 로비 `_btnMyCookie`「쿠키」, 탭 `_btnTabCookie`·`_btnTabPet`·`_btnTabTreasure`·`_btnTabSpell`(수호카드)·`_btnTabRaidModeSkill`(스킬), 카드 `_btnCardSelect`(이름 `_labelCookieName`·`_labelPetTreasureName`, 수호카드 `CellEquipSpell`, 스킬 `CellRaidModeSkillListCard`), 「보유한 것만 보기」 | 2026-11-04 · aos |
| 쿠키·펫 상세 | `SceneNavigator` | `SceneCPTCookieInfo` / `_labelTxtCardName`, 제목 `_labelTitle`「쿠키 자세히 보기」·「펫 자세히 보기」 | `_btnBack`, `_btnStory`, `_btnLevelUpInfo`, `_btnSkin` | 2026-11-04 · aos |
| 점핑 이벤트(홈 이동 시) | `SceneUaJumpingEventMain` | — | 로비 홈으로 돌아오면 다시 뜰 수 있다. `routes.back_to_lobby` 가 닫는다 | 2026-11-04 · aos |
