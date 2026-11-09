# 시나리오 파일

QA 테스트 시트의 TC 하나를 자동으로 돌리는 방법이다. 파일이 있는 TC 는 QA 앱 아웃게임 탭에 ✓ 로 나오고, 나중에 ✓ 인 것만 순서대로 돌린다.

- 위치: `scenarios/<탭 이름>/<TC 키>.json` — 탭 이름의 `/` `\` `:` 는 `_` 로 바꾼다
- **TC 키**: 앱의 TC 상세에 나온다. 탭 이름 + 분류(Main~Sub3) + 기대 결과로 만든 12자리다
  - 번호(No)는 쓰지 않는다. 한 번호 아래 기대 결과를 여러 줄로 적기도 하고, 다음 버전 시트에서 번호가 밀린다
  - 시트 문구가 바뀌면 키도 바뀐다. 앱은 같은 탭·같은 번호의 옛 시나리오를 「문구 바뀜」으로 보여 준다
- 만들고 고치는 사람: QA 담당자와 Claude 가 같이 한다
  1. Claude 가 기기에서 화면을 확인하며 단계를 추측해 만든다
  2. 한 플랫폼에서 돌려 본다
  3. 담당자가 교정하거나 유의사항을 말한다
  4. Claude 는 그 말을 `notes` 에 남기고 단계를 고친다

```json
{
 "key": "8e4abf6c3b4d",
 "tab": "쿠키의 도전",
 "no": "20",
 "sheet": "CRO_14.50N Test Case",
 "tc": {"section": "…", "main": "…", "sub1": "…", "sub2": "…", "sub3": "…", "priority": "Normal", "expected": "…"},
 "createdBy": "GitHub 아이디",
 "updatedAt": "2026-11-09T16:40:00",
 "server": "gb-qa-126",
 "time_ok": false,
 "case": {
  "start": "lobby",
  "spends": false,
  "note": "트리로 옮기지 못한 기대 등",
  "steps": [ … ]
 },
 "scoring": [
  {"name": "episode-select", "label": "에피소드 선택 화면이 열린다",
   "expect": {"scene": "SceneOvenBreakEpisode", "tappable": [{"inst": "_btnStart"}], "count": [{"owner": "CellEpisode", "min": 1}],
              "text": [{"select": {"inst": "_labelGold"}, "contains": "100"}]},
   "confirmed": true, "confirmedBy": "담당자", "confirmedAt": "2026-11-09T16:50:00",
   "human": false, "humanNote": "", "compareImage": false,
   "values": [{"label": "골드", "value": "100"}], "mask": [{"owner": "CellEpisode"}],
   "platforms": {"aos": {"at": "2026-11-09T16:42:00", "by": "담당자"}}}
 ],
 "notes": [
  {"at": "2026-11-09", "by": "담당자", "text": "교정·유의사항 — 사람이 말한 그대로"}
 ],
 "lastRun": {"at": "2026-11-09T16:45:00", "platform": "aos", "verdict": "PASS", "run": "kit/runs/…"}
}
```

필드 설명:
- `tc` 는 시트 원문을 그대로 둔다. 문구가 바뀌었는지 비교하는 데 쓴다.
- `server` 와 `time_ok` 는 `state` 단계(마카롱)·`server_time` 단계가 있을 때만 쓴다.
- `case` 는 케이스 한 개와 같은 모양이다. 단계 종류·선택자·판정은 `kit/cases/README.md` 의 「단계」 절을 따른다.
- `notes` 는 지우지 않고 쌓는다. 다음에 고칠 때 먼저 읽는다.
- `scoring`(채점표)은 채점할 지점의 목록이다. 시나리오를 만드는 중 사람이 「여기 캡처해」라고 한 지점이다.
  - **채점은 조건(`expect`)으로 한다.** 조건은 게임이 주는 화면 정보다: 화면 이름, 보이는·누를 수 있는 버튼, 목록 개수, 값. 실행 때마다 기계가 같은 기준으로 판정한다.
  - **캡처는 참고 그림이다**: `scenarios/<탭>/<키>/<플랫폼>/<지점>.png`. 조건을 정한 근거이자 사람이 볼 기준이다. `compareImage: true` 인 지점만 화면 비교도 한다(레이아웃 확인용).
  - 조건은 Claude 가 초안을 만들고 **사람이 확정한다**(`confirmed`). 사람의 유의사항은 이때 조건과 `mask`(달라도 되는 영역)로 옮긴다. 실행 때마다 Claude 가 판단하지 않는다.
  - 확정 전 지점은 실행에서 **HUMAN(사람 확인)** 으로 나온다.
  - 조건으로 옮길 수 없는 것(연출·그림이 맞는지)은 `human: true` + `humanNote` 로 둔다. 조건이 통과해도 HUMAN 으로 남겨 사람이 캡처를 본다.
  - `values` 는 사람이 말한 숫자·값이다(예: 골드 = 100). 조건의 `text` 로도 들어간다.
  - `case.steps` 에 같은 이름의 `checkpoint` 단계가 있어야 다음 실행에서 채점된다.
- `lastRun` 은 `scenario_run.py` 가 돌린 뒤 적는다(지점별 판정·실행 캡처 경로).

「여기 캡처해」 — 기기가 그 화면에 와 있을 때:

```bash
cd kit
python3 tools/scenario_capture.py ../scenarios/<탭>/<키>.json --platform aos --name <지점> --by <말한 사람> \
        --label "무엇을 보는 지점인지" [--value "골드=100"] [--mask '{"owner": "CellCookieListCard"}'] \
        [--expect '<조건 JSON>'] [--human "사람이 캡처로 볼 것"] [--compare-image]
python3 tools/scenario_capture.py ../scenarios/<탭>/<키>.json --name <지점> --confirm --by <확정한 사람>
```

이 도구는 조건 초안과 참고 그림을 만든다. 출력의 조건을 사람에게 보여 주고 확인받는다. 맞으면 앱의 「조건 확정」이나 `--confirm` 으로 확정하고, 다르면 `--expect` 로 고친다. 같은 자리에 `{"do": "checkpoint", "name": "<지점>"}` 단계를 넣는 것은 Claude 가 한다.

돌리기:

```bash
cd kit
python3 tools/scenario_run.py ../scenarios/<탭>/<키>.json --check            # 형식만
python3 tools/scenario_run.py ../scenarios/<탭>/<키>.json --platform aos      # 한 플랫폼에서
```

결과는 `kit/runs/scenario-<플랫폼>-<시각>/` 에 남는다. 돌린 뒤 `lastRun` 을 고친다.
