# 정답지

사람이 「이 화면이 맞다」고 승인한 체크포인트 화면이다. 실행 결과는 이것과 비교된다.

```
answers/<묶음>/<플랫폼 ios|aos|mac>/<케이스>/<체크포인트>.png   캡처
answers/<묶음>/<플랫폼>/<케이스>/<체크포인트>.json  글자 목록(숫자 글자 제외)·마스크 영역·화면 좌표·승인 정보
answers/.history/…                                         덮어쓴 이전 정답지
```

- 만들기: `python3 tools/answer_key.py approve runs/<run> --case TC-01,TC-02 --by "<승인자>"` — expect 를 통과한 체크포인트만 승인된다
- 보기: `python3 tools/answer_key.py list --suite <묶음>`
- 빼기: `python3 tools/answer_key.py drop <묶음> <플랫폼> <케이스> [--checkpoint 이름]`

정답지는 승인 당시의 빌드·계정·서버 데이터를 담는다. 의도된 UI 변경 뒤에는 사람 확인을 거쳐 다시 승인한다.
