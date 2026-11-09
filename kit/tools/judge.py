#!/usr/bin/env python3
"""REVIEW(정답지와 차이가 있는 체크포인트)를 낮은 모델 판정용으로 묶고, 판정 결과를 결과에 반영한다.

  python3 tools/judge.py prepare runs/<run>            # judge-request.md 다시 만들기(case_runner 가 자동으로 한다)
  python3 tools/judge.py apply runs/<run> <verdicts.json>

판정은 `.claude/agents/qa-judge.md`(model: haiku) 서브에이전트가 한다. 그 서브에이전트에게
「runs/<run>/judge-request.md 를 판정해」라고 넘기고, 돌려받은 JSON 배열을 verdicts.json 으로 저장해 apply 한다.

verdicts.json: [{"case": "TC-01", "checkpoint": "icing-tab", "verdict": "ALLOWED|DEFECT|UNSURE",
                 "category": "...", "reason": "..."}]
  ALLOWED → PASS(판정: 허용 차이) · DEFECT → FAIL(판정: 결함 의심, 메인이 트리로 재확인) · UNSURE → UNSURE(사람 확인)
exit: 0 성공, 2 사용법·형식 오류
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_common as qc  # noqa: E402

CATEGORIES = {
    'ALLOWED': ['timer', 'currency_or_count', 'animation_frame', 'account_data', 'banner_rotation', 'debug_overlay',
                'device_letterbox'],
    'DEFECT': ['missing_element', 'wrong_text', 'layout_shift', 'clipping', 'overlap', 'wrong_image', 'wrong_screen'],
}
GUIDE = """# 판정 요청 — 정답지와 실제 화면의 차이

당신은 게임 QA 화면 판정자다. 아래 항목마다 **정답(expected)** 과 **실제(actual)** 이미지 크롭, 글자 차이를 보고
차이가 **허용 차이(ALLOWED)** 인지 **결함 의심(DEFECT)** 인지 고른다. 확신이 없으면 **UNSURE**.

허용 차이(ALLOWED) — category 하나를 고른다
- timer: 남은 시간·시계·날짜
- currency_or_count: 재화·보유 수량·개수 숫자
- animation_frame: 반짝이·캐릭터 동작·이펙트 프레임이 다른 순간에 찍힘
- account_data: 계정마다 다른 내용(보유 표시 ✓, 뽑힌 아이템, 닉네임, 랭킹)
- banner_rotation: 배너·광고 순서가 돌아간 것
- debug_overlay: 디버그 문구(MID, build number, TextureCache 등)
- device_letterbox: 화면 바깥 검은 띠·OS 표시(iPad 위 「…」)

결함 의심(DEFECT) — category 하나를 고른다
- missing_element: 정답에 있던 버튼·아이콘·글자가 없다
- wrong_text: 숫자가 아닌 문구가 다르다(오타, 번역 키가 그대로 보임, 다른 문구)
- layout_shift: 같은 요소가 눈에 띄게 다른 위치·크기
- clipping: 글자·이미지가 잘림
- overlap: 요소끼리 겹쳐 가려짐
- wrong_image: 다른 아이콘·그림·색
- wrong_screen: 아예 다른 화면

규칙
- 이미지 파일을 Read 로 직접 열어 본다. 크롭이 없으면 전체 캡처(actual/expected)를 연다
- 글자 차이 목록의 'missing' 은 정답에만, 'added' 는 실제에만 있는 글자다(숫자가 든 글자는 이미 뺐다)
- 판정 근거를 reason 에 한 문장으로 쓴다. 보이지 않는 것을 추측하지 않는다
- 출력은 JSON 배열 하나만: [{"case","checkpoint","verdict","category","reason"}]

"""


def items(results):
    out = []
    for c in results['cases']:
        for cp in c.get('checkpoints', []):
            if cp.get('verdict') == 'REVIEW' and not cp.get('judged'):
                out.append((c, cp))
    return out


def prepare(run_dir):
    results = qc.load_json(os.path.join(run_dir, 'results.json'))
    todo = items(results)
    path = os.path.join(run_dir, 'judge-request.md')
    if not todo:
        if os.path.exists(path):
            os.remove(path)
        return None
    lines = [GUIDE, f'플랫폼: {results["platform"]} · 묶음: {results["suite"]} · 항목 {len(todo)}개\n']
    for c, cp in todo:
        d = cp.get('diff') or {}
        base = cp.get('baseline')
        lines.append(f'## {c["id"]} / {cp["name"]} — {c.get("title", "")}')
        lines.append(f'- 실제 전체: `{cp.get("shot")}`')
        if base:
            lines.append(f'- 정답 전체: `{os.path.join(base, cp["name"] + ".png")}`')
        img = d.get('image')
        if img:
            lines.append(f'- 바뀐 픽셀 {img["changed"] * 100:.1f}% (마스크 뒤), 큰 차이 덩어리 {len(img.get("significant", []))}개')
            for cr in img.get('crops', []):
                lines.append(f'  - 영역 {cr["region"]}: 정답 `{cr["expected"]}` · 실제 `{cr["actual"]}`')
        t = d.get('texts')
        if t:
            lines.append(f'- 글자 missing: {t["missing"]}')
            lines.append(f'- 글자 added: {t["added"]}')
        lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return path


def apply(run_dir, verdict_file):
    results = qc.load_json(os.path.join(run_dir, 'results.json'))
    raw = open(verdict_file, encoding='utf-8').read().strip()
    if raw.startswith('```'):
        raw = raw.strip('`').split('\n', 1)[1].rsplit('```', 1)[0] if '\n' in raw else raw
    verdicts = json.loads(raw)
    index = {(c['id'], cp['name']): (c, cp) for c in results['cases'] for cp in c.get('checkpoints', [])}
    errors, applied = [], 0
    for v in verdicts:
        key = (v.get('case'), v.get('checkpoint'))
        if key not in index:
            errors.append(f'없는 항목 {key}')
            continue
        if v.get('verdict') not in ('ALLOWED', 'DEFECT', 'UNSURE'):
            errors.append(f'{key}: verdict 는 ALLOWED|DEFECT|UNSURE')
            continue
        c, cp = index[key]
        if cp.get('verdict') != 'REVIEW' and not cp.get('judged'):
            errors.append(f'{key}: REVIEW 가 아니다({cp.get("verdict")})')
            continue
        cp['judged'] = {'verdict': v['verdict'], 'category': v.get('category', ''), 'reason': v.get('reason', ''),
                        'by': v.get('by', 'qa-judge')}
        cp['verdict'] = {'ALLOWED': 'PASS', 'DEFECT': 'FAIL', 'UNSURE': 'UNSURE'}[v['verdict']]
        applied += 1
    for c in results['cases']:
        if c.get('verdict') not in ('ERROR', 'NOT_RUN'):
            c['verdict'] = qc.worst(cp['verdict'] for cp in c.get('checkpoints', []))
    qc.save_json(os.path.join(run_dir, 'results.json'), results)
    left = prepare(run_dir)
    print(json.dumps({'ok': not errors, 'applied': applied, 'errors': errors, 'remaining': left}, ensure_ascii=False))
    return 0 if not errors else 2


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == 'prepare':
        print(json.dumps({'ok': True, 'judgeRequest': prepare(sys.argv[2])}, ensure_ascii=False))
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == 'apply':
        return apply(sys.argv[2], sys.argv[3])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
