# device_flows — 기기 플로우 모음

Figma 플로우를 실기기(macOS·iPad·Android)에서 이름·글자로 따라가는 스크립트를 쌓아 두는 곳이다.
처음 한 번은 탐색해서 만들고, 그 뒤로는 어느 플랫폼에서든 바로 다시 돌린다. 브리지는 DEBUG 빌드의 AgentBridge, 조작은 `../gb_device.py`.

## 구성

| 파일 | 무엇 |
|---|---|
| `flowlib.py` | `Device`(트리·탭·스와이프·캡처·대기·팝업 닫기)와 실패 분류 `FlowFailure` |
| `routes.py` | 여러 플로우가 쓰는 경로 — `to_lobby`(프리셋·다운로드·약관·튜토리얼·첫 실행 팝업까지), `lobby_to_gacha`, `back_to_lobby` |
| `flows/<기능>.py` | 기능별 플로우. `FIGMA` 링크, `SKIPS`(데이터 조건으로 못 보는 단계), `run(dev, check, pull)` |
| `SCREENS.md` | 화면 ↔ scene·owner·노드 이름 대응표. 새 플로우를 짤 때 먼저 본다 |
| `devices.json` | 플랫폼별 기기 ID |
| `states.py` | 계정 상태 레시피 — 마카롱으로 테스트 계정 필드를 바꾸고 블록이 끝나면 되돌린다(`../macaron_edit.py`, dev 마카롱 gb-* · 계정 제한 없음) |
| `run_flow.py` | 실행기 |

## 돌리기

```bash
python3 gb_device.py build/install --platform … --checkout <wt>   # 필요하면
python3 device_flows/run_flow.py --list
python3 device_flows/run_flow.py mycookie_icing_gacha --platform mac|ios|aos --checkout <wt> --relaunch [--no-pull]
```

- `--relaunch`: 앱을 새로 띄워 같은 시작 상태에서 돈다. 안 주면 지금 화면에서 시작한다
- `--no-pull`: 재화를 쓰는 단계를 건너뛴다(QA 계정 재화가 줄어든다)
- `--states`: 마카롱으로 계정 상태를 바꿔 보는 단계를 켠다(예: 재화 부족). Aside 가 CDP 로 떠 있고 마카롱에 로그인돼 있어야 한다. 바꾼 값은 `routes.refresh_user_info`(디버그 콘솔 「유저 정보 갱신」)로 앱에 반영하고, 끝나면 원래 값으로 되돌린다
- 결과: `<wt>/.gb-agent/runs/device-flows/<flow>-<platform>-<시각>/report.json` 과 단계별 캡처

exit: 0 전 단계 통과 · 1 확인 실패(화면은 갔는데 기대값이 다름) · 2 사용법 · 3 흐름 실패

## 실패 분류 — 깨졌을 때 무엇을 볼지

| kind | 뜻 | 먼저 볼 것 |
|---|---|---|
| `NAME_MISSING` | 기대한 노드 이름·글자가 트리에 없다 | **UI(ccb) 변경**. 같은 화면에서 트리를 떠 새 이름을 찾고 플로우·SCREENS.md 를 고친다 |
| `BLOCKED` | 노드는 있는데 확실히 덮였다 | 위에 뜬 팝업. `routes` 의 팝업 처리에 더한다 |
| `NOT_REACHED` | 기대한 화면이 제한 시간 안에 안 나왔다 | **흐름 변경 또는 결함**. 실패 캡처(`failure`)와 `detail` 의 scene 을 본다 |
| `BRIDGE` | 브리지·기기 연결 실패 | 앱이 떠 있는지, iPad 잠금, 빌드가 DEBUG 인지 |

`exit 1`(확인 실패)은 흐름은 맞는데 값이 다르다 — 결함 후보다. Figma 대조는 캡처를 Fable 에게 넘겨 판정받는다(스킬 `gb-device-loop`).

## 새 플로우 더하기

1. Figma 를 읽고 화면 순서를 정한다. 화면 이름이 `SCREENS.md` 에 있으면 그 이름을 쓴다
2. 처음 보는 화면은 앱에서 트리를 떠(`gb_device.py tree`) 확인 노드와 버튼 이름을 찾는다. 찾은 것은 `SCREENS.md` 에 더한다
3. `flows/<기능>.py` 에 `FIGMA`·`SKIPS`·`run()` 을 쓴다. 화면까지의 공통 구간은 `routes` 를 쓰고, 두 플로우 이상이 같은 구간을 쓰게 되면 `routes` 로 옮긴다
4. 한 플랫폼에서 통과시킨 뒤 나머지 플랫폼에서 `--relaunch` 로 돌린다
5. 누르기는 이름·글자로만 한다(`dev.tap`). 좌표는 이름이 없는 닫기·바깥 탭에만 쓴다

## 지키는 것

- 선택 동의(광고성 수신 등)·구매·계정 연동 버튼은 누르지 않는다
- 재화를 쓰는 단계는 `pull` 인자로 끌 수 있게 둔다
- 테스트: `python3 -m unittest test_flowlib.py`
