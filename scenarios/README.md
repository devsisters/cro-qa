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

돌리기:

```bash
cd kit
python3 tools/scenario_run.py ../scenarios/<탭>/<키>.json --check            # 형식만
python3 tools/scenario_run.py ../scenarios/<탭>/<키>.json --platform aos      # 한 플랫폼에서
```

결과는 `kit/runs/scenario-<플랫폼>-<시각>/` 에 남는다. 돌린 뒤 `lastRun` 을 고친다.
