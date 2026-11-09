#!/usr/bin/env node
// chrome_cdp.mjs — QA 키트 전용 Chrome 창(별도 프로필)을 원격 디버깅(CDP)으로 조작한다. 사내 dev 웹 두 곳만 쓴다:
//   · 마카롱(couchbase_modifier) — 테스트 계정 상태 조회·변경. 쓰기는 macaron_edit.py 를 거친다(백업·기대값·확인 창 대조·저장 뒤 비교)
//   · 타임머신(stove.devspie.com/app/timemachine) — dev 서버(gb-*) 시간 조회·변경. timemachine.py 를 거친다
//
// 별도 프로필(workspace/chrome-profile)로 띄운다 — 평소 쓰는 Chrome 과 로그인·쿠키가 섞이지 않고, Chrome 은 기본 프로필에서
// 원격 디버깅을 막는다. 처음 한 번 사람이 이 창에서 stove·마카롱에 로그인하고 인증서 경고(고급 → 계속)를 넘긴다.
//
// 이 도구가 하지 않는 것: 쿠키·스토리지·토큰 읽기, 임의 클릭·입력. 마카롱 Delete 는 절대 누르지 않는다.
// 위험: 포트가 열려 있는 동안은 이 맥의 다른 프로세스도 이 창을 조작할 수 있다. 127.0.0.1 에만 연다. 다 쓰면 창을 닫는다.
//
//   node chrome_cdp.mjs status | launch | open <url> | activate <targetId> | read <targetId> [--chars N] [--selector CSS]
//   node chrome_cdp.mjs shot <targetId> <out.png> | close <targetId>
//   node chrome_cdp.mjs macaron-lookup|macaron-get|macaron-replace|macaron-save|macaron-confirm …   (macaron_edit.py 가 부른다)
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
  const send = (method, params = {}) => new Promise((r, j) => {
    const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params }));
    setTimeout(() => { if (pend.has(i)) { pend.delete(i); j(new Error(`CDP 응답 없음(90초): ${method}`)); } }, Number(process.env.QA_CDP_TIMEOUT_MS || 90000));
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
  } else if (cmd === 'macaron-lookup') {
    const [target, bucket, key] = args;
    if (!target || !bucket || !key) throw new Error('macaron-lookup <targetId> <bucket> <key>');
    const s = await session(target);
    const chars = Number(opt('--chars', 4000));
    // 조회 한 동작만 한다. 누르는 요소를 `.search-button` 으로 고정하고, 그 요소가 Save/Delete 계열이면 멈춘다.
    const act = `(() => {
      if (!location.pathname.includes('/couchbase_modifier')) return {error: '마카롱 couchbase_modifier 탭이 아니다: ' + location.href};
      const sel = document.querySelector('select[name=bucket]'), inp = document.querySelector('input[name=key]');
      const btn = document.querySelector('button.search-button');
      if (!sel || !inp || !btn) return {error: '조회 요소를 못 찾았다(bucket/key/search-button)'};
      if (btn.matches('.btn-success,.btn-danger') || /save|delete/i.test(btn.innerText)) return {error: '검색 버튼이 저장/삭제로 보인다 — 멈춘다'};
      if (![...sel.options].some(o => o.value === ${JSON.stringify(bucket)})) return {error: '없는 버킷: ' + ${JSON.stringify(bucket)}, buckets: [...sel.options].map(o => o.value)};
      sel.value = ${JSON.stringify(bucket)}; sel.dispatchEvent(new Event('change', {bubbles: true}));
      inp.value = ${JSON.stringify(key)}; inp.dispatchEvent(new Event('input', {bubbles: true}));
      btn.click(); return {clicked: 'search-button'}; })()`;
    const r1 = await s.send('Runtime.evaluate', { expression: act, returnByValue: true });
    const a1 = r1.result?.result?.value || {};
    if (a1.error) { s.close(); out(a1); process.exit(5); }
    await new Promise(r => setTimeout(r, Number(opt('--wait', 2500))));
    const r2 = await s.send('Runtime.evaluate', { returnByValue: true, expression:
      `(() => { const v = (window.editor && window.editor.getValue) ? window.editor.getValue() : (window.ace ? ace.edit('editor').getValue() : ''); return { bucket: ${JSON.stringify(bucket)}, key: ${JSON.stringify(key)}, length: v.length, value: v.slice(0, ${chars}) }; })()` });
    s.close(); out(r2.result?.result?.value ?? r2.result);
  } else if (cmd === 'macaron-get') {
    // 읽기 전용: 이미 조회된 탭(…/couchbase_modifier/?bucket=&key=)의 편집기 전체 내용과 키를 파일로 남긴다.
    const [target, outFile] = args;
    if (!target || !outFile) throw new Error('macaron-get <targetId> <out.json>');
    const s = await session(target);
    const r = await s.send('Runtime.evaluate', { returnByValue: true, expression:
      `(() => ({ url: location.href, host: location.host, key: (document.querySelector('input[name=key]')||{}).value,
                 bucket: (document.querySelector('select[name=bucket]')||{}).value,
                 text: ace.edit(document.querySelector('.ace_editor')).getValue() }))()` });
    s.close();
    const v = r.result?.result?.value;
    if (!v || !v.text) { out({ ok: false, error: '편집기가 비어 있다 — 조회된 탭이 아니다' }); process.exit(5); }
    writeFileSync(outFile, v.text);
    out({ ok: true, url: v.url, bucket: v.bucket, key: v.key, length: v.text.length, saved: outFile });
  } else if (cmd === 'macaron-replace' || cmd === 'macaron-save') {
    // 쓰기 — 2026-11-03 사용자 승인(테스트 계정 상태 만들기). gb- 마카롱은 전부 dev 서버이고 계정도 전부 테스트용이라
    // 서버·계정 제한은 없다(사용자 결정). 아래 조건을 만족할 때만 한다:
    //  · 주소가 dev 마카롱(macaron.gb-*.stove.devspie.com)의 couchbase_modifier
    //  · replace: 편집기의 지정 위치 텍스트가 --expect 와 정확히 같을 때만 그 범위만 --new 로 바꾼다(문서 전체를 다시 쓰지 않는다 — int64 보존)
    //  · save: 누르는 버튼은 `.btn-success` 이면서 글자가 Save 인 것 하나. Delete 는 절대 누르지 않는다
    // 범위 계산·전후 검증은 macaron_edit.py 가 한다.
    const target = args[0];
    const s = await session(target);
    const guard = `(() => { const key = (document.querySelector('input[name=key]')||{}).value;
      if (!/^macaron\\.gb-[a-z0-9-]+\\.stove\\.devspie\\.com$/.test(location.host) || !location.pathname.includes('/couchbase_modifier'))
        return {error: 'dev 마카롱(gb-*) couchbase_modifier 가 아니다: ' + location.href};
      return {key}; })()`;
    const g = (await s.send('Runtime.evaluate', { expression: guard, returnByValue: true })).result?.result?.value || {};
    if (g.error) { s.close(); out({ ok: false, ...g }); process.exit(6); }
    if (cmd === 'macaron-replace') {
      const row = Number(opt('--row')), c1 = Number(opt('--col-start')), c2 = Number(opt('--col-end'));
      const rowEnd = Number(opt('--row-end', String(row)));   // 여러 줄 범위(배열 항목 빼기·넣기)
      const expect = opt('--expect'), next = opt('--new');
      if (![row, rowEnd, c1, c2].every(Number.isInteger) || expect == null || next == null) throw new Error('macaron-replace <targetId> --row R --col-start C1 --col-end C2 --expect TEXT --new TEXT');
      const r = await s.send('Runtime.evaluate', { returnByValue: true, expression: `(() => {
        const e = ace.edit(document.querySelector('.ace_editor'));
        // 마카롱의 ace 빌드에는 ace.require 가 없다. 선택 영역 객체의 생성자로 Range 를 만든다.
        const Range = e.getSelectionRange().constructor;
        const range = new Range(${row}, ${c1}, ${rowEnd}, ${c2}); const cur = e.session.getTextRange(range);
        if (cur !== ${JSON.stringify(expect)}) return {error: '현재 텍스트가 기대와 다르다', current: cur};
        e.session.replace(range, ${JSON.stringify(next)}); return {replaced: cur, with: ${JSON.stringify(next)}}; })()` });
      s.close();
      // 페이지 쪽 예외는 value 가 비어 온다 — 성공으로 보지 않는다
      const v = r.result?.exceptionDetails ? { error: r.result.exceptionDetails.exception?.description || 'exception' }
                                            : (r.result?.result?.value || { error: 'no result' });
      if (!v.error && v.replaced === undefined) v.error = '바꾼 결과가 없다';
      out({ ok: !v.error, key: g.key, ...v }); process.exit(v.error ? 7 : 0);
    } else {
      // 1단계: 본문 Save 를 누르면 「Confirm changes」 창이 변경 줄을 보여 준다. 그 텍스트를 돌려준다(아직 저장 안 됨).
      const modalText = `(() => { const m = [...document.querySelectorAll('.modal')].find(x => getComputedStyle(x).display !== 'none');
        return m ? m.innerText : null; })()`;
      const r = await s.send('Runtime.evaluate', { returnByValue: true, expression: `(() => {
        const b = [...document.querySelectorAll('button.btn-success')].filter(x => x.innerText.trim() === 'Save');
        if (b.length !== 1) return {error: 'Save 버튼이 정확히 하나가 아니다', count: b.length};
        b[0].click(); return {clicked: 'Save'}; })()` });
      const v = r.result?.result?.value || { error: 'no result' };
      let diff = null;
      for (let i = 0; i < 20 && !v.error; i++) {
        await new Promise(r2 => setTimeout(r2, 1500));
        diff = (await s.send('Runtime.evaluate', { returnByValue: true, expression: modalText })).result?.result?.value;
        if (diff && /\n.*[^.\s].*\n/.test(diff.replace(/^Confirm changes/, ''))) break;
      }
      s.close();
      if (!v.error && !diff) v.error = '확인 창이 뜨지 않았다';
      out({ ok: !v.error, key: g.key, ...v, diff });
      process.exit(v.error ? 7 : 0);
    }
  } else if (cmd === 'macaron-confirm') {
    // 2단계: 확인 창의 텍스트가 --diff-file 내용과 정확히 같을 때만 확인 창의 Save(.btn-primary)를 누른다.
    const [target] = args; const diffFile = opt('--diff-file');
    if (!target || !diffFile) throw new Error('macaron-confirm <targetId> --diff-file <검증한 확인 창 텍스트 파일>');
    const expected = (await import('node:fs')).readFileSync(diffFile, 'utf8');
    const s = await session(target);
    const r = await s.send('Runtime.evaluate', { returnByValue: true, expression: `(() => {
      const key = (document.querySelector('input[name=key]')||{}).value;
      if (!/^macaron\\.gb-[a-z0-9-]+\\.stove\\.devspie\\.com$/.test(location.host)) return {error: 'dev 마카롱(gb-*)이 아니다'};
      const m = [...document.querySelectorAll('.modal')].find(x => getComputedStyle(x).display !== 'none');
      if (!m) return {error: '확인 창이 없다'};
      if (m.innerText !== ${JSON.stringify(expected)}) return {error: '확인 창 내용이 검증한 것과 다르다', current: m.innerText.slice(0, 500)};
      const b = [...m.querySelectorAll('button.btn-primary')].filter(x => x.innerText.trim() === 'Save');
      if (b.length !== 1) return {error: '확인 창 Save 버튼이 정확히 하나가 아니다'};
      b[0].click(); return {confirmed: true, key}; })()` });
    await new Promise(r2 => setTimeout(r2, Number(opt('--wait', 4000))));
    const page = (await s.send('Runtime.evaluate', { returnByValue: true, expression: 'document.body.innerText.slice(0, 3000)' })).result?.result?.value || '';
    s.close();
    const v = r.result?.exceptionDetails ? { error: 'exception' } : (r.result?.result?.value || { error: 'no result' });
    out({ ok: !v.error, ...v, notice: page.match(/(success|fail|error|saved|성공|실패)[^\n]{0,100}/i)?.[0] || null });
    process.exit(v.error ? 7 : 0);
  } else {
    console.error('usage: status | launch | activate <targetId> | page-text <url> | open <url> | read <targetId> [--chars N] [--selector CSS] | shot <targetId> <out.png> | close <targetId> | macaron-lookup <targetId> <bucket> <key> | macaron-get <targetId> <out> | macaron-replace … | macaron-save <targetId>');
    process.exit(2);
  }
} catch (e) { console.error(String(e.message || e)); process.exit(1); }
