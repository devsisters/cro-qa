# QA 자동화 테스트 키트 — Claude 작업 지침

**독자: 이 폴더에서 실행된 QA팀 Claude.** 사람이 기능 테스트 시트 링크를 주면 그 케이스를 iPad(iOS)·Android 실기기에서 자동으로 돌리고, 정답지와 비교해 판정하고, 리포트를 만든다.

```
1. 시트 받기   → tools/sheet_import.py → cases/<묶음>.json (케이스 뼈대) → Claude 가 단계·기대값을 채운다
2. 실행        → tools/case_runner.py  (iOS·Android 동시에)
3. 판정        → ① expect(트리 조건) ② 정답지 비교(answers/) ③ 차이만 qa-judge(낮은 모델)
4. 리포트      → tools/report.py → report.md · results.csv · results.tsv
```

## 답하는 말과 명령 쓰는 법 — 앱에서 사람이 보고 있다

- 사람에게 보이는 글(답·진행·결과 보고)은 **한국어**로 쓴다. 코드·명령·로그·식별자는 원문 그대로 둔다.
- Bash 는 **한 번에 명령 하나**만 쓴다. `cd …;`·`&&`·`;`·`|`·`>` 로 잇지 않는다. 앱은 허용 목록을 명령마다 대조하므로, 이은 명령은 허용된 도구가 들어 있어도 막히고 「허락이 필요해 멈춘 작업」 으로 멈춘다.
- 키트 도구는 키트 폴더 기준 `python3 tools/<도구>.py …` 로 부른다. 파일 읽기는 Read, 찾기는 Grep·Glob 으로 한다(`cat`·`sed`·`ls`·`grep` 을 Bash 로 쓰지 않는다).
- 도구 출력이 길면 도구의 저장 옵션(예: `basic_sheet.py create|update --save <파일>`)으로 파일에 쓰고 Read 로 읽는다. `python3 -c` 로 살펴보지 않는다. 임시 파일은 `/tmp` 가 아니라 그 실행 폴더(`runs/<실행>/`)에 둔다.

## 0. 동작 원리 — 먼저 이해할 것

- 게임 **DEBUG 빌드**에는 AgentBridge 가 들어 있다. 게임이 자기 UI 트리(노드 이름·화면 글자·위치·누를 수 있는지·덮였는지)를 JSON 으로 내보내고, 이름으로 누르는 터치를 받는다. 화면을 이미지로 짐작하지 않는다.
- 기기 조작은 전부 `tools/gb_device.py` 로 한다. 케이스 실행기와 플로우 라이브러리도 이 도구를 거친다.
- **판정은 모델보다 트리가 먼저다.** 이미지로만 판단한 「결함 의심」은 샘플 작업에서 5건 모두 오판이었다. 트리로 판정할 수 있는 것은 트리로 판정하고, 이미지 비교는 레이아웃·그림 확인에만 쓴다.
- 사람의 맥 마우스·키보드와 충돌하지 않는다. 입력은 게임 안으로 들어간다.

## 1. 처음 한 번 — 환경 점검

`python3 tools/doctor.py` 를 돌려 FAIL 이 없게 한다. 설치는 사람이 한다(`SETUP.md`). 막힌 항목은 doctor 의 「→」 줄을 그대로 사람에게 전한다.

| 확인 | 안 되면 |
|---|---|
| `tools/device_flows/devices.json` 의 `ios.device`(devicectl Identifier/UDID)·`aos.device`(adb serial) | doctor 출력의 기기 ID 를 넣는다 |
| 앱 설치 | 사람이 CI(Cookiepot) **DEBUG 단계 빌드**를 설치한다. 이 키트는 앱을 빌드·설치하지 않는다 |
| 브리지 | `python3 tools/gb_device.py launch --platform ios --device <ID> --checkout "$PWD/workspace"` 후 `python3 tools/doctor.py --ping` 이 OK. `ping` 이 exit 4 면 릴리즈 빌드다 → DEBUG 빌드를 요청한다 |
| iPad 잠금 | `launch` 가 `Locked` 오류면 사람에게 잠금 해제를 요청한다(자동 잠금 「안 함」 권장). 비밀번호는 다루지 않는다 |
| 프리셋(서버) | 첫 화면 「프리셋 환경설정」에서 고를 이름. 케이스 파일 `preset` 에 넣는다. 모르면 사람에게 묻는다 |

## 2. 시트 받기 → 케이스 파일

### 2-1. 시트를 CSV 로

1. 구글 시트 링크면 `python3 tools/sheet_import.py "<링크>" --suite <묶음이름>` 을 먼저 시도한다. 링크 공개 시트만 받아진다.
2. exit 5(회사 계정 전용)면 Google Drive 연결이 있으면 그것으로 읽어 CSV 로 저장하고, 없으면 사람에게 **[파일 → 다운로드 → CSV]** 를 요청한다. 탭이 여러 개면 테스트할 탭을 묻는다.
3. CSV 로 `python3 tools/sheet_import.py <파일.csv> --suite <묶음이름> --sheet-url "<링크>"`. 출력의 `columns`(어느 열을 무엇으로 읽었는지)를 사람에게 보여 주고, 틀리면 `--map "열이름=필드"` 로 다시 한다.

결과 `cases/<묶음>.json` 의 케이스는 `auto: null`(미정)·`steps: []` 다. 시트 원문은 `sheet` 에 남는다. 형식 정본은 `cases/README.md`.

### 2-2. 케이스마다 자동화 여부를 정한다

**계정 상태 정책(2026-11-04 결정)**: 테스트 계정은 전부 테스트용이다. 케이스에 필요한 상태(재화·보유·미보유·진행도·해금 등)를 마카롱으로 만들 수 있으면 **직접 바꿔서 확인한다**(`state` 단계). 「이 계정은 조건이 안 맞아 확인 못 함」으로 넘기기 전에 마카롱으로 만들 수 있는지 먼저 본다. **바꾼 상태는 되돌리지 않는다**(2026-11-04 결정) — 케이스마다 필요한 상태로 맞추고 시작한다. 이미 그 상태면 저장하지 않고 넘어간다. 되돌려야 하는 케이스만 단계에 `"restore": true`. 마카롱으로 만들 수 없는 조건(다른 계정·결제·서버 일정 등)만 Check·N/T 로 남긴다.

| auto | 언제 |
|---|---|
| `true` | 화면 이동·버튼·글자·팝업·화면 전환으로 확인할 수 있다 |
| `false` + `reason` | 소리·진동·푸시 알림·결제·외부 링크·로그인 연동·계정 상태 조작이 필요함·두 기기 상호작용·시간 경과(일일 초기화 등)·사람 눈 판단(「자연스럽다」 「어색하지 않다」) |

`spends: true` — 재화를 쓰는 케이스. 사람이 허락했을 때만 `--allow-spend` 로 돈다.

### 2-3. 단계와 기대값을 쓴다

1. **이미 아는 화면부터 본다.** `tools/device_flows/SCREENS.md`(화면 ↔ 노드 이름 대응표), `cases/` 의 다른 묶음, `tools/device_flows/flows/`. 아는 경로는 탐색하지 않는다.
2. 처음 보는 화면은 기기 하나에서 탐색한다: `python3 tools/ui_find.py --platform <ios|aos>`(화면 요약), 필요하면 `--owner`·`--text`·`--buttons` 로 좁힌다. 누르기는 `gb_device.py tap --node "<이름 또는 글자>"`.
   **트리 전체를 읽지 않는다** — `gb_device.py tree` 출력이나 실행 결과의 `*.tree.json` 을 통째로 Read 하지 않는다. 한 화면이 수백 노드·수백 KB 라 토큰을 가장 많이 쓰는 곳이다. 지난 실행의 화면은 `ui_find.py --file <…tree.json>` 으로 본다. `ui_find.py` 로 안 되는 것만 `gb_device.py tree` 를 `--max-nodes` 로 작게 받아 본다.
   gb_device.py 명령에는 항상 `--platform ios|android --device <ID> --checkout "$PWD/workspace"` 를 붙인다(checkout 은 **절대 경로**여야 한다). 트리는 커서 파일로 받아 필요한 부분만 본다. 찾은 화면·버튼은 **`SCREENS.md` 에 더한다**(다음 시트에서 탐색이 줄어든다).
3. 시트의 「기대 결과」를 `checkpoint.expect` 의 트리 조건으로 옮긴다. **시트에 적힌 것만** 옮긴다. 시트에 없는 기대를 지어내지 않는다. 트리로 옮길 수 없는 기대(색·모양·연출)는 정답지 이미지 비교에 맡기고 케이스 `note` 에 적는다.
4. 바뀌는 값(재화·남은 시간·랜덤 결과·계정마다 다른 목록)은 `expect` 에 값으로 쓰지 않는다. 숫자가 든 글자는 정답지 비교에서 자동으로 빠지고, 그 밖의 바뀌는 영역은 `mask` 로 뺀다.
5. `python3 tools/case_runner.py cases/<묶음>.json --check` 가 오류 없이 끝나야 한다.
6. 새로 쓴 케이스는 **한 플랫폼에서 `--case <id>` 로 먼저 돌려** 통과시킨 뒤 전체를 돌린다.

케이스 하나가 다른 케이스의 결과에 기대지 않게 쓴다. 기본 시작은 `start: "lobby"`(로비로 돌아와서 시작)이다.

## 2-4. 시트 TC 시나리오 (QA 앱 아웃게임 탭)

QA 앱이 테스트 시트를 탭별 TC 로 읽는다(`tools/sheet_tc.py`). TC 하나의 자동 실행 방법은 저장소 `scenarios/<탭>/<TC 키>.json` 이고 형식은 `scenarios/README.md` 다.
- 앱의 「Claude 와 만들기」가 TC 정보(구간·분류·기대 결과·TC 키·파일 경로)를 넣은 요청을 준다. 위 2-3 순서대로 화면을 확인해 단계를 쓰고, `tools/scenario_run.py <파일> --platform aos|ios` 로 한 번 돌려 결과와 확신 없는 부분을 알린다
- 담당자의 교정·유의사항은 `notes` 에 그대로 남기고 단계에 반영한다. notes 는 지우지 않는다
- 담당자가 「여기 캡처해」라고 하면 그 화면이 채점 지점이다: 지금 화면에서 `tools/scenario_capture.py` 를 돌리고(말한 숫자·값은 `--value`, 달라도 되는 영역은 `--mask`), 같은 자리에 같은 이름의 `checkpoint` 단계를 넣는다
- **채점은 조건(expect)으로 한다. 캡처는 참고 그림이다.** 도구가 만든 조건 초안을 담당자의 말(유의사항)에 맞게 고쳐(`--expect`) 담당자에게 보여 주고 확인받는다. 확정은 담당자가 한다(앱 「조건 확정」 또는 담당자가 확정하라고 했을 때 `--confirm`). 조건으로 못 옮기는 것(연출·그림)은 `--human` 으로 남긴다 — 실행 때 Claude 가 판단하지 않는다
- 시트 원문(`tc`)은 고치지 않는다. 시트가 바뀌어 앱이 「문구 바뀜」을 보이면 새 문구로 `key`·`tc` 를 바꾸고 파일 이름도 새 키로 바꾼다

## 2-5. 기본 기능 (QA 앱 기본 기능 탭)

고정 시트 「CRO_버젼별 기본기능」의 TC 탭이 원본이고, 저장소 `basic/` 에 사본(`tc.json`)·시나리오(`scenarios/`)·규칙(`README.md`)이 있다.
- 시나리오는 대분류 하나에 하나, 모드리스트만 중분류마다 하나다. 안은 TC 구간으로 나뉘고 다음 구간은 앞 구간이 끝난 화면에서 이어 간다(형식은 `basic/README.md` 「시나리오 파일」)
- TC 탭 「판정 항목」 한 줄을 채점 지점(`checkpoint`) 하나로 옮긴다. 화면 정보로 판정 못 하는 줄은 `human` 으로 두고, 자동화하지 않는 TC 는 구간 `reason` 에 이유를 적는다
- 돌리기: `python3 tools/basic_run.py <시나리오.json> --platform aos|ios --version <버전>` → `runs/basic-<버전>-<플랫폼>-<시각>/`
- 결과는 리포트 대신 시트의 `<버전>` 탭에 쓴다. 절차·칸 규칙은 `basic/README.md` 「결과 쓰기」 — 칸은 `tools/basic_sheet.py` 가 정하고 에이전트는 그대로 쓴다. 사람이 적은 결과·QA 메모는 덮어쓰지 않는다

## 3. 실행 — iOS·Android 동시에

두 기기는 서로 다른 프로세스라 동시에 돌려도 된다. 각각 백그라운드로 띄우고 끝날 때까지 기다린다.

```bash
python3 tools/case_runner.py cases/<묶음>.json --platform ios --relaunch
python3 tools/case_runner.py cases/<묶음>.json --platform aos --relaunch
```

- `--relaunch`: 첫 케이스 전에 앱을 새로 띄워 로비까지 간다(약관·튜토리얼·공지 팝업 처리 포함). 첫 실행의 리소스 다운로드는 길다(수십 분)
- `--case TC-01,TC-02`: 일부만 · `--allow-spend`: 재화 쓰는 케이스 포함 · `--preset`: 프리셋 덮어쓰기
- 결과: `runs/<묶음>-<플랫폼>-<시각>/results.json`, 케이스별 캡처·트리(`*.tree.json`), `judge-request.md`(판정할 것이 있을 때)
- exit: 0 전부 PASS/NOT_RUN · 1 FAIL 또는 REVIEW · 2 케이스 형식 오류 · 3 ERROR 있음

ERROR(진행 실패) 분류와 할 일:

| kind | 뜻 | 할 일 |
|---|---|---|
| `NAME_MISSING` | 누를 이름이 트리에 없다 | UI 이름이 바뀌었는지 그 화면 트리를 떠서 확인한다. 케이스를 고쳐 다시 돌리고, 고친 것을 리포트에 적는다 |
| `BLOCKED` | 누를 버튼을 팝업이 덮었다 | 떠 있는 팝업을 확인해 닫는 단계를 더한다 |
| `NOT_REACHED` | 기대한 화면이 안 나왔다 | **흐름 변경 또는 결함 후보.** 실패 캡처와 scene 을 보고 판단한다 |
| `BRIDGE` | 연결 실패 | 1장을 다시 확인한다 |

같은 ERROR 가 한 번 나면 그 케이스만 `--case` 로 한 번 더 돌려 재현되는지 본다. 재현되지 않으면 리포트에 「1회 실패, 재실행 통과」로 적는다.

### 3-1. 계정 상태·서버 시간이 필요한 케이스

| 단계 | 하는 일 | 전제 |
|---|---|---|
| `{"do": "state", "path": "wallet.….amt", "value": 50}` | 마카롱으로 그 계정의 필드를 바꾸고 디버그 콘솔 「유저 정보 갱신」으로 앱에 반영한다. 되돌리지 않는다(`"restore": true` 일 때만 되돌림). 배열 항목을 빼려면 `{"do": "state", "op": "remove", "path": "inventory.pets.@id=201800", "max_refs": 2}` | 케이스 파일 `server`, 키트 Chrome 로그인(SETUP.md 5장) |
| `{"do": "server_time", "to": "+1d"}` 또는 `"2026-11-14 00:00"` | 서버 시간을 바꾸고 앱을 다시 띄워 로비까지 간다. 되돌리지 않는다 | 케이스 파일 `time_ok: true` + 실행기 `--allow-time` + 서버를 같이 쓰는 사람과 합의 |

- 필드 경로는 capnp proto-struct 의 이름을 snake_case 로 쓴 JSON 경로다(예: `wallet.my_cookie_icing_gacha_token.amt`). 모르면 `python3 tools/macaron_edit.py get <경로> --target <탭>` 으로 먼저 읽어 본다. 숫자·문자열 같은 **잎 값만** 바꾼다
- MID 는 화면의 「MID : …」 라벨에서 읽는다(케이스 파일 `mid` 로 고정할 수도 있다)
- 직접 확인: `python3 tools/timemachine.py get <서버>`, `python3 tools/timemachine.py set <서버> +1d --reason <케이스>`(기록은 `workspace/timemachine-log.jsonl`)
- 마카롱 **Delete 는 누르지 않는다**. 도구도 누르지 않는다
- 키트 Chrome(포트 9444)이 꺼져 있으면 마카롱 단계가 `fetch failed` 로 멈춘다. 실행기가 마카롱을 열기 전에 꺼져 있으면 `node tools/web/chrome_cdp.mjs launch` 로 띄운다. **새 컴퓨터는 처음 한 번 사람이 그 창에서 stove·마카롱에 로그인한다**(SETUP.md 5장, 로그인은 `workspace/chrome-profile` 에 남는다). 확인: `python3 tools/doctor.py --web`
- 키트 Chrome 하나를 모든 기기가 같이 쓴다. 마카롱 단계는 이 컴퓨터에서 한 번에 한 실행만 들어간다(`workspace/macaron.lock` 파일 잠금) — 두 기기를 같이 돌리면 늦게 온 쪽이 「다른 기기가 마카롱을 쓰는 중」을 남기고 기다린다

- **기본 기능 결과 캡처는 `python3 tools/basic_sheet.py upload --run runs/<실행>` 으로 올린다**(Google Drive 데스크톱의 캡쳐 폴더로 복사 → Drive 가 올린 파일 id 를 `drive.json` 에). Drive 연결(MCP)의 `create_file` 에 이미지를 base64 글자로 직접 써서 올리지 않는다 — 깨진 그림이 올라간다. Drive 데스크톱이 없으면 INSTALL.md 2-1 을 사람에게 안내한다

### 3-2. 인게임 자동 되감기 (kind: rewind)

QA 가 앱(`app/`)을 쓰면 케이스 편집·실행·리포트는 앱이 하고, Claude 는 앱에서 요약·진단·대화로 불린다. 앱이 만든 케이스·결과 파일은 이 문서의 형식과 같다.

되감기 시점 판단과 실행은 **게임이 한다**(DEBUG·GB_ENTERPRISE 빌드의 AutoRewind 모듈, 브랜치 v126_auto_rewind 이후). Claude 는 케이스를 쓰고 실행기를 돌리고 리포트를 읽는다. 화면을 보며 조작하지 않는다.

```bash
python3 tools/rewind_runner.py cases/<묶음>.json --check            # 형식 검사
python3 tools/rewind_runner.py cases/<묶음>.json --platform ios     # iPad·iPhone
python3 tools/rewind_runner.py cases/<묶음>.json --platform aos     # Android
```

- 케이스 형식: `cases/sample-rewind.json`, `cases/README.md` 「rewind」 절
- 실행기가 하는 일: 테스트 화면(디버그 → 테스트용 화면으로 가기) 이동 → 무한 되감기 켜기·트리거 설정 → 카드 장착(고정 + 랜덤, 보유 무관) → 맵 시작 → 이벤트·캡처·앱 로그 수집
- 트리거: `interval`(시작·직전 되감기 뒤 N초) · `afterRevive`(체력 0 부활 뒤 N초) · `afterBonusReturn`(보너스타임 복귀 뒤 N초), 각각 판당 `count` 회
- 판정: PASS(되감기 성공, 불일치 0) · FAIL(`rewind_fail` = 재시뮬레이션 어긋남, `state_mismatch` = 되감은 뒤 부활·보너스 횟수가 체크포인트와 다름) · ERROR(앱 종료·멈춤) · UNSURE(되감기가 한 번도 안 일어남 — 부활·보너스가 없었다)
- 앱 로그: iOS 는 `devicectl --console` 로 받는다(실행기가 앱을 직접 띄운다). 로컬 빌드는 assert 가 SIGINT 종료라 크래시 리포트가 남지 않는다 — 로그의 「App terminated due to signal」 이 그것이다. Android 는 logcat
- 조작 입력은 넣지 않는다. 부활·보너스 케이스는 **아무것도 안 눌러도** 장애물에 부딪혀 죽고, 보너스 아이템에 닿는 맵이어야 한다(GD 요청)
- 케이스의 `map` 은 기기 맵 목록에 있는 이름과 글자·대소문자까지 같아야 한다. 아니면 `맵 시작 실패: unknown map` 이다 — `python3 tools/gb_device.py testmode --platform ios --device <ID> --checkout "$PWD/workspace" --json '{"op":"maps"}'` 로 목록을 보고 고른다(QA 앱 되감기 탭의 「기기에서 목록 가져오기」도 같다). `unknown cmd` 는 빌드가 오래된 것이다(INSTALL.md 9장)
- 실행 중 다른 프로세스가 같은 기기를 조작하지 않는다. iOS 실행기를 멈추면 앱도 함께 끝난다(콘솔 연결 종료 = SIGINT)

## 4. 판정 — 세 층

| 층 | 무엇 | 모델 | 결과 |
|---|---|---|---|
| ① expect | 시트 기대 결과를 옮긴 트리 조건 | 없음 | 틀리면 **FAIL** |
| ② 정답지 | `answers/<묶음>/<플랫폼>/<케이스>/<체크포인트>.png·.json` 과 비교. 숫자 글자·`mask` 는 뺀다 | 없음 | 남은 큰 차이·글자 차이가 있으면 **REVIEW** |
| ③ 차이 판정 | REVIEW 만 | **qa-judge (haiku)** | ALLOWED → PASS · DEFECT → FAIL · UNSURE → 사람 확인 |

### REVIEW 처리

1. `runs/<run>/judge-request.md` 가 있으면 **qa-judge 서브에이전트**(`.claude/agents/qa-judge.md`)에게 「`<경로>` 를 판정해」라고 넘긴다. 직접 판정하지 않는다 — 찍은 쪽이 판정하면 놓친다.
2. 돌려받은 JSON 배열을 `runs/<run>/verdicts.json` 으로 저장하고 `python3 tools/judge.py apply runs/<run> runs/<run>/verdicts.json`.
3. **DEFECT 는 트리로 다시 확인한다.** 그 체크포인트의 `*.tree.json` 에서 문제의 노드(글자·rect·visible·clipped)를 `tools/ui_find.py --file <…tree.json> --owner/--inst/--text` 로 찾아 근거를 붙인다(파일 통째로 읽지 않는다). 트리가 반박하면(예: 노드가 정상 위치에 있음) `{"verdict": "ALLOWED", "by": "main-recheck", "reason": "<트리 근거>"}` 로 다시 apply 한다.
4. UNSURE 는 사람에게 캡처 경로와 함께 묻는다.

### 정답지 만들기 — 사람이 승인한다

- 정답지가 없는 첫 실행은 ①만으로 판정된다(체크포인트에 `baseline: none`). 리포트에 「정답지 없음」을 적는다.
- 사람에게 체크포인트 캡처를 보여 주고 「맞다」고 한 것만 `python3 tools/answer_key.py approve runs/<run> --case <id,...> --by "<승인한 사람>"` 으로 올린다. **Claude 가 스스로 승인하지 않는다.**
- 정답지는 플랫폼별이다(iPad 와 Android 의 화면 비율이 다르다). 같은 기종을 쓰는 것이 좋다. 비율이 다르면 비교 결과에 `note` 가 붙는다.
- 의도된 UI 변경으로 정답지가 낡으면 사람 승인 후 다시 approve 한다(이전 것은 `answers/.history/`).

## 5. 리포트

```bash
python3 tools/report.py --latest <묶음>          # 플랫폼별 최신 실행을 묶는다
```

`runs/report-<묶음>-<시각>/` 에 `report.md`(요약·실패 상세·근거 캡처 경로·미실행 이유), `results.csv`(시트 붙여넣기용), `results.tsv`(칸에 바로 붙여넣기) 가 생긴다.

대화로 보고할 때:
- 요약 표(플랫폼별 PASS/FAIL/확인 필요/진행 실패/미실행 개수)
- FAIL 마다 화면·근거(트리 조건 또는 판정 근거)·재현 경로(케이스 단계)·캡처 경로
- 「확인 필요」와 그 이유, 미실행 케이스와 이유
- 케이스·SCREENS.md 를 고친 것이 있으면 그 목록
- **돌리지 않은 것은 NOT_RUN 이라고 쓴다.** PASS 는 자동 판정 결과다. 사람 확인을 대신한다고 쓰지 않는다

### 시트에 결과 쓰기

케이스 파일에 `layout`(결과 칸 위치)·`sheetTab`·`statusMap` 이 있으면 리포트 폴더에 `sheet-update.json` 이 생긴다.
Google Sheets 연결(편집 권한)로 원본 시트에 쓴다:

0. 시트에는 「자동화」 탭이 있다: 케이스별 자동화 구분(화면·상태·시간·플레이·수동)·필요 조건·시트 확인 메모, 원본 결과 칸을 가리키는 수식, 오른쪽에 구분별·결과별 요약. 원본 탭 결과를 쓰면 요약이 저절로 바뀐다
1. 결과 칸(AOS·iOS)과 「자동화」 탭의 근거·마지막 실행 칸에 `cells[].value` 를 쓴다. `statusMap` 기본: PASS→Pass · FAIL→Fail · ERROR→Block · REVIEW/UNSURE→Check. **NOT_RUN 은 쓰지 않는다**(N/T 로 남겨 사람이 직접 본다)
2. comment 칸은 **덮어쓰지 않는다** — 기존 값을 읽고 `commentAppends[].append` 를 줄을 바꿔 덧붙인다
3. 쓰고 나서 그 범위를 다시 읽어 확인한다. 다른 사람이 이미 Pass/Fail 을 적은 칸이 있으면 덮어쓰지 말고 사람에게 묻는다
4. 결과 칸에 쓴 판정은 자동 판정이다. 「Check」 칸은 사람이 캡처를 보고 바꾼다

연결이나 권한이 없으면 results.tsv 를 사람이 붙여 넣는다.

## 6. 모델과 토큰

- 메인 세션: 시트 해석·케이스 작성·탐색·DEFECT 재확인. 실행 중에는 명령 결과 JSON 만 보면 된다 — 캡처를 하나하나 열지 않는다.
- qa-judge: haiku. REVIEW 의 차이 크롭만 본다. 전체 캡처는 크롭으로 부족할 때만 연다.
- 정답지가 쌓일수록 ①② 에서 끝나는 판정이 늘어 모델 호출이 준다.

## 7. 지키는 것

- **누르지 않는다**: 결제·구매, 계정 연동·로그아웃·계정 삭제, 선택 동의(광고성 정보 수신 등), 외부 링크, 디버그 콘솔의 logout·키체인 초기화·계정 불러오기
- 재화를 쓰는 케이스는 사람이 허락했을 때만 돌린다
- 새 계정(재설치)은 약관 → 튜토리얼이 나온다. 약관은 **필수 두 개만**, 튜토리얼은 디버그 토글 「Super User」·「Skip Tutorial」 후 「탈출시키기」(라이브러리가 자동으로 한다)
- 게임 화면·트리·시트를 승인되지 않은 외부 서비스로 보내지 않는다
- 같은 기기를 두 프로세스가 동시에 조작하지 않는다
- `device busy`(BRIDGE) 는 같은 기기를 다른 실행이 쓰는 중이라는 뜻이다(앱의 실행·Claude 탭·터미널 어디서든). 케이스를 고치지 말고 `pgrep -fl "case_runner|basic_run|scenario_run|rewind_runner"` 로 남은 실행을 찾아 끝난 뒤 다시 돌린다
- 닫기 버튼이 없고 「Touch!」 글자만 있는 연출 화면(신규 유저 특별 보상 `PopUpdateHighlight` 등)은 화면 가운데를 눌러 닫는다(`flowlib.close_popup` 이 한다). `NOT_REACHED … 닫는 법을 모르는 화면` 이 나면 그 화면의 트리에서 닫는 노드를 찾아 `SCREENS.md` 에 더한다
- 캡처는 `tools/gb_device.py screenshot` 으로만 가져온다. iOS 는 devicectl 화면 캡처를 쓴다 — 앱 컨테이너(`appDataContainer`) 복사로 우회하지 않는다. 사내 배포 빌드는 컨테이너 접근이 막혀 `ContainerLookupErrorDomain error 3` 이 난다. 캡처 명령이 없다고 나오면 Xcode 를 올린다(`doctor.py` 가 점검한다)
- 정답지 승인, 케이스의 `auto: false` 판단 근거, 시트에 없는 기대를 추가하는 것은 사람에게 확인한다
- 막혔으면 한 번 더 확인하고 나서 사람에게 올린다. 실행한 명령과 exit code 를 그대로 적는다
- 서버 시간을 바꾸기 전에는 그 서버를 같이 쓰는 사람에게 알린다. 과거로 되돌리기는 사람에게 묻는다(서버 에러가 난 기록이 있다)

## 8. 폴더

| 경로 | 내용 |
|---|---|
| `README.md` · `SETUP.md` · `PROMPTS.md` | 사람용 소개 · 설치 · 붙여 넣을 요청 문장 |
| `cases/` | 케이스 파일. 형식 `cases/README.md`, 샘플 `sample-mycookie-gacha.json` |
| `answers/` | 정답지(사람 승인). `answers/README.md` |
| `runs/` | 실행 결과·리포트 |
| `tools/case_runner.py` · `judge.py` · `answer_key.py` · `report.py` · `sheet_import.py` · `imgdiff.py` · `doctor.py` | 이 키트의 도구. 모두 `--help`(또는 파일 머리 설명) |
| `tools/gb_device.py` | 기기 조작 CLI |
| `tools/device_flows/` | 공통 경로(`routes.py`)·화면 대응표(`SCREENS.md`)·파이썬 플로우 |
| `.claude/agents/qa-judge.md` | 차이 판정 서브에이전트(haiku) |
| `workspace/` | 기기 도구의 상태·로그(게임 소스 아님) |
