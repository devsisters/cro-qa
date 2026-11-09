# QA 앱

키트(이 폴더의 부모)를 화면으로 쓰는 Electron 앱이다. 실행·판정은 키트 Python 도구가 하고, 앱은 편집·실행·보기를, Claude CLI 는 요약·진단·대화를 맡는다. 같은 결과를 CLI(`CLAUDE.md`)로도 얻는다 — 파일 형식이 같다.

실행: `npm install` (처음 한 번) → `npm start`. 점검: `npm test`, `QA_APP_SMOKE=1 npx electron .`(화면 오류를 터미널로 내보내고 닫힌다).

## 탭

| 탭 | 하는 일 |
|---|---|
| 준비 | 처음 세팅 점검(`lib/setup.js`) — Python·Homebrew·Xcode·iOS 캡처·adb·Claude CLI·로그인·기기의 게임 앱·Node·Chrome. 빠진 것은 버튼(앱 안 설치 / 터미널 창 / 다운로드 링크)이나 명령 복사로 고친다. 실행하는 명령은 `lib/setup.js` 표에 있는 것뿐이다. 준비된 줄은 숨기고 전부 준비되면 「처음 세팅」 부분을 숨긴다. 필수 항목이 빠졌거나 팀 저장소를 아직 안 받았으면 앱이 이 탭부터 연다 |
| (위 줄) 시나리오 | 시나리오 저장소(`lib/git.js`, 팀 저장소 `devsisters/cro-qa`) 상태·「받기」(pull --rebase --autostash, 충돌이면 rebase --abort 로 되돌리고 알림)·「올리기」(커밋 → 받기 → push). 준비 탭 맨 위에서 「받기」 한 번(기본 `~/Documents/cro-qa` 로 clone, 이미 받은 폴더면 그대로 씀, 빈 저장소면 키트 샘플로 첫 기록). 앱을 켤 때 자동으로 받는다. 정하면 케이스·프리셋을 그 폴더의 `cases/`·`presets/` 에서 읽고 쓰고, Claude 도 `--add-dir` 로 그 폴더를 본다. 인증은 gh 로그인(`gh auth login --web` + `gh auth setup-git`) |
| 기기 | 연결된 iOS·Android 기기를 자동으로 찾아 고르고 저장(`tools/device_flows/devices.json`, 15초마다 다시 찾음). 「연결 모드로 실행」(브리지를 켠 채 게임 다시 띄우기)·연결 확인(브리지 ping·현재 화면), Python·Claude CLI·Xcode 경로 설정 |
| 되감기 | `cases/` 의 `kind: rewind` 묶음 편집 — 맵(「맵 목록 받기」로 기기에서 받아 자동완성)·카드(고정 id / 빈칸=랜덤 / 보물 0=빈칸)·판 수·트리거·입력 수치. 프리셋(`presets/rewind-input.json`) 적용·저장. 「Claude 로 채우기」에 문장을 쓰면 폼을 채운다(저장은 사람이 누른다) |
| 아웃게임 | 시트 기반 묶음(`case_runner`)에서 돌릴 케이스 선택 |
| 실행 | iOS·Android 를 고르고 「테스트 시작」. 기기마다 실행기를 따로 띄우고 줄 단위 로그를 보여 준다. 판마다 결과가 리포트에 쌓인다 |
| 리포트 | `runs/` 목록. 전체 표(조합·되감기 요청→돌아간 인게임 시각·충돌·부활·구멍 구출·이어달리기·보너스타임·캡처 썸네일), 줄을 누르면 그 판 상세로 이동. 실패 판은 게임 로그. FAIL·ERROR·UNSURE 판마다 「Claude 진단」(결과는 `diagnosis-<케이스>-play<N>.md`) |
| Claude | 키트 폴더를 작업 폴더로 한 대화. 읽기·검색·케이스 편집·`python3 tools/*` 실행만 허용 |

## 조정하는 수치(되감기)

| 값 | 기본 | 뜻 |
|---|---|---|
| actionsPerSec | 0.8 | 초당 점프·슬라이드 시작 빈도 |
| slideRatio | 0.3 | 그중 슬라이드 비율 |
| doubleJumpRatio | 0.4 | 점프 중 더블 점프 비율 |
| abilityEverySec | 8 | 능력·스펠·축복 버튼 간격(0 = 안 누름) |
| rescue | 켜짐 | 구멍 구출 버튼이 눌릴 수 있으면 누른다 |
| input seed | 0 | 판 시드 = 시드 + 판번호 − 1. 같은 시드·카드·맵이면 같은 입력 |
| plays · timeoutSec | 2 · 300 | 판 수, 판 제한(넘으면 ERROR) |
| 트리거 delaySec · count | 10 · 2 | 트리거 뒤 몇 초에 되감을지, 판당 몇 번 |

## 비용

Claude 호출마다 비용이 든다(2026-11-05 실측: 케이스 초안 $0.24, 리포트 요약 $0.48, 대화 한 턴 약 $0.3). 실행 자체(장착·되감기·판정)는 모델을 쓰지 않는다.

## 구조

`main.js`(창·IPC·실행기 관리) · `preload.js`(화면에 여는 API) · `lib/kit.js`(키트 파일·도구 호출) · `lib/claude.js`(Claude CLI) · `lib/caseModel.js`(케이스 기본값·검사 — 범위는 `tools/rewind_runner.py` 와 같다) · `renderer/`(화면) · `test/`
