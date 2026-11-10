"""기기 플로우 공통 라이브러리 — gb_device.py(AgentBridge) 위에서 화면을 이름으로 찾아 누르고, 실패를 분류한다.

실패 분류(FlowFailure.kind):
  NAME_MISSING  기대한 노드 이름·글자가 트리에 아예 없다 → UI(ccb) 변경 의심. 화면 자체는 맞을 수 있다
  BLOCKED       노드는 있는데 다른 노드가 확실히 덮고 있다 → 팝업·순서 문제
  NOT_REACHED   기대한 화면(씬·글자)이 제한 시간 안에 나오지 않았다 → 화면이 다르거나 흐름이 바뀌었다
  BRIDGE        브리지·기기 연결 실패 → 환경 문제
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GB_DEVICE = os.path.join(os.path.dirname(HERE), 'gb_device.py')
# 짧고 자주 부르는 브리지 명령 — 프로세스를 띄우지 않고 부른다. launch·screenshot 처럼 외부 명령을 오래 기다리는 것은 따로 띄운다
IN_PROCESS = {'ping', 'scene', 'tree', 'tap', 'swipe', 'scroll'}
_GB_DEVICE_MOD = None


def _gb_device():
    global _GB_DEVICE_MOD
    if _GB_DEVICE_MOD is None:
        spec = importlib.util.spec_from_file_location('gb_device_inproc', GB_DEVICE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GB_DEVICE_MOD = mod
    return _GB_DEVICE_MOD


class FlowFailure(Exception):
    def __init__(self, kind, step, detail):
        super().__init__(f'{kind} at {step}: {detail}')
        self.kind = kind
        self.step = step
        self.detail = detail


def load_devices():
    with open(os.path.join(HERE, 'devices.json'), encoding='utf-8') as f:
        return json.load(f)


class Device:
    """플랫폼 하나. 모든 호출은 gb_device.py 를 거친다(브리지 토큰·연결은 그쪽이 맡는다)."""

    def __init__(self, platform, checkout, out_dir, device=None, runner=None):
        devices = load_devices()
        self.platform = platform
        self.checkout = checkout
        self.out_dir = out_dir
        cfg = devices.get(platform, {})
        self.args = ['--platform', cfg.get('platform', platform)]
        dev = device or cfg.get('device')
        self.device_id = dev or ''
        if dev:
            self.args += ['--device', dev]
        self.runner = runner or self._run
        self.log = []
        self.shot_error = None

    def _run(self, *args):
        if args and args[0] in IN_PROCESS:
            return self._run_here(args)
        r = subprocess.run(['python3', GB_DEVICE, *args, *self.args, '--checkout', self.checkout],
                           capture_output=True, text=True)
        lines = r.stdout.strip().splitlines()
        try:
            return json.loads(lines[-1]) if lines else {'ok': False, 'error': r.stderr[-300:]}
        except ValueError:
            return {'ok': False, 'error': r.stdout[-300:]}

    def _run_here(self, args):
        """브리지 명령은 이 프로세스 안에서 gb_device 를 부른다 — 명령마다 파이썬을 새로 띄우는 0.1초를 아낀다.
        출력·종료 코드 형식은 따로 띄운 것과 같다(gb_device.main 의 마지막 JSON 줄)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            _gb_device().main([*args, *self.args, '--checkout', self.checkout])
        lines = out.getvalue().strip().splitlines()
        try:
            return json.loads(lines[-1]) if lines else {'ok': False, 'error': 'gb_device 출력 없음'}
        except ValueError:
            return {'ok': False, 'error': out.getvalue()[-300:]}

    def call(self, *args):
        return self.runner(*args)

    # --- 읽기 ---
    def scene(self):
        return self.call('scene').get('result', {}).get('top')

    def tree(self):
        d = self.call('tree', '--max-nodes', '8000')
        if not d.get('ok', True) and 'result' not in d:
            raise FlowFailure('BRIDGE', 'tree', d.get('error'))
        return d.get('result', d)

    def nodes(self):
        """보이는(잘리지 않은) 노드만."""
        return [n for n in self.tree().get('nodes', [])
                if n.get('clipped') is not True and not n.get('offscreen')]

    def find(self, name=None, owner=None, text=None, inst=None, nodes=None):
        out = []
        for n in (nodes if nodes is not None else self.nodes()):
            if owner is not None and n.get('owner') != owner:
                continue
            if inst is not None and n.get('inst') != inst:
                continue
            if text is not None and n.get('text') != text:
                continue
            if name is not None and name not in (n.get('inst'), n.get('name'), n.get('text')):
                continue
            out.append(n)
        return out

    def texts(self, owner=None, inst=None):
        return [n.get('text') for n in self.find(owner=owner, inst=inst) if n.get('text')]

    # --- 조작 ---
    def tap(self, name, step=None, index=None):
        """이름·글자로 누른다. 실패를 분류해 던진다."""
        args = ['tap', '--node', name] + (['--index', str(index)] if index is not None else [])
        r = self.call(*args)
        step = step or f'tap {name}'
        if r.get('ok'):
            self.log.append({'step': step, 'ok': True, 'result': r.get('result')})
            return r.get('result', {})
        err = str(r.get('error'))
        if err.startswith('blocked by'):
            raise FlowFailure('BLOCKED', step, err)
        if 'node not found' in err:
            raise FlowFailure('NAME_MISSING', step, f'{name} 이(가) 트리에 없다 (scene={self.scene()})')
        raise FlowFailure('BRIDGE', step, err)

    def tap_xy(self, x, y, step=None):
        r = self.call('tap', '--x', f'{x:.1f}', '--y', f'{y:.1f}')
        if not r.get('ok'):
            raise FlowFailure('BRIDGE', step or f'tap {x},{y}', r.get('error'))
        return r.get('result', {})

    def tap_node(self, node, step=None):
        x, y, w, h = node['rect']
        return self.tap_xy(x + w / 2, y + h / 2, step)

    def swipe(self, x1, y1, x2, y2, ms=600):
        return self.call('swipe', '--x1', f'{x1:.0f}', '--y1', f'{y1:.0f}', '--x2', f'{x2:.0f}', '--y2', f'{y2:.0f}',
                         '--duration-ms', str(ms))

    def visible_size(self):
        return self.call('ping').get('result', {}).get('visibleSize', [568, 320])

    def shot(self, name):
        os.makedirs(self.out_dir, exist_ok=True)
        path = os.path.join(self.out_dir, f'{self.platform}-{name}-{int(time.time() * 1000)}.png')
        r = self.call('screenshot', path)
        if r.get('ok') and os.path.isfile(path):
            self.shot_error = None
            return path
        self.shot_error = str(r.get('error') or '캡처 파일이 만들어지지 않았다')[-300:]
        return None

    # --- 대기 ---
    def wait(self, predicate, timeout, step, expect, interval=0.4):
        end = time.time() + timeout
        while time.time() < end:
            value = predicate()
            if value:
                return value
            time.sleep(interval)
        raise FlowFailure('NOT_REACHED', step, f'{timeout}s 안에 {expect} 가 나오지 않았다 (scene={self.scene()})')

    def wait_text(self, text, timeout, step):
        return self.wait(lambda: next(iter(self.find(text=text)), None), timeout, step, f'글자 「{text}」')

    def wait_scene(self, names, timeout, step, stable=2.0):
        """씬이 names 중 하나가 되고 stable 초 동안 유지될 때까지 기다린다(전환 중 cover 를 피한다)."""
        names = (names,) if isinstance(names, str) else tuple(names)

        def ok():
            if self.scene() in names:
                time.sleep(stable)
                return self.scene() in names
            return False
        return self.wait(ok, timeout, step, f'씬 {names}')

    # --- 팝업 ---
    def close_popup(self, owner):
        """owner 레이어의 닫기 버튼을 누른다. 이름(_btnClose·_btnNo·_btnConfirm) → 글자(닫기·확인) →
        오른쪽 위 작은 활성 버튼 순으로 찾는다."""
        ns = self.nodes()
        for inst in ('_btnClose', '_btnNo', '_btnConfirm'):
            hit = [n for n in ns if n.get('owner') == owner and n.get('inst') == inst and n.get('receiver')]
            if hit:
                return self.tap_node(hit[-1], f'close {owner}')
        for text in ('닫기', '확인'):
            hit = [n for n in ns if n.get('owner') == owner and n.get('text') == text]
            if hit:
                return self.tap_node(hit[-1], f'close {owner}')
        small = [n for n in ns if n.get('owner') == owner and n.get('receiver') == 'button'
                 and n.get('rect') and n['rect'][2] <= 60 and n['rect'][3] <= 60]
        if small:
            return self.tap_node(max(small, key=lambda n: n['rect'][0] + n['rect'][1]), f'close {owner}')
        # 닫기 버튼 없이 「Touch!」 만 있는 연출 화면(신규 유저 특별 보상 PopUpdateHighlight 등) — 화면 아무 데나 누르면 닫힌다
        if [n for n in ns if n.get('owner') == owner and n.get('text') == 'Touch!']:
            w, h = self.visible_size()[:2]
            return self.tap_xy(w / 2, h / 2, f'close {owner} (Touch!)')
        return None
