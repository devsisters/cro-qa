#!/usr/bin/env python3
"""정답 스크린샷과 실제 스크린샷을 비교한다. 표준 라이브러리 + macOS 기본 `sips` 만 쓴다(설치할 것 없음).

  python3 imgdiff.py <expected.png> <actual.png> [--mask x,y,w,h ...] [--out-dir DIR]

방식
  1. 두 이미지를 sips 로 같은 크기(가로 WIDTH px)의 BMP 로 줄인다. 해상도·기기 차이를 흡수한다
  2. 마스크(바뀌어도 되는 영역 — 재화·시간·MID 등)는 비교에서 뺀다. 좌표는 축소 전 원본 픽셀, 원점 왼쪽 위
  3. 픽셀 차이(RGB 평균 절댓값)가 PIXEL_DELTA 를 넘는 픽셀의 비율 = changed
  4. 바뀐 픽셀을 칸(CELL px) 단위로 묶어 이어진 덩어리 = regions (원본 픽셀 좌표로 돌려준다)

출력(JSON 한 줄): {"ok", "changed", "regions":[[x,y,w,h]...], "size":[w,h], "crops":[...]}
--out-dir 를 주면 덩어리마다 정답·실제 크롭 PNG 를 만든다(판정 모델에게 줄 것).
exit: 0 비교 완료(판정은 changed 로 한다), 2 사용법, 3 이미지 읽기 실패
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile

WIDTH = 320          # 비교 해상도(가로). 세로는 비율대로
PIXEL_DELTA = 40     # 0~255. 압축·보간 노이즈보다 크고, 글자·아이콘 변화보다 작게
CELL = 8             # 덩어리를 묶는 칸 크기(축소 해상도 px)
MIN_CELL_PIXELS = 4  # 칸 안에 바뀐 픽셀이 이만큼은 있어야 그 칸을 바뀐 것으로 본다


class ImageError(Exception):
    pass


def size_of(path):
    r = subprocess.run(['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', path], capture_output=True, text=True)
    vals = [int(line.split(':')[1]) for line in r.stdout.splitlines() if 'pixel' in line]
    if r.returncode or len(vals) != 2:
        raise ImageError(f'sips 로 크기를 읽지 못했다: {path}')
    return vals[0], vals[1]


def load_small(path, width=WIDTH, height=None):
    """sips 로 축소해 BMP 로 읽는다 → (w, h, rows[ [ (r,g,b), ... ], ... ]) 위에서 아래 순서."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'x.bmp')
        args = ['sips', '-s', 'format', 'bmp']
        args += ['-z', str(height), str(width)] if height else ['--resampleWidth', str(width)]
        r = subprocess.run(args + [path, '--out', out], capture_output=True, text=True)
        if r.returncode or not os.path.exists(out):
            raise ImageError(f'sips 변환 실패: {path} {r.stderr[-200:]}')
        with open(out, 'rb') as f:
            data = f.read()
    return parse_bmp(data)


def parse_bmp(data):
    if data[:2] != b'BM':
        raise ImageError('BMP 아님')
    offset = struct.unpack('<I', data[10:14])[0]
    w, h, _planes, bpp = struct.unpack('<iiHH', data[18:30])
    if bpp not in (24, 32):
        raise ImageError(f'지원하지 않는 BMP 비트수 {bpp}')
    step = bpp // 8
    stride = (w * step + 3) & ~3
    top_down = h < 0
    h = abs(h)
    rows = []
    for i in range(h):
        y = i if top_down else h - 1 - i
        base = offset + y * stride
        line = data[base:base + w * step]
        rows.append([(line[x * step + 2], line[x * step + 1], line[x * step]) for x in range(w)])
    return w, h, rows


def compare(expected, actual, masks=(), width=WIDTH):
    """masks 는 expected 원본 픽셀 좌표(왼쪽 위 원점)."""
    ew, eh = size_of(expected)
    aw, ah = size_of(actual)
    w, h, a_rows = load_small(expected, width)
    # 실제 이미지는 정답과 같은 축소 크기로 맞춘다(비율이 다르면 늘려서라도 맞춘다 — 비율 차이는 note 로 알린다)
    _, _, b_rows = load_small(actual, w, h)
    sx, sy = ew / w, eh / h
    masked = [[False] * w for _ in range(h)]
    for (mx, my, mw, mh) in masks:
        x0, y0 = max(0, int(mx / sx)), max(0, int(my / sy))
        x1, y1 = min(w, int((mx + mw) / sx) + 1), min(h, int((my + mh) / sy) + 1)
        for y in range(y0, y1):
            row = masked[y]
            for x in range(x0, x1):
                row[x] = True
    changed = 0
    counted = 0
    cw, ch = (w + CELL - 1) // CELL, (h + CELL - 1) // CELL
    cells = [[0] * cw for _ in range(ch)]
    for y in range(h):
        ra, rb, rm = a_rows[y], b_rows[y], masked[y]
        for x in range(w):
            if rm[x]:
                continue
            counted += 1
            pa, pb = ra[x], rb[x]
            if (abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2])) / 3 > PIXEL_DELTA:
                changed += 1
                cells[y // CELL][x // CELL] += 1
    regions = []
    seen = set()
    for cy in range(ch):
        for cx in range(cw):
            if cells[cy][cx] < MIN_CELL_PIXELS or (cx, cy) in seen:
                continue
            stack, members = [(cx, cy)], []
            seen.add((cx, cy))
            while stack:
                px, py = stack.pop()
                members.append((px, py))
                for nx, ny in ((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)):
                    if 0 <= nx < cw and 0 <= ny < ch and (nx, ny) not in seen and cells[ny][nx] >= MIN_CELL_PIXELS:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            x0 = min(m[0] for m in members) * CELL
            y0 = min(m[1] for m in members) * CELL
            x1 = min(w, (max(m[0] for m in members) + 1) * CELL)
            y1 = min(h, (max(m[1] for m in members) + 1) * CELL)
            regions.append([round(x0 * sx), round(y0 * sy), round((x1 - x0) * sx), round((y1 - y0) * sy)])
    regions.sort(key=lambda r: -r[2] * r[3])
    result = {'ok': True, 'changed': round(changed / counted, 4) if counted else 0.0, 'regions': regions,
              'size': [ew, eh], 'actualSize': [aw, ah], 'maskedRatio': round(1 - counted / (w * h), 4)}
    if abs(ew / eh - aw / ah) > 0.01:
        result['note'] = f'화면 비율이 다르다(정답 {ew}x{eh}, 실제 {aw}x{ah}) — 다른 기종의 정답지일 수 있다'
    return result


def crop(src, rect, out, pad=12):
    """원본 픽셀 rect(왼쪽 위 원점)를 잘라 PNG 로 저장한다."""
    iw, ih = size_of(src)
    x, y, w, h = rect
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(iw, x + w + pad), min(ih, y + h + pad)
    r = subprocess.run(['sips', '-c', str(y1 - y0), str(x1 - x0), '--cropOffset', str(y0), str(x0), src, '--out', out],
                       capture_output=True, text=True)
    if r.returncode:
        raise ImageError(f'크롭 실패: {r.stderr[-200:]}')
    return out


def crops_for(expected, actual, regions, out_dir, prefix, limit=4):
    """덩어리마다 정답·실제 크롭을 만든다. 실제 이미지 크기가 다르면 비율로 옮긴다."""
    os.makedirs(out_dir, exist_ok=True)
    ew, eh = size_of(expected)
    aw, ah = size_of(actual)
    out = []
    for i, (x, y, w, h) in enumerate(regions[:limit]):
        e = crop(expected, [x, y, w, h], os.path.join(out_dir, f'{prefix}-r{i}-expected.png'))
        ar = [round(x * aw / ew), round(y * ah / eh), round(w * aw / ew), round(h * ah / eh)]
        a = crop(actual, ar, os.path.join(out_dir, f'{prefix}-r{i}-actual.png'))
        out.append({'region': [x, y, w, h], 'expected': e, 'actual': a})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('expected')
    ap.add_argument('actual')
    ap.add_argument('--mask', action='append', default=[], help='x,y,w,h (정답 원본 픽셀, 왼쪽 위 원점)')
    ap.add_argument('--out-dir')
    a = ap.parse_args()
    try:
        masks = [tuple(int(v) for v in m.split(',')) for m in a.mask]
    except ValueError:
        print('--mask 는 x,y,w,h 정수', file=sys.stderr)
        return 2
    try:
        res = compare(a.expected, a.actual, masks)
        if a.out_dir and res['regions']:
            res['crops'] = crops_for(a.expected, a.actual, res['regions'], a.out_dir, 'diff')
    except ImageError as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))
        return 3
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
