#!/usr/bin/env python3
"""게임 화면 정보(UI 트리)를 필요한 부분만 짧게 본다. 트리 전체(한 화면 수백 노드·수백 KB)를 읽지 않으려고 쓴다.

  python3 tools/ui_find.py --platform ios|aos [--device ID]            # 지금 기기 화면 요약
  python3 tools/ui_find.py --file runs/<실행>/<케이스>/<지점>.tree.json   # 실행 때 남긴 트리
  걸러 보기(여러 개 주면 모두 만족): --owner 소속 · --inst 이름 · --text 글자(포함) · --type 타입(포함)
                                    --tappable(누를 수 있는 것) · --buttons(버튼 전부) · --texts(글자 있는 것)
  --all 이름·글자·버튼이 없는 노드도 · --each 같은 노드(목록 칸 등)를 묶지 않고 하나씩 · --limit N(기본 60) · --json

요약(걸러 보기 없이)에는 화면 이름, 소속별 노드 수, 누를 수 있는 버튼, 이름 있는 글자가 나온다.
한 줄 형식: [id] 소속 · 이름 · 「글자」 · 버튼(눌림|꺼짐|가려짐←무엇) · 좌표 x,y,w,h (게임 좌표, 원점 왼쪽 아래)
선택자로 옮길 때는 소속(owner)·이름(inst)을 그대로 쓴다 — 예: {"owner": "SceneCookieList", "inst": "_btnSortMenu"}
exit: 0 · 2 사용법 · 3 기기에서 못 읽음
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'device_flows'))
import qa_common as qc  # noqa: E402


def useful(n):
    return bool(n.get('inst') or n.get('text') or n.get('receiver'))


def button_state(n):
    if not n.get('receiver'):
        return ''
    if n.get('enabled') is False:
        return '버튼(꺼짐)'
    if n.get('blockedBy'):
        return f'버튼(가려짐←{n.get("blockedByDesc") or n["blockedBy"]})'
    return '버튼(눌림)'


def tappable(n):
    return bool(n.get('receiver')) and n.get('enabled') is not False and not n.get('blockedBy')


def line(n):
    parts = [f'[{n.get("id")}]', n.get('owner') or '-']
    if n.get('inst'):
        parts.append(n['inst'])
    elif n.get('name'):
        parts.append(f'name={n["name"]}')
    if n.get('text'):
        t = n['text'].replace('\n', ' ')
        parts.append(f'「{t[:60]}{"…" if len(t) > 60 else ""}」')
    b = button_state(n)
    if b:
        parts.append(b)
    if not n.get('inst') and not n.get('text'):
        parts.append(n.get('type', '').split('<')[-1].rstrip('>').split('::')[-1])
    r = n.get('rect')
    if r:
        parts.append('%d,%d,%d,%d' % tuple(round(v) for v in r))
    return ' · '.join(parts)


def grouped(nodes, each=False):
    """소속·이름·글자·버튼 상태가 같은 노드(목록 칸의 같은 버튼 등)를 한 줄로 묶는다 → [(대표 노드, 개수)]"""
    if each:
        return [(n, 1) for n in nodes]
    order, groups = [], {}
    for n in nodes:
        k = (n.get('owner'), n.get('inst') or n.get('name'), n.get('text'), button_state(n),
             '' if (n.get('inst') or n.get('text')) else n.get('type'))
        if k not in groups:
            groups[k] = [n, 0]
            order.append(k)
        groups[k][1] += 1
    return [tuple(groups[k]) for k in order]


def gline(n, count):
    return line(n) + (f' · ×{count}' if count > 1 else '')


def pick(nodes, a):
    out = []
    for n in nodes:
        if not a.all and not useful(n):
            continue
        if a.owner and n.get('owner') != a.owner:
            continue
        if a.inst and n.get('inst') != a.inst:
            continue
        if a.text and a.text not in (n.get('text') or ''):
            continue
        if a.type and a.type not in (n.get('type') or ''):
            continue
        if a.tappable and not tappable(n):
            continue
        if a.buttons and not n.get('receiver'):
            continue
        if a.texts and not n.get('text'):
            continue
        out.append(n)
    return out


def summary(scene, nodes, limit, each=False):
    owners = collections.Counter(n.get('owner') or '-' for n in nodes)
    useful_nodes = [n for n in nodes if useful(n)]
    L = [f'화면: {scene} · 보이는 노드 {len(nodes)}개(이름·글자·버튼 있는 것 {len(useful_nodes)}개)',
         '소속별: ' + ', '.join(f'{o} {c}' for o, c in owners.most_common(12))]
    btn = grouped([n for n in useful_nodes if n.get('receiver')], each)
    L.append(f'버튼 {sum(c for _, c in btn)}개:')
    L += ['  ' + gline(n, c) for n, c in btn[:limit]]
    if len(btn) > limit:
        L.append(f'  … {len(btn) - limit}줄 더 (--buttons --owner 로 좁힌다)')
    txt = grouped([n for n in useful_nodes if n.get('text') and not n.get('receiver')], each)
    L.append(f'글자 {sum(c for _, c in txt)}개:')
    L += ['  ' + gline(n, c) for n, c in txt[:limit]]
    if len(txt) > limit:
        L.append(f'  … {len(txt) - limit}줄 더 (--texts --owner 로 좁힌다)')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--platform', choices=('ios', 'aos', 'mac'))
    ap.add_argument('--device')
    ap.add_argument('--file')
    for k in ('owner', 'inst', 'text', 'type'):
        ap.add_argument(f'--{k}')
    for k in ('tappable', 'buttons', 'texts', 'all', 'json', 'each'):
        ap.add_argument(f'--{k}', action='store_true')
    ap.add_argument('--limit', type=int, default=60)
    a = ap.parse_args()
    if a.file:
        data = qc.load_json(a.file)
        scene, nodes = data.get('scene') or '-', [n for n in data.get('nodes', []) if n.get('visible', True) is not False]
    elif a.platform:
        from flowlib import Device
        dev = Device(a.platform, qc.WORKSPACE, os.path.join(qc.RUNS, '_capture'), a.device)
        try:
            scene, nodes = dev.scene(), qc.visible(dev.tree())
        except Exception as e:  # noqa: BLE001 — 기기 쪽 실패는 그대로 알린다
            print(f'기기에서 화면을 읽지 못했다: {e}')
            return 3
    else:
        ap.print_usage(sys.stderr)
        return 2
    filtered = any([a.owner, a.inst, a.text, a.type, a.tappable, a.buttons, a.texts])
    if a.json:
        hit = pick(nodes, a) if filtered else [n for n in nodes if a.all or useful(n)]
        keys = ('id', 'owner', 'inst', 'name', 'text', 'receiver', 'enabled', 'blockedByDesc', 'rect')
        print(json.dumps({'scene': scene, 'count': len(hit), 'nodes': [{k: n[k] for k in keys if n.get(k) not in (None, '')} for n in hit[:a.limit]]},
                         ensure_ascii=False))
        return 0
    if not filtered:
        print(summary(scene, nodes, a.limit, a.each))
        return 0
    hit = pick(nodes, a)
    rows = grouped(hit, a.each)
    print(f'화면: {scene} · 맞는 노드 {len(hit)}개' + (f' (앞 {a.limit}줄)' if len(rows) > a.limit else ''))
    for n, c in rows[:a.limit]:
        print('  ' + gline(n, c))
    return 0


if __name__ == '__main__':
    sys.exit(main())
