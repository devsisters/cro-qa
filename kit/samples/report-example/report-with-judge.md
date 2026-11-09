# 자동화 테스트 결과 — sample-mycookie-gacha

- 테스트 시트: (샘플 — 실제 시트 없음. Figma 2610_마이쿠키뽑기 플로우를 시트 형식으로 옮긴 것)
- AOS: 시작 20261104-113709 · 끝 20261104-114120 · 기기 R3CW909TLSM · 결과 `runs/sample-mycookie-gacha-aos-20261104-113709`

## 요약

| 판정 | AOS |
|---|---|
| ERROR 진행 실패 | 0 |
| FAIL 실패 | 0 |
| REVIEW 확인 필요 | 0 |
| UNSURE 확인 필요 | 1 |
| PASS 통과 | 4 |
| NOT_RUN 미실행 | 0 |

## 케이스별

| 케이스 | 제목 | AOS |
|---|---|---|
| TC-01 | 아이싱 뽑기 / 진입 / 아이싱 뽑기 탭을 누르면 픽업 화면이 나온다 | PASS |
| TC-02 | 아이싱 뽑기 / 확률 정보 / 아이싱 탭이 선택된 채 열린다 | PASS |
| TC-03 | 아이싱 뽑기 / 최근 상자 내역 / 팝업이 열리고 닫힌다 | PASS |
| TC-04 | 아이싱 뽑기 / 아이템 정보 / 아이싱 셀을 누르면 이름·설명 말풍선 | PASS |
| TC-05 | 아이싱 뽑기 / 1회 뽑기 / 그리기 연출 → 결과 | - |
| TC-06 | 아이싱 뽑기 / 옷장 / 옷장 버튼으로 마이쿠키 옷장 이동 | UNSURE |
| TC-07 | 아이싱 뽑기 / 재화 부족 / 재화가 모자라면 부족 팝업 | - |
| TC-08 | 아이싱 뽑기 / 사운드 / 뽑기 연출 효과음 | - |

## 확인 필요 — 정답지와 차이, 판정 미완 또는 불확실

### TC-06 [AOS] 아이싱 뽑기 / 옷장 / 옷장 버튼으로 마이쿠키 옷장 이동
- 체크포인트 `closet` → **UNSURE** (scene SceneNavigator)
  - 화면 차이 0.2% · 큰 덩어리 3개
    - 정답 `<키트>/runs/sample-mycookie-gacha-aos-20261104-113709/TC-06/crops/aos-closet-r0-expected.png` · 실제 `<키트>/runs/sample-mycookie-gacha-aos-20261104-113709/TC-06/crops/aos-closet-r0-actual.png`
    - 정답 `<키트>/runs/sample-mycookie-gacha-aos-20261104-113709/TC-06/crops/aos-closet-r1-expected.png` · 실제 `<키트>/runs/sample-mycookie-gacha-aos-20261104-113709/TC-06/crops/aos-closet-r1-actual.png`
    - 정답 `<키트>/runs/sample-mycookie-gacha-aos-20261104-113709/TC-06/crops/aos-closet-r2-expected.png` · 실제 `<키트>/runs/sample-mycookie-gacha-aos-20261104-113709/TC-06/crops/aos-closet-r2-actual.png`
  - 판정(qa-judge): UNSURE / animation_frame — 크롭상 구별되지 않아 원인을 특정할 수 없다
  - 캡처: `<키트>/runs/sample-mycookie-gacha-aos-20261104-113709/TC-06/aos-closet-1793760073351.png`


---
판정 기준: expect(트리 조건) → 정답지 비교(숫자 마스크) → 차이만 낮은 모델 판정. 「통과」는 자동 판정 결과이며 사람 확인을 대신하지 않는다.
