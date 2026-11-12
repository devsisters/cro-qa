# QA 앱 처음 설치 — Claude 작업 지침

**독자: QA 팀원의 맥에서 실행된 Claude Code.** 사람이 「INSTALL.md 대로 설치해줘」라고 하면 이 문서를 위에서부터 순서대로 진행한다. 끝나면 그 맥에서 QA 앱(`kit/start.command`)이 뜨고, `python3 kit/tools/doctor.py` 에 FAIL 이 없어야 한다.

사람용 설명은 `README.md`, 키트 설치의 상세 정본은 `kit/SETUP.md` 다. 이 문서는 그 내용을 Claude 가 실행하는 순서로 옮긴 것이다.

## 0. 진행 규칙

- **각 단계는 「확인 → 없을 때만 설치 → 다시 확인」 순서로 한다.** 이미 있는 것은 다시 설치하지 않는다. 중간에 끊겼다가 다시 시작해도 처음부터 이 문서를 따르면 된다.
- **사람만 할 수 있는 일은 하지 않고 멈춰서 정확히 요청한다.** 해당 단계마다 「사람」이라고 적어 두었다. 사람이 끝냈다고 하면 확인 명령을 다시 돌려 실제로 됐는지 본다.
  - 비밀번호 입력이 필요한 명령(`sudo`, Homebrew 설치 스크립트)
  - App Store 설치, 기기 화면에서 누르는 허용·신뢰·설정
  - `gh auth login` 같은 대화형 로그인 — 사람에게 프롬프트에 `! gh auth login` 을 입력하게 한다
  - 게임(DEBUG 빌드 또는 Stage 빌드) 설치 — 빌드는 앱 담당자가 따로 전달한다
- 비밀번호·토큰·쿠키 값은 묻지도, 출력하지도, 파일에 쓰지도 않는다.
- 이 저장소에 커밋·push 하지 않는다. `kit/` 의 소스를 고치지 않는다. 설치 중 키트 오류가 나면 고치려 하지 말고 오류 원문과 함께 사람에게 「앱 담당자에게 전달」하라고 알린다.
- 명령의 성공은 종료 코드로 판정한다. 출력을 `| tail` 로 잘라 성공을 판정하지 않는다.
- PATH 에 Homebrew 가 없을 수 있다. 명령 앞에 `export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"` 를 붙인다.

## 1. Homebrew

확인: `command -v brew || ls /opt/homebrew/bin/brew /usr/local/bin/brew`

없으면 **사람**: 맥의 「터미널」 앱을 열어 https://brew.sh 첫 화면의 설치 명령을 붙여 넣고 실행한다. 맥 로그인 비밀번호를 묻는다. 끝에 「Next steps」로 나오는 두 줄도 그대로 실행한다.

## 2. 명령줄 도구 — gh · Node.js · adb

확인:

```bash
command -v gh; command -v node && node --version; command -v adb
```

없는 것만 설치한다. 비밀번호가 필요 없어 Claude 가 실행해도 된다.

```bash
brew install gh          # gh 가 없을 때
brew install node        # node 가 없거나 22 미만일 때
brew install --cask android-platform-tools   # adb 가 없을 때 (Android 기기를 쓸 때만)
```

### 2-1. Google Drive 데스크톱 — 기본 기능 결과 캡처용(팀원 모두)

기본 기능 결과의 캡처 사진은 키트가 Google Drive 데스크톱의 공유 드라이브 폴더로 복사해 올린다(에이전트의 Drive 연결은 파일을 올리지 못한다). 이 컴퓨터에서 처음이면 설치와 로그인이 필요하다.

확인: `ls -d "/Applications/Google Drive.app"` 와 `ls ~/Library/CloudStorage` 에 `GoogleDrive-<메일>` 이 있고, `cd kit && python3 tools/doctor.py` 의 「Google Drive 데스크톱」 줄이 OK.

- 없으면 설치: `brew install --cask google-drive` — 맥 비밀번호를 물으면 **사람**이 프롬프트에 `! brew install --cask google-drive` 로 실행한다.
- **사람**: 설치한 Google Drive 앱을 열어 회사 계정으로 로그인한다. 메뉴 막대의 Drive 아이콘이 동기화 중이 아니게 되면, Finder 의 「Google Drive › 공유 드라이브 › QA」 가 열리는지 본다. 폴더가 안 보이면 공유 드라이브 「QA」 접근 권한을 요청한다.
- 터미널에서 그 폴더를 읽을 때 `Operation timed out` 이 나면 아직 Drive 앱이 연결되지 않은 것이다(로그인·초기 동기화가 끝나길 기다린다). 계속되면 시스템 설정 › 개인정보 보호 및 보안 › 파일 및 폴더(또는 전체 디스크 접근)에서 쓰는 터미널 앱을 허용한다.
- 캡쳐 폴더 경로는 `basic/sheet.json` 의 `captureDrivePath` 다. 계정 폴더 이름(`GoogleDrive-<메일>`)은 컴퓨터마다 달라도 키트가 찾는다. 경로가 다르게 보이는 컴퓨터는 환경변수 `QA_CAPTURE_DIR` 에 그 폴더를 준다.

## 3. GitHub 로그인

확인: `gh auth status` 가 `Logged in to github.com` 을 보이고, `gh repo view devsisters/cro-qa --json name` 이 성공해야 한다.

안 되면 **사람**: 프롬프트에 `! gh auth login` 을 입력하고 GitHub.com → HTTPS → 웹 브라우저 로그인 순서로 고른다. 회사 계정으로 로그인한다. 로그인은 됐는데 저장소가 안 보이면 devsisters 조직 권한이 없는 것이다 — 앱 담당자에게 저장소 권한을 요청하게 한다.

## 4. 저장소 받기

기본 위치는 `~/Documents/cro-qa` 다. 사람이 다른 위치를 말했으면 그 위치를 쓴다.

```bash
test -d ~/Documents/cro-qa/.git && git -C ~/Documents/cro-qa pull --ff-only \
  || gh repo clone devsisters/cro-qa ~/Documents/cro-qa
```

- 이미 받아 둔 저장소에서 `pull` 이 실패하면(충돌·로컬 변경) 아무것도 지우지 말고 `git status` 를 사람에게 보여 준다.
- 이후 단계의 상대 경로는 저장소 폴더 기준이다.

## 5. Xcode — iPad 를 쓸 때만

확인: `ls -d /Applications/Xcode*.app` 와 `xcrun devicectl --version`

- Xcode 가 없으면 **사람**: App Store 에서 Xcode 를 설치하고 한 번 실행해 추가 구성요소 설치를 끝낸다. 용량이 커서 오래 걸린다. iPad 를 안 쓰면 건너뛰고 완료 보고에 「iPad 미설정」이라고 적는다.
- `devicectl` 이 첫 실행 구성 요소를 요구하면 **사람**: 터미널에서 `sudo xcodebuild -runFirstLaunch`.

## 6. QA 앱 구성요소

```bash
cd kit/app && npm ci --no-audit --no-fund
```

- `npm install` 이 아니라 `npm ci` 를 쓴다. `npm install` 은 `package-lock.json` 을 고쳐서 나중에 앱의 「변경 공유」에 섞여 올라간다.
- 확인: `ls kit/app/node_modules/electron/dist` 에 `Electron.app` 이 있어야 한다. 없으면 `cd kit/app && node node_modules/electron/install.js` 를 한 번 더 돌린다.

## 7. 기기 연결과 기기 ID

`kit/tools/device_flows/devices.json` 은 컴퓨터마다 다르고 저장소에 들어가지 않는다. 없으면 견본에서 만든다.

```bash
cd kit && test -f tools/device_flows/devices.json || cp tools/device_flows/devices.example.json tools/device_flows/devices.json
```

**사람**에게 기기 준비를 요청한다(쓰는 기기만). 자세한 화면 경로는 `kit/SETUP.md` 1·2장이다.

| 기기 | 사람이 할 일 |
|---|---|
| iPad | 케이블 연결 → 「이 컴퓨터를 신뢰」 → 설정 › 개인정보 보호 및 보안 › 개발자 모드 켜기(재시동) → 디스플레이 및 밝기 › 자동 잠금 「안 함」 |
| Android | 개발자 옵션 켜기 → USB 디버깅 켜기 → 연결 후 「이 컴퓨터에서 항상 허용」 체크 후 허용 → 개발자 옵션 › 충전 중 화면 켜짐 유지 |

그다음 ID 를 찾아 `devices.json` 의 `ios.device`·`aos.device` 에 넣는다. 다른 키(`platform`·`note`)는 그대로 둔다.

```bash
xcrun devicectl list devices      # iPad: Identifier 열. State 가 connected 인 줄
adb devices                       # Android: serial. 상태가 device 인 줄 (unauthorized 면 기기 화면의 허용을 누르게 한다)
```

같은 종류 기기가 여러 대면 어느 것을 쓸지 사람에게 묻는다. QA 앱의 「기기」 탭에서도 같은 값을 고를 수 있다.

## 8. 점검

```bash
cd kit && python3 tools/doctor.py; echo "exit $?"
```

- exit 0 이고 FAIL 줄이 없으면 통과다. 각 FAIL·WARN 줄 아래의 「→」 줄이 해결 방법이다. 사람이 할 일이면 그 줄을 그대로 전한다.
- WARN 중 Node.js·Chrome 은 서버 시간 케이스용이라 없어도 되감기·화면 테스트는 돈다. Chrome 로그인(`SETUP.md` 5장)은 그 케이스를 쓸 때 사람이 한다.

### 8-1. 키트 Chrome 로그인 — 사람(서버 시간 케이스를 쓸 때)

서버 시간을 바꾸는 케이스는 키트 Chrome 으로 타임머신을 부른다. 이 컴퓨터에서 처음이면 **사람**: `node kit/tools/web/chrome_cdp.mjs launch` 로 뜬 창에서 stove 에 로그인한다(`kit/SETUP.md` 5장). 로그인은 `kit/workspace/chrome-profile` 에 남아 다음부터는 실행기가 창을 스스로 띄운다. 확인: `cd kit && python3 tools/doctor.py --web`.

마카롱으로 계정 상태를 바꾸는 케이스(기본 기능·쿠키 인벤토리 등)는 브라우저 없이 dev 마카롱 API 를 부르므로 로그인이 필요 없다.

## 9. 게임 설치 — 사람

기기에 **DEBUG 빌드**나 자동화 연결을 넣은 **Stage 빌드**(Android Release·iOS AdHoc)가 깔려 있어야 앱이 게임을 조작한다. Real·스토어 빌드에는 자동화 연결(AgentBridge)이 없다. iOS Stage 빌드는 앱 「기기」 탭 iOS 줄의 빌드를 「Stage (AdHoc)」로 고른다. 빌드 파일과 설치 방법은 앱 담당자가 따로 전달하므로, Claude 는 빌드를 찾거나 만들지 않는다. 사람에게 「앱 담당자에게 받은 DEBUG 빌드(또는 Stage 빌드)를 기기에 설치해 달라」고 요청한다.

설치됐다고 하면 확인한다(기기마다):

```bash
cd kit && python3 tools/gb_device.py launch --platform ios --device <ID> --checkout "$PWD/workspace"
python3 tools/doctor.py --ping; echo "exit $?"
```

- Android 는 `--platform android`. iOS Stage AdHoc 빌드는 `--bundle stage` 를 붙인다.
- `launch` 가 `Locked` 오류면 사람에게 iPad 잠금 해제를 요청한다.
- `--ping` 의 「브리지」 줄이 FAIL 이고 ping 결과가 exit 4 면 자동화 연결이 없는 빌드다(Real·스토어 빌드) — DEBUG 빌드나 Stage 빌드를 다시 받아야 한다.
- 게임 첫 실행의 리소스 다운로드는 수십 분 걸릴 수 있다.
- `testmode`(맵 목록·되감기) 명령에 `{"ok": false, "error": "unknown cmd"}` 가 나오면 Stage 빌드이거나(되감기는 DEBUG 빌드에만 있다) 되감기(AutoRewind)를 지원하지 않는 오래된 DEBUG 빌드다 — 앱 담당자에게 최신 DEBUG 빌드를 받는다.
- 앱을 새로 설치한 직후 `bridge unavailable; addresses attempted: …` 가 나오면, 기기에서 앱 아이콘으로 직접 열었기 때문이다. 브리지 환경변수는 `gb_device.py launch`(QA 앱의 실행·되감기 탭 포함)로 띄울 때만 들어간다 — launch 로 다시 띄운다.

## 10. QA 앱 띄우기

```bash
open kit/start.command
```

- 앱 창이 뜨면 「준비」 탭에서 빠진 것이 없는지 사람에게 확인하게 한다.
- 다음부터 사람은 Finder 에서 `kit/start.command` 를 두 번 누르면 된다. 앱 업데이트는 앱이 스스로 받는다(`README.md` 「그다음부터」).
- 앱 안의 Claude 기능은 `claude` 명령을 쓴다. 앱이 못 찾으면 `command -v claude` 의 전체 경로를 「기기」 탭 › 설정 › Claude CLI 에 넣게 한다.

## 11. 완료 보고

사람에게 표로 보고한다. 단계마다 상태는 `OK` · `건너뜀(이유)` · `사람 할 일` · `실패` 중 하나다. 확인 명령을 돌리지 않은 단계는 `NOT_RUN` 으로 적고 OK 로 적지 않는다.

| 단계 | 상태 | 근거(확인 명령과 exit code) |
|---|---|---|
| 1 Homebrew ~ 10 QA 앱 | | |

마지막에 남은 「사람 할 일」을 번호 목록으로 다시 적는다.
