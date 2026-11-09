#!/usr/bin/env python3
"""채점표 지점 등록 — 시나리오를 만드는 중 사람이 「여기 캡처해」라고 하면 그 화면을 채점 지점으로 등록한다.

  python3 tools/scenario_capture.py <시나리오.json> --platform ios|aos --name <지점 이름> --by <말한 사람>
                                    [--label "무엇을 보는 지점인지"] [--expect '<조건 JSON>'] [--value "설명=값" ...]
                                    [--mask <선택자 JSON> ...] [--human "사람이 캡처를 보고 판단할 것"] [--compare-image]
                                    [--device ID]
  python3 tools/scenario_capture.py <시나리오.json> --name <지점 이름> --confirm --by <확정한 사람>   # 조건 확정(기기 없이)

채점은 **조건(expect — 게임이 주는 화면 정보: scene·present·tappable·count·text)** 으로 한다. 캡처는 참고 그림이다.
- 지금 화면의 트리로 조건 초안을 만든다(화면 이름·누를 수 있는 버튼·이름 있는 글자·mask 목록 1개 이상). --expect 를 주면 그것을 쓴다
- --value "골드=100" 은 화면에서 그 값을 가진 글자를 찾아 text 조건으로 넣는다
- 새 조건은 확정 전(confirmed=false)이다. 확정 전 지점은 실행에서 HUMAN(사람 확인)으로 나온다. 사람이 조건을 보고 확정한다(앱 버튼 또는 --confirm)
- --human: 조건으로 옮길 수 없는 것(연출·그림이 맞는지). 조건이 통과해도 HUMAN 으로 남겨 사람이 캡처를 본다
- --compare-image: 이 지점만 참고 그림과 화면 비교도 한다(레이아웃 확인용 — 기본 꺼짐)
- 참고 그림: scenarios/<탭>/<키>/<플랫폼>/<지점>.png · .json
- case.steps 에 같은 이름의 checkpoint 단계가 있어야 다음 실행에서 채점된다 — 없으면 경고한다(단계는 Claude 가 넣는다)
exit: 0 저장 · 2 사용법 · 3 기기/캡처 실패
"""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'device_flows'))
import qa_common as qc  # noqa: E402


def answers_dir(scenario_path):
    return os.path.splitext(os.path.abspath(scenario_path))[0]


def draft_expect(scene, nodes, masks=(), values=()):
    """지금 화면 트리로 채점 조건 초안을 만든다. 사람이 보고 고치거나 확정한다."""
    masked = set()
    for sel in masks:
        masked.update(id(n) for n in qc.select(nodes, sel))
    ident = lambda n: {k: n[k] for k in ('owner', 'inst') if n.get(k)}
    exp = {'scene': scene} if scene else {}
    buttons = [n for n in nodes if n.get('inst') and n.get('receiver') and id(n) not in masked
               and n.get('enabled') is not False and not n.get('blockedBy')]
    labels = [n for n in nodes if n.get('inst') and n.get('text') and not qc.DIGIT.search(n['text']) and id(n) not in masked]
    seen = set()
    tap, pres = [], []
    for n in buttons:
        k = json.dumps(ident(n), sort_keys=True)
        if k not in seen and len(tap) < 5:
            seen.add(k)
            tap.append(ident(n))
    for n in labels:
        k = json.dumps(ident(n), sort_keys=True)
        if k not in seen and len(pres) < 4:
            seen.add(k)
            pres.append(dict(ident(n), text=n['text']))
    if tap:
        exp['tappable'] = tap
    if pres:
        exp['present'] = pres
    counts = [dict(sel, min=1) if isinstance(sel, dict) else {'any': sel, 'min': 1} for sel in masks]
    if counts:
        exp['count'] = counts
    texts = []
    for v in values:
        label, _, val = v.partition('=')
        hit = next((n for n in nodes if val.strip() and val.strip() in (n.get('text') or '')), None)
        if hit and ident(hit):
            texts.append({'select': ident(hit), 'contains': val.strip()})
    if texts:
        exp['text'] = texts
    return exp


def upsert_scoring(data, name, platform, by, label=None, values=None, mask=None, when=None,
                   expect=None, human=None, compare_image=None):
    """채점표 지점을 넣거나 고친다. 같은 이름이면 플랫폼별 참고 그림 정보를 더하고, 새 조건을 주면 확정 전으로 되돌린다."""
    when = when or time.strftime('%Y-%m-%dT%H:%M:%S')
    scoring = data.setdefault('scoring', [])
    entry = next((x for x in scoring if x.get('name') == name), None)
    if entry is None:
        entry = {'name': name, 'label': label or '', 'expect': {}, 'confirmed': False, 'human': False, 'humanNote': '',
                 'compareImage': False, 'values': [], 'mask': [], 'platforms': {}}
        scoring.append(entry)
    if expect is not None and expect != entry.get('expect'):
        entry['expect'] = expect
        entry['confirmed'] = False
        entry.pop('confirmedBy', None)
        entry.pop('confirmedAt', None)
    if human:
        entry['human'], entry['humanNote'] = True, human
    if compare_image is not None:
        entry['compareImage'] = bool(compare_image)
    if label:
        entry['label'] = label
    for v in values or []:
        key, _, val = v.partition('=')
        item = {'label': key.strip(), 'value': val.strip()}
        entry['values'] = [x for x in entry.get('values', []) if x.get('label') != item['label']] + [item]
    for m in mask or []:
        if m not in entry.setdefault('mask', []):
            entry['mask'].append(m)
    if platform:
        entry.setdefault('platforms', {})[platform] = {'at': when, 'by': by}
    data['updatedAt'] = when
    steps = ((data.get('case') or {}).get('steps') or [])
    return any(s.get('do') == 'checkpoint' and s.get('name') == name for s in steps)


def confirm(data, name, by, when=None):
    entry = next((x for x in data.get('scoring', []) if x.get('name') == name), None)
    if entry is None:
        return False
    entry['confirmed'] = True
    entry['confirmedBy'] = by
    entry['confirmedAt'] = when or time.strftime('%Y-%m-%dT%H:%M:%S')
    data['updatedAt'] = entry['confirmedAt']
    return True


def save(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write('\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scenario')
    ap.add_argument('--platform', choices=('ios', 'aos'))
    ap.add_argument('--expect', help='채점 조건 JSON(expect 형식). 없으면 지금 화면으로 초안을 만든다')
    ap.add_argument('--human', help='조건으로 못 옮기는 것 — 사람이 캡처를 보고 판단한다')
    ap.add_argument('--compare-image', action='store_true', help='이 지점은 참고 그림과 화면 비교도 한다')
    ap.add_argument('--confirm', action='store_true', help='이 지점의 조건을 확정한다(기기 없이)')
    ap.add_argument('--name', required=True)
    ap.add_argument('--by', required=True)
    ap.add_argument('--label')
    ap.add_argument('--value', action='append', default=[])
    ap.add_argument('--mask', action='append', default=[], help='바뀌는 영역 선택자(JSON 객체 또는 이름)')
    ap.add_argument('--device')
    a = ap.parse_args()
    if not a.name.replace('-', '').replace('_', '').isalnum():
        print(json.dumps({'ok': False, 'error': '지점 이름은 영문·숫자·-·_ (파일 이름으로 쓴다)'}, ensure_ascii=False))
        return 2
    data = qc.load_json(a.scenario)
    if a.confirm:
        if not confirm(data, a.name, a.by):
            print(json.dumps({'ok': False, 'error': f'채점표에 「{a.name}」 지점이 없다'}, ensure_ascii=False))
            return 2
        save(a.scenario, data)
        print(json.dumps({'ok': True, 'confirmed': a.name, 'by': a.by}, ensure_ascii=False))
        return 0
    if not a.platform:
        print(json.dumps({'ok': False, 'error': '--platform 이 필요하다(캡처할 기기)'}, ensure_ascii=False))
        return 2
    given = None
    if a.expect:
        try:
            given = json.loads(a.expect)
        except ValueError as e:
            print(json.dumps({'ok': False, 'error': f'--expect 가 JSON 이 아니다: {e}'}, ensure_ascii=False))
            return 2
    masks = []
    for m in a.mask:
        try:
            masks.append(json.loads(m))
        except ValueError:
            masks.append(m)
    from flowlib import Device
    tmp = os.path.join(qc.RUNS, '_capture')
    dev = Device(a.platform, qc.WORKSPACE, tmp, a.device)
    try:
        tree = dev.tree()
        nodes = qc.visible(tree)
        scene = dev.scene()
        geometry = dev.call('ping').get('result', {})
        shot = dev.shot(a.name)
    except Exception as e:  # noqa: BLE001 — 기기 쪽 실패는 그대로 알린다
        print(json.dumps({'ok': False, 'error': f'기기에서 화면을 읽지 못했다: {e}'}, ensure_ascii=False))
        return 3
    if not shot:
        print(json.dumps({'ok': False, 'error': f'캡처 실패: {getattr(dev, "shot_error", "")}'}, ensure_ascii=False))
        return 3
    dest = os.path.join(answers_dir(a.scenario), a.platform)
    os.makedirs(dest, exist_ok=True)
    png, js = os.path.join(dest, f'{a.name}.png'), os.path.join(dest, f'{a.name}.json')
    shutil.copy2(shot, png)
    when = time.strftime('%Y-%m-%dT%H:%M:%S')
    # 이 지점에 이미 등록된 바뀌는 영역 + 이번에 준 것. 다음 실행에서도 같은 영역의 그림·글자를 비교에서 뺀다
    prev = next((x for x in data.get('scoring', []) if x.get('name') == a.name), {})
    selectors = list(prev.get('mask', []))
    selectors += [m for m in masks if m not in selectors]
    qc.save_json(js, {'scenario': data.get('key'), 'platform': a.platform, 'checkpoint': a.name, 'scene': scene,
                      'geometry': {k: geometry.get(k) for k in ('visibleOrigin', 'visibleSize', 'frameSize')},
                      'imageSize': __import__('imgdiff').size_of(png), 'texts': qc.text_signature(nodes, selectors),
                      'masks': qc.dynamic_masks(nodes, selectors), 'maskSelectors': selectors,
                      'approved': {'by': a.by, 'at': when, 'note': a.label or ''}})
    prev_expect = (next((x for x in data.get('scoring', []) if x.get('name') == a.name), {}) or {}).get('expect')
    # 조건: 준 것 > 이미 있는 것(다른 플랫폼에서 만든 것) > 지금 화면으로 만든 초안
    expect = given if given is not None else (None if prev_expect else draft_expect(scene, nodes, selectors, a.value))
    has_step = upsert_scoring(data, a.name, a.platform, a.by, a.label, a.value, masks, when,
                              expect=expect, human=a.human, compare_image=True if a.compare_image else None)
    save(a.scenario, data)
    entry = next(x for x in data['scoring'] if x.get('name') == a.name)
    out = {'ok': True, 'image': os.path.relpath(png, os.path.dirname(os.path.abspath(a.scenario))), 'scene': scene,
           'expect': entry.get('expect'), 'confirmed': entry.get('confirmed'),
           'next': '조건을 사람에게 보여 주고 확인받는다 — 맞으면 앱의 「조건 확정」 또는 --confirm, 다르면 --expect 로 고친다'}
    if not has_step:
        out['warning'] = f'case.steps 에 checkpoint 「{a.name}」 단계가 없다 — 이 지점에 단계를 넣어야 다음 실행에서 채점된다'
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
