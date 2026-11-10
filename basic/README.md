# 기본 기능 — 버전별 기본기능 시트

QA 앱 「기본 기능」 탭이 쓰는 자료다. 시트 원본은 `sheet.json` 의 링크(CRO_버젼별 기본기능)이고, 이 폴더는 앱과 에이전트가 읽는 사본·규칙이다.

| 파일 | 내용 |
|---|---|
| `sheet.json` | 시트 링크·ID, TC 탭 이름. 앱은 항상 이 시트를 읽는다 |
| `tc.json` | TC 탭 사본. 앱 「시트에서 다시 읽기」가 고친다(`tools/basic_sheet.py tc`) |
| `scenarios/` | 자동화 시나리오. 대분류 하나에 하나, 모드리스트만 중분류마다 하나(`sheet.json` 의 `splitBySub`) |

## TC 탭 형식

한 줄이 TC 하나다. 병합 셀이 없고 1행이 헤더다. **열 이름으로 읽는다** — 열 순서를 바꿔도 되지만 이름은 바꾸지 않는다.

| 열 | 뜻 |
|---|---|
| ID | `TC-001` 형식. 결과 탭과 자동화 케이스가 이 ID 로 TC 를 찾는다. 행을 옮겨도 ID 는 그대로 둔다. 새 TC 는 다음 번호를 쓴다 |
| 대분류 · 중분류 · 중요도 | 원본 TC_Backup 그대로(병합을 풀어 줄마다 채웠다) |
| 확인 내용 | 원본 CheckList 문구 |
| 판정 항목 | 확인 내용을 하나씩 판정할 수 있게 나눈 것. **한 줄이 판정 하나다.** 자동화하면 한 줄이 채점 지점 하나가 된다 |
| 자동화 구분 | 화면 · 상태 · 시간 · 플레이 · 수동 (헤더 메모에 뜻) |
| 사전 조건 | 확인 전에 갖춰야 할 계정·서버 상태 |
| 비고 | 원본과 다르게 옮긴 점, 확인이 필요한 점 |

## 시나리오 파일

`scenarios/<대분류>.json`, 나누는 대분류는 `scenarios/<대분류>/<중분류>.json`(이름의 `/` `\` `:` 는 `_`). 빈 파일은 `python3 tools/basic_scenario.py new "<대분류>" ["<중분류>"]` 로 만든다.
QA 앱에서는 시나리오 단위로 골라 돌리고, 판정과 결과 탭 기록은 TC 단위다.

```json
{
 "area": "쿠키 인벤토리", "sub": "",
 "start": "lobby",
 "server": "gb-qa-126",
 "setup": [ {"do": "state", "op": "remove", "path": "inventory.pets.@id=201800", "max_refs": 2} ],
 "entry": [ {"do": "tap", "target": "_btnMyCookie"}, {"do": "wait", "select": {"inst": "_btnTabCookie"}} ],
 "segments": [
  {"tc": "TC-028", "steps": [ {"do": "checkpoint", "name": "tabs", "expect": {…}} ]},
  {"tc": "TC-029", "steps": [ … ]},
  {"tc": "TC-035", "steps": [], "reason": "다른 계정(친구) 필요 — 사람이 확인"}
 ],
 "notes": [ {"at": "2026-11-10", "by": "담당자", "text": "교정·유의사항 그대로"} ]
}
```

- 실행 순서: `start` → `setup`(마카롱 상태 등) → `entry`(이 화면까지 들어가기) → 첫 구간 → 다음 구간 …
- **다음 구간은 앞 구간이 끝난 화면에서 이어 간다.** 구간을 쓸 때 앞 구간이 어디서 끝나는지 보고, 필요하면 탭 누르기·뒤로 가기로 시작한다.
- 앞 구간이 진행에 실패하면(화면 이동·연결) 그 TC 만 `Block` 이 된다. 다음 구간은 `start` → `setup` → `entry` 부터 다시 들어간다. 앞 TC 실패가 뒤 TC 를 실패로 만들지 않는다.
- `fresh: true` 인 구간은 앞 구간과 상관없이 처음(`start` → `setup` → `entry`)부터 들어간다.
- 판정 항목 한 줄이 `checkpoint` 하나다. 단계 종류·선택자·조건은 `kit/cases/README.md` 「단계」 절을 따른다.
- 사전 조건이 특정 기기(최저사양·최신 OS 등)면 그 줄의 `checkpoint` 에 `device` 를 적는다. 다른 기기에서 돌리면 그 줄은 판정하지 않고, 근거 칸에 줄마다 「통과(기기)」·「확인 안 함(기기)」을 적는다. 실행 칸에 실행 기기 모델·OS 가 붙는다.
- 단계가 없는 구간은 돌리지 않는다(결과 탭 칸을 건드리지 않아 `N/T` 그대로). 자동화하지 않는 이유는 `reason` 에 적는다.
- `notes` 는 지우지 않고 쌓는다.

돌리기(키트 폴더에서):

```bash
python3 tools/basic_run.py "../basic/scenarios/쿠키 인벤토리.json" --check                        # 형식만
python3 tools/basic_run.py "../basic/scenarios/쿠키 인벤토리.json" --platform aos --version 14.50   # 기기에서
```

결과는 `kit/runs/basic-<버전>-<플랫폼>-<시각>/` 이다. 리포트는 시나리오 아래에 TC 별로 쓴다.

## 결과 탭 형식 — 버전마다 하나(`14.50` 등)

1행이 헤더다. 열 순서가 형식이다(`tools/basic_sheet.py` 의 `RESULT_HEADER`).

| 열 | 쓰는 쪽 | 값 |
|---|---|---|
| A ID ~ F 자동화 구분 | 탭을 만들 때 TC 탭에서 복사 | 그 버전 시점의 TC. 나중에 TC 탭이 바뀌어도 이 탭은 그대로다 |
| G AOS · J iOS | 자동 실행 또는 사람 | `Pass` · `Fail` · `Block` · `Check` · `N/T` |
| H AOS 근거 · K iOS 근거 | 자동 실행 | 지점별 판정. 실패한 조건, 사람 확인할 것 |
| I AOS 실행 · L iOS 실행 | 자동 실행 | `시각 · 실행자 · 실행 폴더`. **이 칸이 차 있으면 자동 결과다** |
| M QA 메모 | 사람만 | 에이전트는 쓰지 않는다 |
| O~Q | 탭을 만들 때 | 결과별 개수(COUNTIF 수식) |

판정 → 결과 값: 통과 `Pass` · 실패 `Fail` · 진행 실패(화면 이동·연결) `Block` · 확인 필요·사람 확인 `Check` · 안 돌림 `N/T`.
캡처는 시트에 넣지 않는다. 실행 칸의 폴더(돌린 사람 컴퓨터의 `kit/runs/…`)에 있다.

## 결과 쓰기 — 에이전트 절차

QA 앱 리포트의 「시트에 결과 쓰기」가 앱 안 Claude 에게 이 절차를 시킨다. 시트 읽기·쓰기는 Google Sheets 연결 도구(`get_spreadsheet` · `get_values` · `update_values` · `update_spreadsheet`)로 한다. 칸을 정하는 것은 도구가 하고, 에이전트는 도구가 준 범위·값을 **그대로** 쓴다.

```bash
cd kit
```

1. 탭이 있는지 본다 — `get_spreadsheet`(fields `sheets.properties.title`, `sheets.properties.sheetId`).
2. 없으면 만든다.
   - `python3 tools/basic_sheet.py add-tab --version <버전>` 의 `requests` 를 `update_spreadsheet` 로 보낸다. 응답의 `sheetId` 를 받는다.
   - `python3 tools/basic_sheet.py create --version <버전> --sheet-id <sheetId>` 의 `values` 와 `summary` 를 `update_values` 로, `requests` 를 `update_spreadsheet` 로 보낸다.
3. 지금 값을 읽는다. `get_values` 로 `'<버전>'!A1:A` 와 `'<버전>'!G1:L` 을 읽고, 응답 JSON 을 그대로 `runs/<실행>/sheet-ids.json` · `runs/<실행>/sheet-cols.json` 에 저장한다.
4. 쓸 칸을 정한다.
   `python3 tools/basic_sheet.py update --run runs/<실행> [--run runs/<다른 플랫폼 실행>] --ids runs/<실행>/sheet-ids.json --cols runs/<실행>/sheet-cols.json`
   - `updates` 의 각 `{range, values}` 를 `update_values` 로 쓴다.
   - `skipped` 는 사람이 이미 적은 결과라서 쓰지 않은 것이다. 그대로 보고한다.
   - `appended` 는 탭에 없어서 맨 아래에 추가한 TC 다.
5. 보고: 쓴 TC 수, 플랫폼별 결과 개수, `skipped`·`appended` 목록, 시트 링크.

하지 않는 것: M열(QA 메모)과 `skipped` 칸에 쓰기, 탭·행 지우기, 판정을 에이전트가 바꾸기(도구가 준 값만 쓴다).
