#!/usr/bin/env python3
"""채점표 지점 등록 — 시나리오를 만드는 중 사람이 「여기 캡처해」라고 하면 지금 기기 화면을 그 지점의 정답으로 저장한다.

  python3 tools/scenario_capture.py <시나리오.json> --platform ios|aos --name <지점 이름> --by <말한 사람>
                                    [--label "무엇을 보는 지점인지"] [--value "설명=값" ...] [--mask <선택자 JSON> ...]
                                    [--device ID]

- 정답: scenarios/<탭>/<키>/<플랫폼>/<지점>.png · .json(화면·글자 목록·바뀌는 영역 마스크). 정답지 비교와 같은 형식이다
- 시나리오 파일의 scoring(채점표)에 지점을 넣거나 고친다. --value 는 사람이 말한 숫자·값(예: "골드=100")이다
- 시나리오 case.steps 에는 같은 이름의 checkpoint 단계가 있어야 다음 실행에서 채점된다 — 없으면 경고한다(단계는 Claude 가 넣는다)
- 지금 화면을 그대로 찍으므로, 부르기 전에 기기가 그 지점에 와 있어야 한다
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


def upsert_scoring(data, name, platform, by, label=None, values=None, mask=None, when=None):
    """채점표 지점을 넣거나 고친다. 같은 이름이면 플랫폼별 정답 정보만 덮어쓴다."""
    when = when or time.strftime('%Y-%m-%dT%H:%M:%S')
    scoring = data.setdefault('scoring', [])
    entry = next((x for x in scoring if x.get('name') == name), None)
    if entry is None:
        entry = {'name': name, 'label': label or '', 'values': [], 'mask': [], 'platforms': {}}
        scoring.append(entry)
    if label:
        entry['label'] = label
    for v in values or []:
        key, _, val = v.partition('=')
        item = {'label': key.strip(), 'value': val.strip()}
        entry['values'] = [x for x in entry.get('values', []) if x.get('label') != item['label']] + [item]
    for m in mask or []:
        if m not in entry.setdefault('mask', []):
            entry['mask'].append(m)
    entry.setdefault('platforms', {})[platform] = {'at': when, 'by': by}
    data['updatedAt'] = when
    steps = ((data.get('case') or {}).get('steps') or [])
    return any(s.get('do') == 'checkpoint' and s.get('name') == name for s in steps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scenario')
    ap.add_argument('--platform', required=True, choices=('ios', 'aos'))
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
    qc.save_json(js, {'scenario': data.get('key'), 'platform': a.platform, 'checkpoint': a.name, 'scene': scene,
                      'geometry': {k: geometry.get(k) for k in ('visibleOrigin', 'visibleSize', 'frameSize')},
                      'imageSize': __import__('imgdiff').size_of(png), 'texts': qc.text_signature(nodes),
                      'masks': qc.dynamic_masks(nodes, masks), 'approved': {'by': a.by, 'at': when, 'note': a.label or ''}})
    has_step = upsert_scoring(data, a.name, a.platform, a.by, a.label, a.value, masks, when)
    with open(a.scenario, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write('\n')
    out = {'ok': True, 'image': os.path.relpath(png, os.path.dirname(os.path.abspath(a.scenario))), 'scene': scene}
    if not has_step:
        out['warning'] = f'case.steps 에 checkpoint 「{a.name}」 단계가 없다 — 이 지점에 단계를 넣어야 다음 실행에서 채점된다'
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
