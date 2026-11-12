#!/usr/bin/env node
// chrome_cdp.mjs — QA 키트 전용 Chrome 창(별도 프로필)을 원격 디버깅(CDP)으로 조작한다. 사내 dev 웹 하나만 쓴다:
//   · 타임머신(stove.devspie.com/app/timemachine) — dev 서버(gb-*) 시간 조회·변경. timemachine.py 를 거친다
//
// 별도 프로필(workspace/chrome-profile)로 띄운다 — 평소 쓰는 Chrome 과 로그인·쿠키가 섞이지 않고, Chrome 은 기본 프로필에서
// 원격 디버깅을 막는다. 처음 한 번 사람이 이 창에서 stove 에 로그인한다. 마카롱(계정 상태)은 macaron_api.py 가 브라우저 없이 부른다.
//
// 이 도구가 하지 않는 것: 쿠키·스토리지·토큰 읽기, 임의 클릭·입력.
// 위험: 포트가 열려 있는 동안은 이 맥의 다른 프로세스도 이 창을 조작할 수 있다. 127.0.0.1 에만 연다. 다 쓰면 창을 닫는다.
//
//   node chrome_cdp.mjs status | launch | open <url> | activate <targetId> | read <targetId> [--chars N] [--selector CSS]
//   node chrome_cdp.mjs shot <targetId> <out.png> | close <targetId>
//   node chrome_cdp.mjs page-text <url> [--wait ms]   새 탭으로 열어 본문을 읽고 닫는다(타임머신 응답 읽기용)
import { execFileSync, spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const PORT = process.env.QA_CDP_PORT || '9444';
const PROFILE = process.env.QA_CHROME_PROFILE || new URL('../../workspace/chrome-profile', import.meta.url).pathname;
const CHROME = process.env.QA_CHROME_APP || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = `http://127.0.0.1:${PORT}`;
const [, , cmd, ...args] = process.argv;

async function up() {
  try { return await (await fetch(`${BASE}/json/version`, { signal: AbortSignal.timeout(2000) })).json(); }
  catch { return null; }
}

function profileRunning() {
  // 이 키트 프로필로 떠 있는 Chrome 만 센다(평소 쓰는 Chrome 은 건드리지 않는다)
  try { return execFileSync('pgrep', ['-f', '--', `--user-data-dir=${PROFILE}`], { encoding: 'utf8' }).trim().split('\n').filter(Boolean); }
  catch { return []; }
}

async function session(target) {
  const list = await (await fetch(`${BASE}/json/list`)).json();
  const t = list.find(x => x.id === target);
  if (!t) throw new Error(`탭 없음: ${target}`);
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  let id = 0; const pend = new Map();
  ws.onmessage = m => { const d = JSON.parse(m.data); if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); } };
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  // 탭이 뒤에 있거나 큰 문서를 다루면 응답이 오지 않을 때가 있다 — 90초 넘으면 실패로 끝낸다(멈춰 있지 않게)
  // 응답이 오면 타이머를 지운다 — 남겨 두면 결과를 낸 뒤에도 node 가 그 시간(90초)만큼 끝나지 않는다
  const send = (method, params = {}) => new Promise((r, j) => {
    const i = ++id;
    const timer = setTimeout(() => { if (pend.has(i)) { pend.delete(i); j(new Error(`CDP 응답 없음(90초): ${method}`)); } }, Number(process.env.QA_CDP_TIMEOUT_MS || 90000));
    pend.set(i, d => { clearTimeout(timer); r(d); });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  return { send, close: () => ws.close() };
}

function opt(name, dflt) { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; }

const out = o => console.log(JSON.stringify(o, null, 1));

try {
  if (cmd === 'status') {
    const v = await up();
    out({ port: PORT, cdp: v ? v.Browser : null, profile: PROFILE, profile_processes: profileRunning().length });
  } else if (cmd === 'launch') {
    if (await up()) { out({ ok: true, note: '이미 포트가 열려 있다' }); process.exit(0); }
    if (profileRunning().length) {
      out({ ok: false, reason: '키트 프로필 Chrome 이 디버깅 포트 없이 떠 있다 — 그 창을 닫고 다시 launch 한다' });
      process.exit(3);
    }
    const { existsSync, mkdirSync } = await import('node:fs');
    if (!existsSync(CHROME)) { out({ ok: false, reason: `Chrome 이 없다: ${CHROME} — SETUP.md 대로 설치한다` }); process.exit(4); }
    mkdirSync(PROFILE, { recursive: true });
    spawn(CHROME, [`--remote-debugging-port=${PORT}`, '--remote-debugging-address=127.0.0.1', `--user-data-dir=${PROFILE}`,
                   '--no-first-run', '--no-default-browser-check', 'about:blank'], { stdio: 'ignore', detached: true }).unref();
    let v = null;
    for (let i = 0; i < 20 && !v; i++) { await new Promise(r => setTimeout(r, 750)); v = await up(); }
    out({ ok: !!v, cdp: v ? v.Browser : null, profile: PROFILE });
    process.exit(v ? 0 : 4);
  } else if (cmd === 'activate') {
    const r = await fetch(`${BASE}/json/activate/${args[0]}`); out({ activated: r.ok });
  } else if (cmd === 'page-text') {
    // 새 탭으로 열고, 로그인 화면이면 그렇다고 알리고, 본문을 읽은 뒤 닫는다
    if (!args[0]) throw new Error('page-text <url>');
    const t = await (await fetch(`${BASE}/json/new?${encodeURIComponent(args[0])}`, { method: 'PUT' })).json();
    await new Promise(r => setTimeout(r, Number(opt('--wait', 3000))));
    const s = await session(t.id);
    const r = await s.send('Runtime.evaluate', { returnByValue: true, expression:
      `({ url: location.href, title: document.title, text: (document.body && document.body.innerText || '').slice(0, 4000),
          login: !!document.querySelector('input[type=password]') || /oauth|login|sign in|accounts\\.google/i.test(location.href) })` });
    s.close(); await fetch(`${BASE}/json/close/${t.id}`);
    const v = r.result?.result?.value || {};
    out({ ok: !v.login, ...v, ...(v.login ? { error: '로그인이 필요하다 — 키트 Chrome 창에서 사람이 로그인한다' } : {}) });
    process.exit(v.login ? 5 : 0);
  } else if (cmd === 'open') {
    if (!args[0]) throw new Error('url 필요');
    const t = await (await fetch(`${BASE}/json/new?${encodeURIComponent(args[0])}`, { method: 'PUT' })).json();
    out({ targetId: t.id, url: args[0] });
  } else if (cmd === 'read') {
    const s = await session(args[0]);
    const chars = Number(opt('--chars', 4000)); const sel = opt('--selector', null);
    await new Promise(r => setTimeout(r, Number(opt('--wait', 1500))));
    const expr = `(() => { const root = ${sel ? `document.querySelector(${JSON.stringify(sel)})` : 'document.body'};
      const text = (root && root.innerText || '').slice(0, ${chars});
      return { title: document.title, url: location.href, ready: document.readyState, iframes: document.querySelectorAll('iframe').length,
               hasPassword: !!document.querySelector('input[type=password]'), textLen: (root && root.innerText || '').length, text }; })()`;
    const r = await s.send('Runtime.evaluate', { expression: expr, returnByValue: true });
    s.close(); out(r.result?.result?.value ?? r.result);
  } else if (cmd === 'shot') {
    const s = await session(args[0]);
    const r = await s.send('Page.captureScreenshot', { format: 'png' });
    s.close(); writeFileSync(args[1], Buffer.from(r.result.data, 'base64')); out({ saved: args[1] });
  } else if (cmd === 'close') {
    const r = await fetch(`${BASE}/json/close/${args[0]}`); out({ closed: r.ok });
  } else {
    console.error('usage: status | launch | activate <targetId> | page-text <url> | open <url> | read <targetId> [--chars N] [--selector CSS] | shot <targetId> <out.png> | close <targetId>');
    process.exit(2);
  }
} catch (e) { console.error(String(e.message || e)); process.exit(1); }
