# QA 시나리오 · QA 앱

QA 자동화의 케이스·문서·녹화와 **QA 앱**을 함께 담은 저장소다. 앱이 이 저장소 안에서 돌기 때문에 받기 한 번으로 케이스와 앱이 같이 최신이 된다.

| 폴더 | 내용 |
|---|---|
| kit/ | QA 앱(`kit/app`)과 실행 도구(`kit/tools`). 앱을 고치는 사람만 수정한다 |
| cases/ | 케이스 묶음(JSON). `kind: rewind` 는 되감기, 나머지는 아웃게임 |
| docs/ | 사람이 쓰는 시나리오 문서(md) |
| presets/ | 되감기 입력 프리셋 |
| recordings/ | 맵 녹화(사람이 한 판 플레이한 입력) |

실행 결과(`kit/runs`)·기기 ID·앱 설정(`kit/workspace`)은 각자 컴퓨터에만 둔다.

## 처음 설치 (컴퓨터마다 한 번)

1. 기기 준비는 `kit/SETUP.md` 1·2장(iPad 는 Xcode, Android 는 adb)
2. Node.js 설치: 터미널에서 `brew install node`
3. 이 저장소 받기: 터미널에서
   ```
   cd ~/Documents && gh repo clone devsisters/cro-qa
   ```
   (`gh` 로그인이 안 돼 있으면 `gh auth login` 부터)
4. Finder 에서 `cro-qa/kit/start.command` 를 두 번 누른다 — 처음에는 구성요소를 설치한 뒤 앱이 뜬다
5. 앱의 「준비」 탭에서 빠진 것이 없는지 확인한다

## 그다음부터

- 앱은 `kit/start.command` 로 띄운다
- **앱 업데이트는 따로 할 일이 없다.** 앱을 켜면 저장소를 받아 오고, 앱이 바뀌었으면 스스로 다시 시작한다. 앱을 켜 둔 채 새 버전이 올라오면 위쪽 「받을 기록」이 늘고, 「최신 받기」를 누르면 「다시 시작」 버튼이 나온다
- 테스트가 도는 중에는 다시 시작하지 않는다 — 끝난 뒤 누른다
- 게임 빌드는 따로 받아 기기에 설치한다(DEBUG 빌드)
