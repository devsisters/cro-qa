# 새 맥 설치 — 사람이 한 번 한다

아무것도 없는 맥 기준이다. 순서대로 하고 마지막에 `python3 tools/doctor.py` 로 확인한다.

## 1. Xcode (iPad 용)

1. App Store 에서 **Xcode** 설치 → 한 번 실행해 추가 구성요소 설치를 끝낸다
2. 터미널: `sudo xcode-select -s /Applications/Xcode.app` (선택. 안 해도 키트가 Xcode 를 찾는다)
3. iPad 를 케이블로 연결 → iPad 에서 「이 컴퓨터를 신뢰」 → 설정 → 개인정보 보호 및 보안 → **개발자 모드 켜기**(재시동)
4. iPad 설정 → 디스플레이 및 밝기 → 자동 잠금 → **안 함** (테스트 중 잠기면 멈춘다)

`python3` 는 Xcode(또는 Command Line Tools)에 들어 있다. 다른 파이썬 패키지는 필요 없다.

## 2. adb (Android 용)

1. Homebrew 가 없으면 https://brew.sh 안내대로 설치
2. `brew install --cask android-platform-tools`
3. Android 기기: 설정 → 휴대전화 정보 → 소프트웨어 정보 → 빌드번호 7번 탭(개발자 옵션) → 개발자 옵션 → **USB 디버깅** 켜기
4. 연결 후 기기에 뜨는 「USB 디버깅을 허용하시겠습니까?」 → 「이 컴퓨터에서 항상 허용」 체크 → 허용
5. 화면 꺼짐 시간을 길게(개발자 옵션 → 「충전 중 화면 켜짐 유지」)

## 3. Claude Code

1. Claude Code 설치(사내 안내 따름) 후 이 폴더에서 `claude` 실행 — `CLAUDE.md` 를 자동으로 읽는다
2. 첫 요청은 `PROMPTS.md` 1번(환경 점검)

## 4. 게임 빌드

- CI(Cookiepot)의 **DEBUG 단계 빌드**나 자동화 연결(AgentBridge)을 넣은 **Stage 빌드**를 기기에 설치한다. Real·스토어 빌드에는 없다
- iOS Stage 빌드는 「기기」 탭 iOS 줄의 빌드를 「Stage (AdHoc)」로 고른다(CLI 는 `--bundle stage`). 인게임 자동 되감기는 DEBUG 빌드에만 있다
- 빌드가 바뀌면 다시 설치하고 `PROMPTS.md` 4번(회귀)을 돌린다

## 5. Chrome·Node — 계정 상태·서버 시간 케이스용

계정 상태를 바꾸는 케이스(마카롱)와 서버 시간을 바꾸는 케이스(타임머신)에만 필요하다. 화면 확인 케이스만 돌리면 건너뛴다.

1. Chrome 설치(https://www.google.com/chrome), `brew install node`(22 이상)
2. 키트 전용 Chrome 창 띄우기: `node tools/web/chrome_cdp.mjs launch`
   - 평소 쓰는 Chrome 과 따로 노는 창이다(프로필 `workspace/chrome-profile`). 로그인·쿠키가 섞이지 않는다
3. 그 창에서 **사람이 한 번** 로그인한다
   - https://stove.devspie.com/app/timemachine/get?name=<서버> → 「데브시스터즈 직원 로그인」
   - https://macaron.<서버>.stove.devspie.com/couchbase_modifier/ → 인증서 경고가 뜨면 [고급] → [계속]
4. `python3 tools/doctor.py --web` 이 OK
5. 다 쓰면 그 창을 닫는다(열려 있는 동안 디버깅 포트가 열려 있다)

서버 시간은 그 서버를 쓰는 모든 사람에게 바뀐다. 같이 쓰는 서버면 먼저 알린다. 슬랙 #cro_timemachine 의 `!t <서버>`(조회)·`!s <서버> 2026-11-14 00:00`(변경)과 같은 기능이다.

## 5-1. Google Drive 데스크톱 — 기본 기능 결과 캡처용

기본 기능 결과의 캡처는 키트가 `basic_sheet.py upload` 로 Google Drive 데스크톱의 공유 드라이브 폴더(`basic/sheet.json` 의 `captureDrivePath`)에 복사하고, Drive 가 올린 뒤 파일 id 를 읽어 시트 링크로 쓴다. 팀원 모두 필요하다.

1. `brew install --cask google-drive` (맥 비밀번호가 필요할 수 있다) 또는 https://www.google.com/drive/download/
2. 앱을 열어 회사 계정으로 로그인하고, Finder 의 「Google Drive › 공유 드라이브 › QA」 가 열리는지 확인한다(권한이 없으면 요청).
3. `python3 tools/doctor.py` 의 「Google Drive 데스크톱」 줄이 OK 면 된다. QA 앱 「준비」 탭에도 같은 점검이 있다.

## 6. 확인

```bash
python3 tools/doctor.py          # FAIL 이 없어야 한다
python3 tools/doctor.py --ping   # 앱을 띄운 뒤 — 브리지까지
python3 tools/doctor.py --web    # 상태·시간 케이스를 돌릴 때 — 키트 Chrome 로그인까지
```

## 7. QA 앱

설치·업데이트는 저장소 맨 위 `README.md` 「처음 설치」를 따른다. Claude 에게 맡길 때의 절차는 저장소 맨 위 `INSTALL.md` 다. 요약하면 `brew install node` → `gh repo clone devsisters/cro-qa` → Finder 에서 `kit/start.command` 두 번 누르기.

- 앱을 처음 띄우면 「준비」 탭이 이 문서의 1~5장을 점검한다. 빠진 도구는 그 줄의 버튼으로 설치하거나 명령을 복사해 터미널에 붙인다. 기기의 게임 앱(DEBUG 빌드) 설치 여부도 본다
- 앱이 저장소 안에서 돌기 때문에 저장소를 따로 고를 필요가 없다. 케이스·문서·녹화는 화면 위 줄의 「최신 받기」·「변경 공유」로 주고받는다(앱을 켤 때도 자동으로 받는다). 같은 부분을 둘이 고쳐 충돌이 나면 앱이 받기 전 상태로 되돌리고 알려 준다
- **앱 업데이트**: 받은 것에 앱이 바뀐 내용이 있으면 앱을 켤 때는 스스로 다시 시작하고, 켜 둔 상태면 「다시 시작」 버튼이 나온다. 구성요소(package-lock)가 바뀌었으면 다시 시작 전에 설치한다
- 실행 결과(`kit/runs`)·기기 ID·앱 설정(`kit/workspace/app-settings.json`)은 저장소에 들어가지 않는다
- 아이콘을 눌러 켠 게임은 자동화 연결(AgentBridge)이 꺼져 있다. 「기기」 탭의 「연결 모드로 실행」으로 띄운다
- 앱 안 Claude 기능은 Claude Code CLI 를 쓴다(3장). `claude` 가 PATH 에 없으면 앱 「기기」 탭 → 설정 → Claude CLI 에 전체 경로를 넣는다(예: `~/.local/bin/claude`)
- `npm ci` 뒤 `app/node_modules/electron/dist` 가 없으면 `node node_modules/electron/install.js`

## 자주 막히는 것

| 증상 | 해결 |
|---|---|
| devicectl: `The developer disk image could not be mounted` 경고 | 무시해도 된다(경고). iPad 를 다시 연결하거나 Xcode 를 한 번 연다 |
| `Locked` | iPad 잠금 해제 |
| adb 기기가 `unauthorized` | 기기 화면의 USB 디버깅 허용 창을 누른다 |
| ping exit 4 | 자동화 연결이 없는 빌드다(Real·스토어 빌드, 또는 연결을 넣기 전 Stage 빌드) |
| 번역 문구가 이상하다 | 첫 리소스 다운로드가 덜 끝났을 수 있다 — 앱 재시작 |
