#!/usr/bin/env python3
"""인게임 자동 되감기 케이스(JSON, kind=rewind)를 기기에서 N판씩 돌리고 판마다 판정한다.

  python3 tools/rewind_runner.py cases/<suite>.json --platform ios|aos [--case RW-01] [--device ID] [--out DIR]
  python3 tools/rewind_runner.py cases/<suite>.json --check        # 케이스 형식만 검사(기기 없음)

게임이 하는 일(DEBUG·GB_ENTERPRISE 빌드의 AutoRewind 모듈):
  트리거(interval·afterRevive·afterBonusReturn)가 오면 HUD 되감기 확인과 같은 순서로 되감고,
  되감은 뒤 체크포인트 시점 통계(부활·구멍 구출·보너스 진입)가 같은지 대조해 이벤트로 남긴다.
  점수·충돌·낙하 어긋남은 게임의 기존 desync 판정이 rewind_fail 로 남긴다.
이 실행기가 하는 일: 테스트 화면 이동 → 트리거 설정 → 카드 장착(고정 + 랜덤) → 맵 시작 →
  이벤트·캡처·앱 로그 수집 → 판 판정 → runs/<suite>-<platform>-<시각>/report.md · results.tsv · results.json

판 판정
  PASS    되감기 1회 이상 성공, rewind_fail · state_mismatch 0
  FAIL    rewind_fail(재시뮬레이션 어긋남) 또는 state_mismatch(되감은 뒤 통계 불일치)
  ERROR   앱 종료(크래시·assert)·멈춤(제한 시간)·브리지 끊김·장착/맵 오류
  UNSURE  되감기가 한 번도 일어나지 않았다(트리거 조건 미발생 — 예: 부활이 없었다)
exit: 0 전부 PASS · 1 FAIL/UNSURE 있음 · 2 사용법·형식 · 3 ERROR 있음
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'device_flows'))

import qa_common as qc  # noqa: E402


class _KeepRunningStdout:
    """QA 앱이 재시작돼 출력 파이프가 끊겨도 판(특히 사람이 하는 녹화)을 끝까지 돌린다."""

    def __init__(self, stream):
        self._stream = stream
        self._broken = False

    def write(self, text):
        if not self._broken:
            try:
                return self._stream.write(text)
            except (BrokenPipeError, OSError):
                self._broken = True
        return len(text)

    def flush(self):
        if not self._broken:
            try:
                self._stream.flush()
            except (BrokenPipeError, OSError):
                self._broken = True

    def __getattr__(self, name):
        return getattr(self._stream, name)


sys.stdout = _KeepRunningStdout(sys.stdout)

TRIGGERS = ('interval', 'afterRevive', 'afterBonusReturn')
TEST_SCENE = 'SceneTestGameMode'
POLL_SEC = 2.0
INPUT_RANGES = (('actionsPerSec', 0, 10), ('slideRatio', 0, 1), ('doubleJumpRatio', 0, 1), ('abilityEverySec', 0, 600), ('mistakeRatio', 0, 1), ('timingOffset', -0.3, 0.3), ('slideJellyDy', 0, 120), ('timingTolerance', 0, 20), ('runJellyMaxDy', 0, 200), ('hazardPenalty', 0, 500), ('hazardMargin', 0, 40), ('rejumpLead', 0, 0.6), ('landMargin', 0, 40), ('jellyLineMin', 1, 10), ('backMargin', 0, 40), ('preciseMargin', 0, 30), ('pressDelay', 0, 0.2))


def validate(suite):
    errs = []
    if suite.get('kind') != 'rewind':
        errs.append('kind 가 "rewind" 가 아니다')
    cases = suite.get('cases')
    if not isinstance(cases, list) or not cases:
        return errs + ['cases 가 비었다']
    seen = set()
    for c in cases:
        cid = c.get('id')
        where = f'case {cid}'
        if not cid or cid in seen:
            errs.append(f'{where}: id 가 없거나 중복')
        seen.add(cid)
        if not isinstance(c.get('map'), str) or not c['map']:
            errs.append(f'{where}: map(테스트 맵 이름)이 없다')
        if not isinstance(c.get('plays', 1), int) or c.get('plays', 1) < 1:
            errs.append(f'{where}: plays 는 1 이상 정수')
        cards = c.get('cards', {})
        for key in ('cookie1', 'cookie2', 'pet'):
            v = cards.get(key, 'random')
            if v != 'random' and not isinstance(v, int):
                errs.append(f'{where}: cards.{key} 는 카드 id 또는 "random"')
            elif v == 0 and key != 'cookie2':
                errs.append(f'{where}: cards.{key} 는 비울 수 없다(0 은 쿠키2·보물만)')
        tr = cards.get('treasures', ['random'] * 3)
        if not isinstance(tr, list) or len(tr) != 3 or any(v != 'random' and not isinstance(v, int) for v in tr):
            errs.append(f'{where}: cards.treasures 는 3칸(카드 id · 0(빈칸) · "random")')
        trig = c.get('triggers')
        if not isinstance(trig, list):
            errs.append(f'{where}: triggers 는 목록(되감기 없이 달리기만 하려면 [])')
        else:
            for t in trig:
                if t.get('type') not in TRIGGERS:
                    errs.append(f'{where}: trigger type 은 {TRIGGERS} 중 하나')
                if not isinstance(t.get('count'), int) or t['count'] < 1:
                    errs.append(f'{where}: trigger count 는 1 이상 정수')
                if not isinstance(t.get('delaySec', 0), (int, float)) or t.get('delaySec', 0) < 0:
                    errs.append(f'{where}: trigger delaySec 는 0 이상')
                if t.get('point') is not None and (not isinstance(t.get('point'), int) or t['point'] < -1):
                    errs.append(f'{where}: trigger point 는 0(기본값)·1(5초 전)·2(10초 전)·3(15초 전)')
        if c.get('stopAfterSec') is not None and (not isinstance(c['stopAfterSec'], (int, float)) or c['stopAfterSec'] < 0):
            errs.append(f'{where}: stopAfterSec 는 0 이상(비우면 끝까지 달린다)')
        if c.get('target', 'latest') not in ('latest', 'oldest'):
            errs.append(f'{where}: target 은 latest 또는 oldest')
        if c.get('seed') is not None and (not isinstance(c['seed'], int) or c['seed'] < 0):
            errs.append(f'{where}: seed 는 0 이상 정수(비우면 매번 새 시드)')
        inp = c.get('input')
        if inp is not None:
            if not isinstance(inp, dict) or inp.get('mode', 'random') not in ('random', 'smart', 'none', 'record', 'replay'):
                errs.append(f'{where}: input.mode 는 random · smart · none · record · replay 중 하나')
            elif inp.get('mode') == 'replay' and inp.get('recording') is not None and not isinstance(inp.get('recording'), str):
                errs.append(f'{where}: input.recording 은 녹화 파일 이름(비우면 맵 이름.json)')
            else:
                for key, low, high in INPUT_RANGES:
                    v = inp.get(key)
                    if v is not None and (not isinstance(v, (int, float)) or not low <= v <= high):
                        errs.append(f'{where}: input.{key} 는 {low}~{high}')
                for flag in ('rescue', 'relay', 'stopOnCrash', 'precise', 'physics', 'search'):
                    if flag in inp and not isinstance(inp[flag], bool):
                        errs.append(f'{where}: input.{flag} 는 true/false')
                if inp.get('seed') is not None and (not isinstance(inp['seed'], int) or inp['seed'] < 0):
                    errs.append(f'{where}: input.seed 는 0 이상 정수(비우면 매번 새 시드)')
    return errs


def resolve_cards(spec, pools, rng):
    """고정 카드는 그대로, "random" 은 풀에서 겹치지 않게 뽑는다."""
    cards = {}
    used = set()
    for key, pool in (('cookie1', 'cookie'), ('cookie2', 'cookie'), ('pet', 'pet')):
        v = spec.get(key, 'random')
        if v == 'random':
            choices = [i for i in pools[pool] if i not in used]
            v = rng.choice(choices)
        cards[key] = v
        used.add(v)
    treasures = []
    for v in spec.get('treasures', ['random'] * 3):
        if v == 'random':
            v = rng.choice([i for i in pools['treasure'] if i not in used])
        treasures.append(v)
        if v:
            used.add(v)
    cards['treasures'] = treasures
    return cards


def judge_play(events, outcome, expect_rewind=True, limit_sec=None, stop_after=None):
    """limit_sec — 판당 제한 시간으로 끊은 판이면 그 초. 긴 맵을 앞부분만 확인하려고 거는 것이라 실패로 보지 않는다.
    stop_after — 되감기 목표 횟수를 채운 뒤 그 초만큼 더 달리고 그만둔 판이면 그 초. 이것도 실패로 보지 않는다."""
    types = [e.get('type') for e in events]
    if outcome:
        return 'ERROR', outcome
    if not expect_rewind:
        # 되감기 없이 달리기만 한 판 — 끝까지 돌았는지와 생존·충돌만 적는다
        over = next((e for e in events if e.get('type') in ('game_over', 'crash_stop', 'timeout_stop')), None)
        crashes = types.count('crash')
        survive = f'{over["t"]:.1f}초' if over else '끝 못 봄'
        death = next((e for e in events if e.get('type') == 'death'), None)
        cause = {'fall': '추락', 'hp': '체력 소진'}.get(death.get('cause'), '기타') if death else '-'
        if any(e.get('type') == 'crash_stop' for e in events):
            cause = '충돌로 중단'
        if any(e.get('type') == 'timeout_stop' for e in events):
            cause = '제한 시간'
        return ('PASS' if over else 'UNSURE'), f'달리기 {survive} · 충돌 {crashes}회 · 젤리 {over.get("jelly", "-") if over else "-"} · 끝 {cause}'
    fails = [e for e in events if e.get('type') in ('rewind_fail', 'state_mismatch')]
    if fails:
        e = fails[0]
        detail = e.get('detail') or ', '.join(f'{k}={v}' for k, v in e.items() if k not in ('seq', 'type', 't'))
        return 'FAIL', f'{e["type"]} (t={e.get("t")}) {detail}'
    done = types.count('rewind_done')
    if not done:
        skips = [e.get('reason') for e in events if e.get('type') == 'rewind_skip']
        if limit_sec:
            return 'UNSURE', f'제한 시간 {limit_sec}초 안에 되감기가 일어나지 않았다' + (f' (skip: {", ".join(skips)})' if skips else ' — 트리거 시점이 제한 시간보다 뒤이거나 조건이 없었을 수 있다')
        return 'UNSURE', '되감기가 일어나지 않았다' + (f' (skip: {", ".join(skips)})' if skips else ' — 트리거 조건(부활·보너스 복귀)이 없었을 수 있다')
    asked = types.count('rewind_request')
    return 'PASS', f'되감기 {done}회 성공' + (f' (요청 {asked}회)' if asked != done else '') + \
        (f' · 목표 횟수 뒤 {stop_after}초까지 확인' if stop_after is not None else '')


class RewindRunner:
    def __init__(self, dev, platform, out, device_id, recordings=None):
        self.recordings = recordings or os.path.join(qc.KIT, 'recordings')
        self.dev = dev
        self.platform = platform
        self.out = out
        self.device_id = device_id
        self.pools = None
        self.card_names = {}

    # --- 기기 ---
    def bridge(self, cmd, **fields):
        return self.dev.call(cmd, '--json', json.dumps(fields))

    def launch(self, log_path):
        args = ['launch']
        if self.platform == 'ios':
            args += ['--console-log', log_path]
            self.console_log = log_path
        if self.platform == 'mac':
            args += ['--restart']
        r = self.dev.call(*args)
        if not r.get('ok'):
            return f'launch 실패: {r.get("error")}'
        if not self.wait(lambda: self.dev.call('ping').get('ok'), 120):
            return '앱을 띄웠지만 브리지가 응답하지 않는다'
        return ''

    def wait(self, predicate, timeout, interval=2.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if predicate():
                    return True
            except Exception:  # noqa: BLE001 — 전환 중 브리지 오류는 다시 본다
                pass
            time.sleep(interval)
        return False

    def to_test_scene(self):
        import routes
        from flowlib import FlowFailure
        if self.dev.scene() == TEST_SCENE:
            return ''
        try:
            # 앱이 지난번 테스트 화면으로 바로 들어오기도 한다 — 로비를 기다리는 동안에도 테스트 화면이면 끝낸다
            end = time.time() + 900
            while True:
                scene = self.dev.scene()
                if scene == TEST_SCENE:
                    return ''
                if scene == routes.LOBBY:
                    break
                if scene and 'Result' in scene:
                    self.leave_result()
                    continue
                if time.time() > end:
                    return f'테스트 화면으로 가지 못했다: 900초 안에 로비·테스트 화면이 나오지 않았다 (scene={scene})'
                try:
                    routes.to_lobby(self.dev, timeout=20)
                except FlowFailure:
                    pass
            w, h = self.dev.visible_size()
            self.dev.swipe(20, 20, w - 20, h - 20, 600)
            self.dev.wait(lambda: self.dev.find(owner='PopDebugSetting', text='테스트용 화면으로 가기'), 10, 'debug console', '「테스트용 화면으로 가기」')
            self.dev.tap('테스트용 화면으로 가기', 'go test scene')
            self.dev.wait_scene(TEST_SCENE, 60, 'test scene')
            if self.dev.find(owner='PopDebugSetting'):
                w, h = self.dev.visible_size()
                self.dev.tap_xy(w - 20, 5, 'close debug console')
        except FlowFailure as e:
            return f'테스트 화면으로 가지 못했다: {e.kind} {e.detail}'
        return ''

    def card_pools(self):
        if self.pools is None:
            pools = {}
            for cat in ('cookie', 'pet', 'treasure'):
                r = self.bridge('testmode', op='cards', category=cat)
                if not r.get('ok'):
                    raise RuntimeError(f'카드 목록을 못 받았다({cat}): {r.get("error")}')
                pools[cat] = r['result']['ids']
                self.card_names.update({i: n for i, n in zip(r['result']['ids'], r['result'].get('names') or []) if n})
            self.pools = pools
        return self.pools

    def device_log_start(self, log_path):
        self.log_dumped = False
        # iOS 는 앱을 띄울 때 연 콘솔 로그 하나에 계속 쌓인다 — 판 시작 위치를 적어 두고 그 뒤만 판 로그로 쓴다
        ios_log = getattr(self, 'console_log', None) if self.platform == 'ios' else None
        self.play_log = ios_log or log_path
        self.play_log_from = os.path.getsize(self.play_log) if os.path.exists(self.play_log) else 0
        if self.platform == 'aos':
            self.adb('logcat', '-c')
        if self.platform == 'mac':
            # 맥 앱은 표준 출력이 이 파일에 이어 붙는다 — 판 시작 위치부터 끝까지 잘라 온다
            self.mac_log = os.path.join(self.dev.checkout, '.gb-agent', 'device', 'mac-app.log')
            self.mac_log_from = os.path.getsize(self.mac_log) if os.path.exists(self.mac_log) else 0
        self.log_path = log_path

    def device_log_end(self):
        if getattr(self, 'log_dumped', False):
            return
        self.log_dumped = True
        if self.platform == 'aos':
            dump = self.adb('logcat', '-d', '-v', 'time')
            with open(self.log_path, 'a', encoding='utf-8', errors='replace') as f:
                f.write(dump)
        if self.platform == 'mac' and os.path.exists(self.mac_log):
            with open(self.mac_log, 'rb') as src:
                src.seek(self.mac_log_from)
                dump = src.read().decode('utf-8', 'replace')
            with open(self.log_path, 'a', encoding='utf-8', errors='replace') as f:
                f.write(dump)

    def adb(self, *args):
        import gb_device
        serial = self.device_id or qc.load_json(os.path.join(HERE, 'device_flows', 'devices.json')).get('aos', {}).get('device')
        r = subprocess.run([gb_device.ADB, '-s', serial, *args], capture_output=True, text=True, errors='replace')
        return r.stdout

    def save_play_log(self, res, pdir):
        """실패한 판은 그 판의 게임 로그를 판 폴더에 남긴다 — 왜 실패했는지 찾는 데 쓴다."""
        if res.get('verdict') not in ('FAIL', 'ERROR'):
            return
        self.device_log_end()
        text = ''
        if self.platform == 'aos':
            # 판 시작에 logcat 을 비웠으니 지금 남은 것이 이 판이다 — 게임 프로세스 로그만 남긴다(시스템 로그는 뺀다)
            pid = self.adb('shell', 'pidof', 'com.devsisters.gb').strip().split()
            if len(pid) == 1 and pid[0].isdigit():
                text = self.adb('logcat', '-d', '-v', 'time', f'--pid={pid[0]}')
        if not text:
            try:
                with open(self.play_log, 'rb') as f:
                    f.seek(getattr(self, 'play_log_from', 0))
                    text = f.read().decode('utf-8', 'replace')
            except (OSError, AttributeError):
                text = '(기기 로그를 읽지 못했다)'
        if len(text) > 4_000_000:
            text = '…(앞부분 생략)\n' + text[-4_000_000:]
        head = [f'# {res["case"]} {res["play"]}판 — {res["verdict"]}: {res["reason"]}', '', '## 되감기 이벤트(게임 기록)']
        for e in res.get('events', []):
            if e['type'] != 'checkpoint':
                head.append(f't={e["t"]:.2f} {e["type"]} ' + ', '.join(f'{k}={v}' for k, v in e.items() if k not in ('seq', 'type', 't')))
        head += ['', '## 기기 로그(이 판)', '']
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, 'game-log.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(head) + text)
        res['gameLog'] = 'game-log.txt'

    def fetch_shot(self, name, path):
        """게임이 남긴 캡처(되감기 직전·직후·실패)를 받아 저장한다. 저장은 다음 프레임에 끝나서 잠깐 기다려 다시 묻는다."""
        import base64
        for _ in range(4):
            r = self.bridge('autorewind', op='shot', name=name)
            png = (r.get('result') or {}).get('png') if r.get('ok') else None
            if png:
                with open(path, 'wb') as f:
                    f.write(base64.b64decode(png))
                return True
            time.sleep(0.5)
        return False

    def add_figure(self, res, pdir, label, name=None, t=None):
        """리포트 판 열에 넣을 캡처 — name 이 있으면 게임 캡처, 없으면 지금 기기 화면."""
        n = len(res['figures']) + 1
        if name:
            path = os.path.join(pdir, f'{n:02d}-{label.replace(" ", "_")}.png')
            ok = self.fetch_shot(name, path)
        else:
            path = self.dev.shot(label)
            ok = bool(path)
        if ok:
            res['figures'].append({'file': os.path.relpath(path, pdir), 'label': label, 't': t, 'shot': name})

    def app_death_reason(self):
        """앱이 죽었으면 로그에서 이유를 찾는다."""
        try:
            with open(self.log_path, encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            text = ''
        for marker in ('App terminated due to signal', 'assertion fail', 'FATAL EXCEPTION', 'Fatal signal', 'SIGABRT', 'SIGSEGV'):
            idx = text.rfind(marker)
            if idx >= 0:
                return text[idx:idx + 200].splitlines()[0]
        return '브리지가 끊겼다(앱 종료 추정 — 로그에 사유 없음)'

    # --- 한 판 ---
    def run_play(self, case, play, rng, pdir):
        os.makedirs(pdir, exist_ok=True)
        self.dev.out_dir = pdir
        res = {'case': case['id'], 'play': play, 'verdict': None, 'reason': '', 'cards': None, 'events': [], 'shots': [], 'figures': []}
        err = self.to_test_scene()
        if err:
            res['verdict'], res['reason'] = 'ERROR', err
            return res
        try:
            cards = resolve_cards(case.get('cards', {}), self.card_pools(), rng)
        except RuntimeError as e:
            res['verdict'], res['reason'] = 'ERROR', str(e)
            return res
        res['cards'] = cards
        name = lambda i: '없음' if i == 0 else f'{self.card_names.get(i, "?")}({i})'
        res['cardNames'] = {'cookie1': name(cards['cookie1']), 'cookie2': name(cards['cookie2']), 'pet': name(cards['pet']),
                            'treasures': [name(t) for t in cards['treasures']]}
        res['cardSeed'] = case['seed'] + play - 1
        r = self.bridge('autorewind', op='clear')
        fields = {'triggers': case['triggers'], 'target': case.get('target', 'latest')}
        if case.get('input'):
            # 판마다 다르게, 다시 돌리면 같게 — 시드는 케이스 시드 + 판 번호
            fields['input'] = dict(case['input'], seed=int(case['input'].get('seed') or 1) + play - 1)
            res['inputSeed'] = fields['input']['seed']
            if fields['input'].get('mode') == 'replay':
                # 녹화한 입력을 위치 기준으로 그대로 누른다
                path = os.path.join(self.recordings, fields['input'].pop('recording', None) or f'{case["map"]}.json')
                try:
                    rec = qc.load_json(path)
                    fields['input']['script'] = rec['acts']
                    if rec.get('gameSeed'):
                        fields['input']['gameSeed'] = int(rec['gameSeed'])
                except (OSError, ValueError, KeyError) as e:
                    res['verdict'], res['reason'] = 'ERROR', f'녹화 파일을 읽지 못했다({path}): {e}'
                    return res
        r = self.bridge('autorewind', op='set', **fields)
        if not r.get('ok'):
            res['verdict'], res['reason'] = 'ERROR', f'autorewind set 실패: {r.get("error")}'
            return res
        r = self.bridge('testmode', op='equip', **cards)
        if not r.get('ok'):
            res['verdict'], res['reason'] = 'ERROR', f'카드 장착 실패: {r.get("error")}'
            return res
        self.add_figure(res, pdir, '조합')
        r = self.bridge('testmode', op='play', map=case['map'])
        if not r.get('ok'):
            res['verdict'], res['reason'] = 'ERROR', f'맵 시작 실패: {r.get("error")}'
            return res

        since, outcome, events = 0, '', []
        # 판당 제한 시간은 판이 시작된 뒤(로딩 제외) 실제로 달린 시간이다 — 되감기로 다시 불러오는 동안은 세지 않는다
        limit = case.get('timeoutSec', 600)
        load_deadline = time.time() + 300
        deadline = None
        rewind_since = None
        quit_sent_at = None
        timed_out = False
        # 되감기 목표 횟수(트리거 횟수의 합)를 채우면 stopAfterSec 뒤에 그만둔다 — 비우면 끝까지 달린다
        stop_after = case.get('stopAfterSec')
        goal = sum(t.get('count', 0) for t in case.get('triggers') or [])
        stop_at = None
        stopped_early = False
        misses = 0
        game_over_at = None
        while True:
            now = time.time()
            if deadline is None and now > load_deadline:
                outcome = '300초 안에 판이 시작되지 않았다(멈춤 의심)'
                res['shots'].append(self.dev.shot('timeout'))
                break
            early = stop_at is not None and now > stop_at
            if rewind_since is None and quit_sent_at is None and (early or (deadline is not None and now > deadline)):
                # 앱을 다시 띄우지 않고 그만두기로 판을 끝낸다 — 결과 화면을 거쳐 테스트 화면으로 돌아가 다음 판을 이어 간다
                res['shots'].append(self.dev.shot('stop' if early else 'timeout'))
                stopped_early, timed_out = early, not early
                quit_sent_at = now
                if not self.bridge('autorewind', op='quit').get('ok'):
                    outcome = f'제한 시간 {limit}초 — 그만두기를 보내지 못했다(멈춤 의심)'
                    break
            if quit_sent_at is not None and now - quit_sent_at > 90:
                outcome = f'제한 시간 {limit}초 — 그만두기 뒤 90초 안에 판이 끝나지 않았다(멈춤 의심)'
                break
            r = self.bridge('autorewind', op='events', since=since)
            if not r.get('ok'):
                misses += 1
                if misses >= 5 and not self.dev.call('ping').get('ok'):
                    outcome = 'APP_DIED'
                    break
                time.sleep(POLL_SEC)
                continue
            misses = 0
            batch = r['result']['events']
            since = r['result'].get('next', since)
            for e in batch:
                events.append(e)
                if e['type'] == 'game_start' and deadline is None:
                    deadline = time.time() + limit
                if e['type'] == 'rewind_request' and rewind_since is None:
                    rewind_since = time.time()
                if e['type'] in ('rewind_done', 'rewind_fail') and rewind_since is not None:
                    if deadline is not None:
                        deadline += time.time() - rewind_since
                    rewind_since = None
                # 리포트 캡처 — 되감기 직전·직후·실패 시점(게임이 그 프레임을 저장해 둔다)
                label = {'rewind_request': '되감기 직전', 'rewind_done': '되감기 직후', 'state_mismatch': '실패', 'rewind_fail': '실패'}.get(e['type'])
                if label and e.get('shot') and not (e['type'] == 'rewind_done' and any(f.get('shot') == e['shot'] for f in res['figures'])):
                    self.add_figure(res, pdir, label, name=e['shot'], t=e.get('t'))
                if e['type'] in ('game_over', 'timeout_stop', 'crash_stop') and game_over_at is None:
                    game_over_at = time.time()
                if e['type'] == 'rewind_fail':
                    self.dismiss_rewind_fail()
                if (e['type'] == 'rewind_done' and stop_after is not None and stop_at is None and goal
                        and sum(1 for x in events if x['type'] == 'rewind_done') >= goal):
                    stop_at = time.time() + stop_after
            if any(e['type'] == 'result_screen' for e in events):
                break
            scene = self.dev.scene()
            if game_over_at and (scene == TEST_SCENE or time.time() - game_over_at > 60):
                break
            if any(e['type'] == 'rewind_fail' for e in events) and scene in (TEST_SCENE, None):
                break
            time.sleep(POLL_SEC)
        if outcome == 'APP_DIED':
            self.device_log_end()
            outcome = '앱 종료: ' + self.app_death_reason()
        res['events'] = events
        if (case.get('input') or {}).get('mode') == 'record':
            # 사람이 한 판의 입력(쿠키 위치 기준)을 맵 이름으로 저장한다 — 다음부터 replay 로 그대로 돌린다
            r = self.bridge('autorewind', op='recording')
            acts = (r.get('result') or {}).get('recording') or []
            os.makedirs(self.recordings, exist_ok=True)
            seed_ev = next((e for e in events if e.get('type') == 'recording'), {})
            rec = {'map': case['map'], 'cards': cards, 'recordedAt': time.strftime('%Y-%m-%d %H:%M:%S'),
                   'gameSeed': int((r.get('result') or {}).get('gameSeed') or seed_ev.get('gameSeed') or 0), 'acts': acts}
            for path in (os.path.join(self.recordings, f'{case["map"]}.json'), os.path.join(pdir, 'recording.json')):
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(rec, f, ensure_ascii=False)
            res['recording'] = {'file': f'{case["map"]}.json', 'acts': len(acts)}
        res['verdict'], res['reason'] = judge_play(events, outcome, expect_rewind=bool(case.get('triggers')),
                                                   limit_sec=limit if timed_out else None,
                                                   stop_after=stop_after if stopped_early else None)
        res['timedOut'] = timed_out and not outcome
        res['stoppedEarly'] = stopped_early and not outcome
        # 되감기마다 요청한 인게임 시각(playTime)과 돌아간 시각
        res['rewinds'] = []
        for e in events:
            if e['type'] == 'rewind_request':
                res['rewinds'].append({'at': e.get('t'), 'to': float(e['toT']) if e.get('toT') else None, 'trigger': e.get('trigger'),
                                       'point': e.get('point'), 'points': e.get('points'), 'result': '진행 중'})
            elif e['type'] in ('rewind_done', 'rewind_fail', 'state_mismatch') and res['rewinds'] and res['rewinds'][-1]['result'] == '진행 중':
                res['rewinds'][-1]['result'] = {'rewind_done': '성공', 'rewind_fail': '실패', 'state_mismatch': '상태 불일치'}[e['type']]
                if e['type'] == 'rewind_done' and res['rewinds'][-1]['to'] is None:
                    res['rewinds'][-1]['to'] = e.get('t')
            elif e['type'] == 'rewind_skip':
                res['rewinds'].append({'at': e.get('t'), 'to': None, 'trigger': e.get('trigger'), 'point': None, 'points': None,
                                       'result': f'건너뜀({e.get("reason")})'})
        if res['verdict'] in ('FAIL', 'ERROR') and not any(f['label'] == '실패' for f in res['figures']) and outcome != 'APP_DIED' and '앱 종료' not in outcome:
            self.add_figure(res, pdir, '실패')
        if res['timedOut']:
            res['reason'] += f' · 제한 시간 {limit}초까지 확인'
        if res.get('recording'):
            res['reason'] += f' · 녹화 {res["recording"]["acts"]}개 입력 → recordings/{res["recording"]["file"]}'
        res['shots'] = [s for s in res['shots'] if s]
        # 결과 화면이 떴으면 확인까지 눌러 테스트 화면으로 돌려 둔다 — 마지막 판도 다음 사람이 바로 쓸 수 있게
        if not outcome and any(e['type'] == 'result_screen' for e in events):
            time.sleep(2)
            res['leftResult'] = self.leave_result()
        with open(os.path.join(pdir, 'events.json'), 'w', encoding='utf-8') as f:
            json.dump(events, f, ensure_ascii=False, indent=1)
        res['afterScene'] = self.dev.scene() if not outcome else None
        return res

    def leave_result(self):
        """결과 화면에서 테스트 화면으로 돌아간다. 나가는 버튼 이름이 화면마다 달라 닫기 규칙(close_popup)을 쓴다."""
        for _ in range(6):
            scene = self.dev.scene()
            if scene == TEST_SCENE:
                return True
            if scene and 'Result' in scene:
                self.dev.close_popup(scene)
            time.sleep(3)
        return self.dev.scene() == TEST_SCENE

    def dismiss_rewind_fail(self):
        n = self.dev.find(owner='PopBrownOneButton', inst='_btnConfirm')
        if n:
            self.dev.tap('_btnConfirm', 'rewind fail confirm')


def combo_text(r):
    n = r.get('cardNames')
    if n:
        return f'쿠키1 {n["cookie1"]} · 쿠키2 {n["cookie2"]} · 펫 {n["pet"]} · 보물 {" / ".join(n["treasures"])}'
    c = r.get('cards') or {}
    return f'{c.get("cookie1")}·{c.get("cookie2")}·{c.get("pet")}·{"/".join(str(t) for t in c.get("treasures", []))}' if c else '-'


def fmt_t(t):
    return '-' if t is None else f'{float(t):.2f}초'


def write_report(out, results, suite_name, platform):
    rows = [r for c in results for r in c['plays']]
    counts = {v: sum(1 for r in rows if r['verdict'] == v) for v in ('PASS', 'FAIL', 'ERROR', 'UNSURE')}
    label = {'PASS': '통과', 'FAIL': '실패', 'ERROR': '진행 실패', 'UNSURE': '확인 필요'}
    L = [f'# 자동 되감기 — {suite_name} [{platform.upper()}]', '',
         f'판 {len(rows)} · 통과 {counts["PASS"]} · 실패 {counts["FAIL"]} · 진행 실패 {counts["ERROR"]} · 확인 필요 {counts["UNSURE"]}'
         + (f' · 제한 시간까지만 확인 {sum(1 for r in rows if r.get("timedOut"))}' if any(r.get('timedOut') for r in rows) else ''), '',
         '| 케이스 | 판 | 판정 | 사유 | 조합 | 되감기(요청 → 돌아간 인게임 시각) | 충돌 | 부활 | 구멍 구출 | 이어달리기 | 보너스타임 | 캡처 |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        base = f'{r["case"]}/play{r["play"]}'
        rw = '<br>'.join(f'{fmt_t(x["at"])} → {fmt_t(x["to"])} {x["result"]}' for x in r.get('rewinds', [])) or '-'
        ev = [e.get('type') for e in r.get('events', [])]
        crashes = ev.count('crash')
        counts_cols = f'{ev.count("revive")} | {ev.count("rescue_click")} | {ev.count("relay_click")} | {ev.count("bonus_enter")}'
        shots = ' '.join(f'<a href="{base}/{f["file"]}"><img src="{base}/{f["file"]}" height="60" title="{f["label"]}"></a>' for f in r.get('figures', [])) or '-'
        if r.get('gameLog'):
            shots += f'<br>[게임 로그]({base}/{r["gameLog"]})'
        L.append(f'| {r["case"]} | {r["play"]} | {label.get(r["verdict"], r["verdict"])} | {r["reason"]} | {combo_text(r)} | {rw} | {crashes}회 | {counts_cols} | {shots} |')
    with open(os.path.join(out, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    with open(os.path.join(out, 'results.tsv'), 'w', encoding='utf-8') as f:
        f.write('case\tplay\tverdict\treason\trewinds\n')
        for r in rows:
            ev = [e['type'] for e in r['events']]
            f.write(f'{r["case"]}\t{r["play"]}\t{r["verdict"]}\t{r["reason"]}\t{ev.count("rewind_done")}\n')
    with open(os.path.join(out, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump({'suite': suite_name, 'platform': platform, 'cases': results}, f, ensure_ascii=False, indent=1)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('suite_file')
    ap.add_argument('--platform', choices=('ios', 'aos', 'mac'))
    ap.add_argument('--checkout', help='mac: 앱을 빌드한 게임 checkout(기본은 키트 workspace)')
    ap.add_argument('--recordings', help='맵 녹화 파일 폴더(기본은 키트 recordings/)')
    ap.add_argument('--case')
    ap.add_argument('--device')
    ap.add_argument('--out')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--preset', help='서버 선택 창에서 고를 게임 서버 프리셋(기본 routes.PRESET)')
    a = ap.parse_args()
    suite = qc.load_json(a.suite_file)
    errs = validate(suite)
    if a.check or errs:
        print(json.dumps({'ok': not errs, 'errors': errs, 'cases': len(suite.get('cases', []))}, ensure_ascii=False, indent=1))
        return 0 if not errs else 2
    if not a.platform:
        ap.print_usage(sys.stderr)
        return 2
    from flowlib import Device
    if a.preset:
        import routes
        routes.PRESET = a.preset
    name = suite.get('suite') or os.path.splitext(os.path.basename(a.suite_file))[0]
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = a.out or os.path.join(qc.RUNS, f'{name}-{a.platform}-{stamp}')
    os.makedirs(out, exist_ok=True)
    dev = Device(a.platform, a.checkout or qc.WORKSPACE, out, a.device)
    runner = RewindRunner(dev, a.platform, out, a.device, a.recordings)
    wanted = set(a.case.split(',')) if a.case else None
    results = []
    log_index = 0
    need_launch = dev.call('ping').get('ok') is not True or a.platform == 'ios'
    for case in suite['cases']:
        if wanted and case['id'] not in wanted:
            continue
        # 시드를 비워 두면 실행할 때마다 새로 뽑는다. 판 시드 = 기준 + 판 번호 - 1 이고 리포트에 남아 그 판만 다시 돌릴 수 있다
        fresh = random.SystemRandom()
        card_base = case['seed'] if case.get('seed') is not None else fresh.randrange(1, 1_000_000)
        input_base = None
        if case.get('input'):
            input_base = case['input']['seed'] if case['input'].get('seed') is not None else fresh.randrange(1, 1_000_000)
        case = dict(case, seed=card_base, input=dict(case['input'], seed=input_base) if case.get('input') else case.get('input'))
        cres = {'id': case['id'], 'title': case.get('title', ''), 'plays': []}
        for play in range(1, case.get('plays', 1) + 1):
            log_index += 1
            log_path = os.path.join(out, f'device-log-{log_index}.txt')
            if need_launch:
                err = runner.launch(log_path)
                if err:
                    cres['plays'].append({'case': case['id'], 'play': play, 'verdict': 'ERROR', 'reason': err, 'events': [], 'shots': []})
                    print(f'[{a.platform}] ERROR  {case["id"]}#{play} {err}', flush=True)
                    continue
            runner.device_log_start(log_path)
            r = runner.run_play(case, play, random.Random(card_base + play - 1), os.path.join(out, case['id'], f'play{play}'))
            if r['verdict'] != 'ERROR':
                runner.device_log_end()
            runner.save_play_log(r, os.path.join(out, case['id'], f'play{play}'))
            cres['plays'].append(r)
            print(f'[{a.platform}] {r["verdict"]:6} {case["id"]}#{play} {r["reason"]}', flush=True)
            # 앱이 죽었거나 멈췄으면 다음 판 전에 다시 띄운다
            need_launch = r['verdict'] == 'ERROR'
        results.append(cres)
    counts = write_report(out, results, name, a.platform)
    print(json.dumps({'ok': True, 'out': out, **counts}, ensure_ascii=False))
    if counts['ERROR']:
        return 3
    return 1 if counts['FAIL'] or counts['UNSURE'] else 0


if __name__ == '__main__':
    sys.exit(main())
