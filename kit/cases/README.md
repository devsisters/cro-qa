# 케이스 파일 형식

`cases/<묶음>.json` 하나가 테스트 시트 하나(또는 탭 하나)다. `tools/sheet_import.py` 가 뼈대를 만들고 Claude 가 `auto`·`steps` 를 채운다.
검사: `python3 tools/case_runner.py cases/<묶음>.json --check`. 샘플: `sample-mycookie-gacha.json`.

```json
{
 "suite": "v126-basic",                 // 폴더 이름으로 쓴다(영문 소문자·숫자·-·_)
 "sheet": "https://docs.google.com/…",   // 원본 시트 링크
 "preset": "gb-qa-126",                 // 첫 화면 「프리셋 환경설정」에서 고를 이름
 "server": "gb-qa-126",                 // 마카롱·타임머신 서버(보통 프리셋과 같다) — state·server_time 단계에 필요
                                        // 실행할 때 `--preset`(QA 앱의 서버 프리셋)을 주면 그 이름이 server 를 덮는다 — 테스트 중인 서버의 마카롱을 연다
 "mid": "",                             // 비우면 화면의 MID 라벨에서 읽는다
 "time_ok": false,                      // 서버 시간을 바꿔도 되는 서버인지(같이 쓰는 사람과 합의)
 "sheetTab": "14.40N", "layout": {…}, "statusMap": {…},   // 결과를 원본 시트에 다시 쓸 때(sheet_import 가 layout 을 채운다)
 "cases": [
  {
   "id": "TC-001", "sheet_row": 12, "title": "대분류 / 중분류 / 항목",
   "sheet": {"pre": "…", "steps": "…", "expected": "…"},   // 시트 원문(고치지 않는다)
   "auto": true,                         // true · false(+ reason) · null(아직 안 정함 — 실행 불가)
   "reason": "",                         // auto=false 인 이유
   "spends": false,                      // 재화를 쓰면 true — --allow-spend 일 때만 돈다
   "start": "lobby",                     // lobby(로비로 돌아와서) · relaunch(앱 재시작) · here(지금 화면)
   "note": "",                           // 트리로 옮기지 못한 기대 등 메모
   "plan": {"class": "화면|상태|시간|플레이|수동", "needs": "…"},   // 자동화 구분과 필요한 조건(케이스를 쓰기 전 분류)
   "steps": [ … ]
  }
 ]
}
```

## 선택자 — 노드를 가리키는 법

- 문자열: `"_btnClose"` · `"확인"` — inst(ccb 인스턴스 이름) · name · 화면 글자 중 하나가 같은 노드
- 객체: `{"owner": "PopShopGachaProbability", "inst": "_btnTabIcing"}` — 키를 모두 만족하는 노드
  - 키: `inst` · `name` · `text` · `owner`(소속 화면) · `type` · `text_contains` · `any`
- 보이는 노드(잘리지 않고 화면 안)만 대상이다

이름은 `tools/device_flows/SCREENS.md` 에서 먼저 찾고, 없으면 `gb_device.py tree` 로 확인한다.

## 단계(steps)

| do | 필드 | 동작 |
|---|---|---|
| `tap` | `target`(이름·글자), `index`? | 이름으로 누른다. 같은 이름이 여럿이면 가장 위의 덮이지 않은 것. 덮였으면 BLOCKED, 없으면 NAME_MISSING |
| `tap_select` | `select`(선택자), `index`?(기본 -1 = 마지막) | 선택자로 찾은 노드 가운데를 누른다(owner 로 좁힐 때) |
| `tap_xy` | `x`, `y` | 게임 좌표(원점 왼쪽 아래) 또는 `"50%"` 같은 화면 비율. 이름 없는 바깥 탭·커튼에만 쓴다 |
| `swipe` | `x1`·`y1`·`x2`·`y2`(숫자 또는 %), `ms`? / `preset: "diagonal"` | 드래그. diagonal = 디버그 콘솔 열기 |
| `back` | — | `_btnBack` 을 누른다 |
| `wait_scene` | `scene`(문자열 또는 배열), `timeout`? | 최상단 화면이 그것이 될 때까지(2초 유지) |
| `wait` | `select`, `timeout`? | 노드가 나타날 때까지 |
| `wait_gone` | `select`, `timeout`? | 노드가 사라질 때까지 |
| `sleep` | `s` | 초 |
| `close_popup` | `owner`?(기본: 지금 화면) | 그 팝업의 닫기 버튼(_btnClose·_btnNo·닫기·확인·오른쪽 위 작은 버튼) |
| `route` | `name`, `args`? | 공통 경로: `to_lobby` · `back_to_lobby` · `lobby_to_gacha`(args: 탭 inst) · `refresh_user_info` |
| `checkpoint` | `name`, `expect`?, `mask`?, `image`?(기본 true), `settle`?(기본 1초), `device`? | **판정 지점.** 화면이 멈출 때까지(트리가 연속 두 번 같을 때까지, 최대 `settle` 초) 기다린 뒤 트리·캡처를 남기고 expect·정답지로 판정한다. `device`: `{"aos": {"model": ["SM-S921B"], "os": ["14"]}, "ios": {"model": ["iPad7,4"], "os": [">=17"]}}` — 이 기기(모델 또는 판매명, OS 는 그 버전·`>=`·`<=`)에서 돌릴 때만 판정한다. 아니면 그 지점은 NOT_RUN 이고, 케이스는 모든 지점이 그러면 NOT_RUN · 일부만 그러면 UNSURE(Check). 실행 기기의 모델·OS 는 results.json `deviceInfo` 에 남는다 |
| `state` | `path`, `value` 또는 `op: "remove"`, `restore`?(기본 false), `refresh`?(기본 true), `max_refs`? | 마카롱으로 계정 필드를 바꾸거나(`value`) 배열 항목을 뺀다(`op: remove`, 경로에 `@id=N` 으로 항목 지정). 「유저 정보 갱신」으로 반영. 이미 그 상태면 저장하지 않는다. 되돌리지 않는 것이 기본. `max_refs`: 항목 id 가 문서에 그보다 많이 나오면(장착 등) 빼지 않는다. 파일 머리 `server` 필요 |
| `scroll_find` | `select`, `max`?(기본 40), `band`?, `list`?, `page`?(기본 0.8), `swipe`? | 목록에서 대상이 화면 안(band 높이 범위)에 나올 때까지 찾는다. 게임 브리지의 `scroll` 로 목록 처음부터 한 쪽(`page` × 보이는 높이)씩 관성 없이 넘기고, 찾으면 띠 가운데로 옮긴다. 끝에 닿으면 바로 실패한다. `list`: 이 이름의 노드가 든 목록(없으면 화면에서 가장 넓은 목록). 브리지에 `scroll` 이 없는 예전 빌드면 `swipe` 로 손가락처럼 넘긴다 |
| `server_time` | `to`(`"+1d"`·`"+2h30m"`·`"2026-11-14 00:00"`), `relaunch`?(기본 true) | 서버 시간 변경 후 앱 재시작·로비. 파일 머리 `time_ok: true` + 실행기 `--allow-time` 일 때만 돈다 |
| `play` | `timeout`?(달린 시간, 기본 600초), `start_timeout`?(기본 180초) | 인게임 한 판을 자동 달리기로 끝까지 달린다. 인게임 진입(시작 버튼 누르기)은 앞 단계가 한다. 시작을 기다린 뒤 결과 화면(`Result` 가 든 화면)이 나올 때까지 게임 AutoRewind 이벤트를 모으고, `timeout` 을 넘으면 그만두기로 끝낸다. 주자가 여럿인 모드(릴레이 등)는 다음 주자가 시작되면 계속 기다리고 마지막 주자 뒤 결과 화면에서 끝난다(`timeout` 은 주자 한 명 기준). 결과의 `plays` 에 주자별 끝난 방식·달린 초·젤리, 충돌·부활·구멍 구출·이어달리기 횟수가 남는다. 파일 머리 `autoplay`(자동 달리기 input) 필요 — 기본 기능 실행기는 `presets/basic-play.json` 을 넣는다 |

모든 단계에 `label`(로그에 쓸 이름), `after`(단계 뒤 기다릴 초)를 붙일 수 있다. `timeout` 기본 15초.

기다리기는 실행기가 한다 — 고정 시간을 쉬지 않고 화면이 멈추면 바로 다음으로 간다. 그래서 `after`·`sleep` 은 보통 필요 없다.
- 화면을 바꾸는 단계(`tap`·`back`·`swipe`·`route`·`state` 등) 뒤에는 트리(위치·글자·투명도·보임)가 연속 두 번 같을 때까지, 최대 `settle` 초(기본 2초) 기다린다.
- `tap`·`tap_select`·`back` 은 누를 노드가 아직 없거나 덮여 있으면(화면 전환 중) `find_wait` 초(기본 5초) 동안 다시 시도한다.
- 「액션마다 캡처」는 사람이 흐름을 볼 때만 켠다(한 장에 1~2초). 꺼도 실패한 단계는 캡처가 남는다.

`when` — 조건이 맞을 때만 그 단계를 한다(checkpoint 제외). 앱에 저장되는 토글처럼 시작 상태가 실행마다 다를 때 맞춰 놓는 데 쓴다. 건너뛴 단계는 결과의 `skipped` 에 남는다.
`{"do": "tap", "target": "마이쿠키 앞으로 정렬", "when": {"present": "_spriteMyCookieFirst"}}` — 체크 표시가 있을 때만 눌러 끈다. `{"absent": 선택자}` 도 된다.

## expect — 시트의 기대 결과를 트리 조건으로

| 키 | 값 | 통과 조건 |
|---|---|---|
| `scene` | 문자열 · 배열 | 최상단 화면 이름이 그것 |
| `present` | 선택자 배열 | 모두 있다 |
| `absent` | 선택자 배열 | 모두 없다 |
| `tappable` | 선택자 배열 | 있고, 터치를 받고(receiver), 덮이지 않았고, 비활성이 아니다 |
| `disabled` | 선택자 배열 | 있고 모두 enabled=false (예: 이미 선택된 탭) |
| `count` | 선택자 + `min`·`max` | 개수가 범위 안 |
| `text` | `{"select": 선택자, "equals": "…"}` 또는 `"contains"` | 그 노드의 글자 |
| `order` | `{"select": 선택자, "first": […], "notFirst": […], "sameAs": "<앞 checkpoint>", "ignore": […]}` | 선택자에 맞는 글자들을 화면 순서(위 줄부터, 줄 안에서 왼쪽부터)로 본다. `first`: 맨 앞부터 이 글자들 · `notFirst`: 맨 앞이 이 글자가 아님 · `sameAs`: 같은 케이스의 앞선 checkpoint 와 순서가 같음(`ignore` 글자를 양쪽에서 뺀 뒤 화면에 보이는 겹치는 앞부분만 비교) |

시트에 적힌 기대만 옮긴다. 「~가 정상적으로 보인다」처럼 트리로 옮길 수 없는 것은 정답지 이미지 비교에 맡긴다.

## mask — 정답지 비교에서 뺄 영역

숫자가 든 글자 노드(재화·시간·MID·개수)는 자동으로 빠진다. 그 밖에 바뀌는 영역(랜덤 결과·계정마다 다른 목록·배너)은 선택자로 적는다.
`"mask": [{"owner": "CellShopGachaIcingOpen"}]`

연출(그리기·커튼)처럼 매번 다른 화면은 `"image": false` 로 이미지 비교를 끈다(캡처도 남기지 않는다). 캡처는 남기고 비교만 끄려면 `"image": "capture"` — 판정은 expect 로만 하고, 캡처는 결과(시트 결과 칸 등)에 근거로 붙는다.


## rewind — 인게임 자동 되감기 (`tools/rewind_runner.py`)

```json
{"suite": "…", "kind": "rewind", "cases": [{
  "id": "RW-01", "title": "…",
  "map": "aaaa0001",                      // 테스트 맵 목록의 이름
  "plays": 3,                               // 같은 케이스를 몇 판
  "seed": 1,                                // 랜덤 카드 시드. 비우면 실행할 때마다 새로 뽑는다. 판 시드 = seed + 판번호 - 1 (리포트 「카드 시드」)
  "cards": {"cookie1": 100100, "cookie2": "random", "pet": "random",
            "treasures": [300100, "random", 0]},   // id · "random" · 0(보물 빈칸)
  "target": "latest",                       // latest(가장 최근 선택 가능 체크포인트) · oldest
  "triggers": [{"type": "afterRevive", "delaySec": 3, "count": 1},
               {"type": "interval", "delaySec": 10, "count": 2}],
  "timeoutSec": 300,                         // 한 판 제한(넘으면 ERROR — 멈춤 의심)
  "input": {"mode": "random", "seed": 7,     // 랜덤 입력 시드. 비우면 실행할 때마다 새로. 판 시드 = seed + 판번호 - 1 (리포트 「입력 시드」)
            "actionsPerSec": 0.8,             // 점프·슬라이드 시작 빈도(초당)
            "slideRatio": 0.3, "doubleJumpRatio": 0.4,
            "abilityEverySec": 8,             // 능력·스펠·축복 버튼을 몇 초마다 누를지(0 = 안 누름)
            "rescue": true,                   // 구멍 구출 창이 뜨면 1초 뒤 누른다(빼면 true, 오프라인 판만)
            "relay": true}                    // 이어달리기 창이 뜨면 1초 뒤 고른다(빼면 true, 오프라인 판만)
// input.mode: random(랜덤으로 누름) · smart(앞의 장애물·구멍·젤리를 보고 점프·슬라이드를 고른다. mistakeRatio 0~1 만큼 일부러 놓친다, 기본 0.15) · none
}]}
```

- 카드 id 목록: `python3 tools/gb_device.py testmode --platform ios --device <ID> --checkout "$PWD/workspace" --json '{"op":"cards","category":"treasure"}'`
- 맵 목록: 같은 명령에 `{"op":"maps"}`
- 이벤트 원본: `runs/<…>/<케이스>/play<N>/events.json` — `checkpoint` · `revive` · `bonus_enter` · `bonus_return` · `rewind_request` · `rewind_done` · `rewind_skip(reason)` · `rewind_fail(detail)` · `state_mismatch(필드=기대/실제)` · `game_over`
- 입력은 화면 버튼과 같은 경로(PlayerControlManager)로 들어가 리플레이에 기록된다. 능력 발동으로 버튼이 스페셜 버튼으로 바뀌어도 게임이 그 상태에 맞게 해석한다. 실패한 판은 리포트의 「카드 시드」·「입력 시드」를 각각 `seed`·`input.seed` 에 넣고 `plays: 1` 로 다시 돌리면 같은 입력이 들어간다(같은 카드·같은 맵일 때)
- `input` 이 없거나 `mode: none` 이면 아무 버튼도 누르지 않는다
