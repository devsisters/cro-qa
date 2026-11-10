'use strict';
/* global qa, caseModel, marked */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const state = { kit: '', rwFile: null, rwSuite: null, rwIndex: 0, ogFile: null, ogSuite: null, ogSelected: new Set(), bsSelected: new Set(), presets: {}, chatSession: null, chatId: 0, repName: null };

// Electron 은 window.prompt 를 지원하지 않는다 — 화면 안 대화상자로 묻는다
function askText(label, value) {
  return new Promise((resolve) => {
    const dlg = $('#askDialog');
    $('#askLabel').textContent = label;
    $('#askInput').value = value || '';
    dlg.onclose = () => resolve(dlg.returnValue === 'ok' ? $('#askInput').value.trim() : null);
    dlg.showModal();
  });
}

// 목록 칸 — 브라우저 기본 자동완성(datalist)은 맥에서 목록이 길면 스크롤이 안 돼서 직접 그린다.
// 칸의 list 속성이 가리키는 datalist 를 목록 데이터로 그대로 쓴다(목록을 채우는 코드는 datalist 만 고친다)
function attachCombo(input) {
  const listId = input.getAttribute('list');
  if (!listId) return;
  input.removeAttribute('list');
  input.setAttribute('autocomplete', 'off');
  const pop = document.createElement('div');
  pop.className = 'combo-pop';
  pop.hidden = true;
  document.body.appendChild(pop);
  let active = -1;
  let items = [];
  const values = () => [...(document.getElementById(listId)?.options || [])].map((o) => o.value);
  const place = () => {
    const r = input.getBoundingClientRect();
    const below = window.innerHeight - r.bottom;
    pop.style.left = `${r.left}px`;
    pop.style.minWidth = `${Math.max(r.width, 220)}px`;
    pop.style.maxWidth = `${Math.max(r.width, 420)}px`;
    if (below < 200 && r.top > below) { pop.style.top = ''; pop.style.bottom = `${window.innerHeight - r.top + 2}px`; pop.style.maxHeight = `${Math.min(280, r.top - 12)}px`; }
    else { pop.style.bottom = ''; pop.style.top = `${r.bottom + 2}px`; pop.style.maxHeight = `${Math.min(280, below - 12)}px`; }
  };
  const render = (showAll) => {
    const all = values();
    const q = input.value.trim().toLowerCase();
    items = showAll || !q ? all : all.filter((v) => v.toLowerCase().includes(q));
    active = items.indexOf(input.value);
    pop.innerHTML = all.length
      ? `<div class="combo-count">${items.length === all.length ? `${all.length}개` : `${items.length} / ${all.length}개`}</div>`
        + (items.length ? items.map((v, i) => `<div class="combo-item${i === active ? ' active' : ''}" data-i="${i}" title="${esc(v)}">${esc(v)}</div>`).join('') : '<div class="combo-empty">맞는 항목이 없습니다</div>')
      : '<div class="combo-empty">목록이 없습니다 — 옆의 「기기에서…」 버튼으로 받는다</div>';
    pop.hidden = false;
    place();
    const cur = pop.querySelector('.combo-item.active');
    if (cur) cur.scrollIntoView({ block: 'nearest' });
  };
  const choose = (v) => {
    input.value = v;
    pop.hidden = true;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const move = (d) => {
    if (!items.length) return;
    active = (active + d + items.length) % items.length;
    $$('.combo-item', pop).forEach((el, i) => el.classList.toggle('active', i === active));
    pop.querySelector('.combo-item.active')?.scrollIntoView({ block: 'nearest' });
  };
  // 칸을 누르면 지금 값과 상관없이 전체 목록을 보여 주고(지금 값에 맞춰 스크롤), 글자를 치면 거른다
  input.addEventListener('focus', () => render(true));
  input.addEventListener('click', () => { if (pop.hidden) render(true); });
  input.addEventListener('input', (e) => { if (e.isTrusted) render(false); });
  input.addEventListener('blur', () => setTimeout(() => { pop.hidden = true; }, 150));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (pop.hidden) render(true); else move(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter' && !pop.hidden && active >= 0) { e.preventDefault(); choose(items[active]); }
    else if (e.key === 'Escape') pop.hidden = true;
  });
  pop.addEventListener('mousedown', (e) => {
    e.preventDefault(); // 칸의 포커스를 잃지 않게 — 스크롤바를 끌어도 닫히지 않는다
    const el = e.target.closest('.combo-item');
    if (el) choose(items[Number(el.dataset.i)]);
  });
  window.addEventListener('resize', () => { if (!pop.hidden) place(); });
  document.addEventListener('scroll', (e) => { if (!pop.hidden && e.target !== pop && !pop.contains(e.target)) place(); }, true);
}

function toast(el, text, isError) {
  el.textContent = text;
  el.style.color = isError ? 'var(--fail)' : '';
}

// ---------- 탭 ----------
function activateTab(name) {
  $$('#tabs button').forEach((x) => { x.classList.toggle('active', x.dataset.tab === name); x.setAttribute('aria-selected', x.dataset.tab === name); });
  $$('.tab').forEach((t) => t.classList.toggle('active', t.id === `tab-${name}`));
  if (name === 'reports') loadRuns();
  if (name === 'run') refreshRunLabel();
  if (name === 'setup') renderUpdates();
  if (name === 'outgame') loadOutgame();
  if (name === 'basic') loadBasic();
}
$$('#tabs button').forEach((b) => b.addEventListener('click', () => activateTab(b.dataset.tab)));

// ---------- 기기·설정 ----------
const deviceRows = () => $$('#tab-devices tr[data-platform]');
let discovering = null;

function fillDeviceSelect(tr, found, saved) {
  const select = $('.device-id', tr);
  const options = found.map((d) => ({ id: d.id, label: `${d.connected ? '●' : '○'} ${d.name}${d.connected ? '' : ` · ${d.state}`}`, connected: d.connected, sub: [d.model !== d.name ? d.model : '', d.os ? `OS ${d.os}` : ''].filter(Boolean).join(' · ') }));
  if (saved && !options.some((o) => o.id === saved)) options.push({ id: saved, label: `○ 저장된 기기 · 지금 안 보임 (${saved.slice(0, 12)}…)`, connected: false });
  options.unshift({ id: '', label: options.length ? '(사용 안 함)' : '(연결된 기기 없음)', connected: false });
  select.innerHTML = options.map((o) => `<option value="${esc(o.id)}">${esc(o.label)}</option>`).join('');
  // 저장값이 연결돼 있으면 그대로, 아니면 처음 보이는 연결 기기를 고른다
  const savedConnected = options.find((o) => o.id === saved && o.connected);
  const firstConnected = options.find((o) => o.connected);
  select.value = (savedConnected || firstConnected || { id: saved || '' }).id;
  const showSub = () => { $('.device-sub', tr).textContent = (options.find((o) => o.id === select.value) || {}).sub || ''; };
  showSub();
  select.onchange = null;
  select.addEventListener('change', showSub);
  return select.value !== (saved || '');
}

async function saveDeviceSelection() {
  const devices = {};
  for (const tr of deviceRows()) devices[tr.dataset.platform] = { device: $('.device-id', tr).value };
  await qa.devicesWrite(devices);
}

async function discoverDevices() {
  if (discovering) return discovering;
  discovering = (async () => {
    $('#discoverStatus').textContent = '기기 찾는 중…';
    try {
      const [found, saved] = await Promise.all([qa.devicesDiscover(), qa.devicesRead()]);
      let changed = false;
      for (const tr of deviceRows()) changed = fillDeviceSelect(tr, found[tr.dataset.platform] || [], (saved[tr.dataset.platform] || {}).device || '') || changed;
      if (changed) await saveDeviceSelection();
      const n = (found.ios || []).filter((d) => d.connected).length + (found.aos || []).filter((d) => d.connected).length;
      const errs = Object.entries(found.errors || {}).map(([k, v]) => `${k === 'aos' ? 'Android' : 'iOS'} 조회 실패: ${v}`);
      $('#discoverStatus').textContent = [`연결된 기기 ${n}대`, ...errs].join(' · ');
      $('#discoverStatus').style.color = errs.length ? 'var(--error)' : '';
      for (const tr of deviceRows()) if ($('.device-id', tr).value) pingRow(tr);
    } catch (err) {
      $('#discoverStatus').textContent = `기기 찾기 실패: ${err.message}`;
    } finally {
      discovering = null;
    }
  })();
  return discovering;
}

async function loadDevices() {
  const info = await qa.kitInfo();
  state.kit = info.kit;
  $('#kitPath').textContent = info.kit.split('/').pop();
  $('#kitPath').title = info.kit;
  $('#setPython').value = info.settings.python;
  $('#setClaude').value = info.settings.claude;
  $('#setDeveloperDir').value = info.settings.developerDir;
  await discoverDevices();
}
$('#discoverDevices').addEventListener('click', () => discoverDevices());
deviceRows().forEach((tr) => $('.device-id', tr).addEventListener('change', async () => {
  await saveDeviceSelection();
  setDeviceState(tr, '-', 'muted');
  if ($('.device-id', tr).value) pingRow(tr);
}));
// 꽂고 빼는 것을 따라가도록 기기 탭을 보는 동안 15초마다 다시 찾는다
setInterval(() => { if ($('#tab-devices').classList.contains('active') && !document.hidden) discoverDevices(); }, 15000);
$('#saveSettings').addEventListener('click', async () => {
  await qa.settingsWrite({ python: $('#setPython').value, claude: $('#setClaude').value, developerDir: $('#setDeveloperDir').value });
  alertInline($('#saveSettings'), '저장했습니다');
});
function setDeviceState(tr, text, cls, hint, needLaunch) {
  const cell = $('.device-status', tr);
  cell.textContent = text;
  cell.className = `device-status ${cls || 'muted'}`;
  $('.device-hint', tr).textContent = hint || '';
  $('.launch', tr).classList.toggle('primary', Boolean(needLaunch));
}
async function pingRow(tr) {
  const cell = $('.device-status', tr);
  if (!$('.device-id', tr).value) { setDeviceState(tr, '기기 없음', 'muted', '케이블로 연결하면 자동으로 찾는다'); return; }
  if (tr.dataset.pinging) return;
  tr.dataset.pinging = '1';
  setDeviceState(tr, '확인 중…', 'muted');
  try {
    const r = await qa.devicePing(tr.dataset.platform);
    if (r.ok) {
      const scene = await qa.deviceScene(tr.dataset.platform);
      setDeviceState(tr, '● 연결됨', 'v-PASS', `화면 ${(scene.result || {}).top || '?'}`);
    } else {
      const refused = /refused|unavailable/i.test(r.error || '');
      setDeviceState(tr, '연결 모드 필요', 'v-ERROR', refused ? '테스트 시작은 자동으로 연결 모드로 실행한다' : String(r.error || '').slice(0, 120), true);
    }
  } finally {
    delete tr.dataset.pinging;
  }
}
$$('#tab-devices .ping').forEach((b) => b.addEventListener('click', () => pingRow(b.closest('tr'))));
$$('#tab-devices .launch').forEach((b) => b.addEventListener('click', async () => {
  const tr = b.closest('tr');
  const cell = $('.device-status', tr);
  if (!$('.device-id', tr).value) { setDeviceState(tr, '기기를 먼저 고른다', 'muted'); return; }
  b.disabled = true;
  setDeviceState(tr, '게임 띄우는 중…', 'muted');
  try {
    const r = await qa.deviceLaunch(tr.dataset.platform);
    if (!r.ok) throw new Error(r.error || '실행 실패');
    // 게임이 켜지고 브리지가 열릴 때까지 기다린다
    for (let i = 0; i < 15; i += 1) {
      await new Promise((res) => setTimeout(res, 3000));
      cell.textContent = `연결 기다리는 중… ${(i + 1) * 3}초`;
      const p = await qa.devicePing(tr.dataset.platform);
      if (p.ok) { await pingRow(tr); return; }
    }
    setDeviceState(tr, '연결 안 됨', 'v-FAIL', '게임은 떴지만 45초 안에 연결되지 않았다 — DEBUG 빌드인지 「준비」 탭에서 확인한다', true);
  } catch (err) {
    setDeviceState(tr, '실행 실패', 'v-FAIL', String(err.message).slice(0, 160), true);
  } finally {
    b.disabled = false;
  }
}));

// ---------- 준비(처음 세팅) ----------
let setupBusy = false;
async function runSetupCheck() {
  if (setupBusy) return;
  setupBusy = true;
  $('#setupStatus').textContent = '점검 중…(기기 조회 때문에 10~30초)';
  $('#setupRecheck').disabled = true;
  try {
    const rows = await qa.setupCheck();
    renderSetup(rows.filter((r) => r.status !== 'OK'));
    $('#setupSection').hidden = rows.every((r) => r.status === 'OK') && $('#setupLog').hidden;
    const fail = rows.filter((r) => r.status === 'FAIL').length;
    const warn = rows.filter((r) => r.status === 'WARN').length;
    $('#setupStatus').textContent = fail ? `고칠 것 ${fail}개 · 확인할 것 ${warn}개` : (warn ? `필수는 통과 · 확인할 것 ${warn}개` : '모두 준비됨');
    $('#setupBadge').textContent = fail ? String(fail) : '';
    $('#setupBadge').style.color = fail ? 'var(--fail)' : '';
    return { fail, warn };
  } catch (err) {
    $('#setupStatus').textContent = `점검 실패: ${err.message}`;
    return null;
  } finally {
    setupBusy = false;
    $('#setupRecheck').disabled = false;
  }
}

function renderSetup(rows) {
  const order = { FAIL: 0, WARN: 1, OK: 2 };
  rows.sort((a, b) => order[a.status] - order[b.status]);
  $('#setupRows').innerHTML = rows.map((r, i) => `<tr>
    <td class="st-${r.status}">${{ OK: '준비됨', WARN: '확인', FAIL: '필요' }[r.status]}</td>
    <td>${esc(r.title)}</td><td class="muted">${esc(r.need)}</td><td>${esc(r.detail)}</td>
    <td class="fix">${esc(r.fix)}${r.actions.map((a, j) => {
      const btns = [];
      if (a.kind === 'run') btns.push(`<button data-i="${i}" data-j="${j}" data-do="run">${esc(a.label)}</button><button data-i="${i}" data-j="${j}" data-do="terminal">터미널에서</button>`);
      if (a.kind === 'terminal') btns.push(`<button data-i="${i}" data-j="${j}" data-do="terminal">${esc(a.label)} (터미널에서)</button>`);
      if (a.kind === 'open') btns.push(`<button data-i="${i}" data-j="${j}" data-do="open">${esc(a.label)}</button>`);
      if (a.kind === 'apply') btns.push(`<button data-i="${i}" data-j="${j}" data-do="apply">${esc(a.label)}</button>`);
      if (a.command) btns.push(`<br><code>${esc(a.command.split('\n')[0])}</code> <button data-i="${i}" data-j="${j}" data-do="copy">명령 복사</button>`);
      return `<div>${btns.join('')}</div>`;
    }).join('')}</td></tr>`).join('');
  $$('#setupRows button').forEach((b) => b.addEventListener('click', async () => {
    const a = rows[b.dataset.i].actions[b.dataset.j];
    const how = b.dataset.do;
    try {
      if (how === 'copy') { await navigator.clipboard.writeText(a.command); alertInline(b, '복사했다'); return; }
      if (how === 'apply') { await qa.settingsWrite(a.settings); await loadDevices(); await runSetupCheck(); return; }
      if (how === 'run') {
        $('#setupLog').hidden = false;
        $$('#setupRows button').forEach((x) => { x.disabled = x.dataset.do !== 'copy'; });
        await qa.setupAction(a.id);
        return;
      }
      if (how === 'terminal') {
        await qa.setupAction(a.id, 'terminal');
        $('#setupStatus').textContent = '터미널 창에서 진행한 뒤 「다시 점검」을 누른다';
      }
      if (how === 'open') {
        await qa.setupAction(a.id);
        $('#setupStatus').textContent = '설치한 뒤 「다시 점검」을 누른다';
      }
    } catch (err) {
      $('#setupStatus').textContent = `실패: ${err.message}`;
    }
  }));
}
// ---------- 시나리오 저장소(팀 git) ----------
let scenBusy = false;
async function refreshScenario() {
  let st;
  try { st = await qa.scenarioStatus(); } catch (err) { $('#scenMsg').textContent = err.message; return null; }
  if (!st.ready) {
    $('#scenWhere').textContent = st.repo;
    $('#scenState').textContent = '· 아직 안 받음 — 「준비」 탭에서 받는다';
    $('#scenSetup').innerHTML = `<p>팀 저장소 <strong>${esc(st.repo)}</strong> 를 이 컴퓨터에 받아 둔다. 케이스·시나리오 문서(md)·프리셋을 여기서 주고받는다. 실행 결과·기기 ID·앱 설정은 이 컴퓨터에만 남는다.</p>
      <div class="toolbar"><button id="scenConnect" class="primary">받기</button><span class="muted">위치: ${esc(st.defaultDir)}</span>
      <button id="scenConnectPick">다른 위치 / 이미 받은 폴더 고르기</button></div>
      <p class="muted">GitHub 로그인이 안 돼 있으면 받기가 실패한다 — 아래 「처음 세팅」의 GitHub 줄부터 끝낸다.</p>`;
  } else {
    const parts = [st.changed.length ? `바뀐 파일 ${st.changed.length}개` : '바뀐 파일 없음'];
    if (st.ahead) parts.push(`올릴 기록 ${st.ahead}개`);
    if (st.behind) parts.push(`받을 기록 ${st.behind}개`);
    if (!st.upstream) parts.push('팀 저장소에 아직 안 올림');
    $('#scenWhere').textContent = st.repo;
    $('#scenState').textContent = '· ' + parts.join(' · ');
    $('#scenSetup').innerHTML = `<p><strong>${esc(st.repo)}</strong> 를 받아 두었다 · <code>${esc(st.dir)}</code>
      <button id="scenOpen2">폴더 열기</button> <button id="scenConnectPick">위치 바꾸기</button></p>`;
  }
  const bind = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  bind('scenConnect', () => scenDo('받기', () => qa.scenarioConnect(false), { reload: true }));
  bind('scenConnectPick', () => scenDo('받기', () => qa.scenarioConnect(true), { reload: true }));
  bind('scenOpen2', () => qa.scenarioOpen());
  $('#scenPull').disabled = scenBusy || !st.ready;
  $('#scenPush').disabled = scenBusy || !st.ready || !(st.changed.length || st.ahead || !st.upstream);
  $('#scenOpen').disabled = !st.ready;
  state.scenBehind = st.ready ? st.behind : 0;
  paintUpdateDot();
  if (st.ready && state.updBehindShown !== st.behind) renderUpdates();
  return st;
}

// ---------- 업데이트 알림 ----------
// 「최신 받기」 버튼의 빨간 점: 받을 기록이 있을 때. 버튼에 마우스를 올리면 받을 항목 제목이 보인다
function lsGet(k) { try { return localStorage.getItem(k) || ''; } catch (_) { return ''; } }
function lsSet(k, v) { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch (_) { /* 이번 실행 동안만 */ } }
function paintUpdateDot() {
  const behind = state.scenBehind || 0;
  $('#updateDot').hidden = !behind;
  if (!behind) $('#scenPull').title = '팀 저장소의 새 기록을 받는다';
}
function updItems(list, cls) {
  return `<ul class="upd-list ${cls || ''}">${list.map((c) => `<li><span class="when">${esc(c.date)}</span>
    <span><span class="subject">${esc(c.subject)}</span><br>${c.areas.map((a) => `<span class="upd-area${a === '앱' ? ' app' : ''}">${esc(a)}</span>`).join('')}<span class="muted">파일 ${c.files}개</span></span>
    <span class="who">${esc(c.author)}</span></li>`).join('')}</ul>`;
}
async function renderUpdates() {
  let u;
  try { u = await qa.scenarioUpdates(); } catch (_) { $('#updCard').hidden = true; return; }
  state.updBehindShown = u.incoming.length;
  $('#scenPull').title = u.incoming.length
    ? `받을 업데이트 ${u.incoming.length}개\n${u.incoming.slice(0, 8).map((c) => `· ${c.subject}`).join('\n')}${u.incoming.length > 8 ? '\n…' : ''}\n(자세히는 준비 탭)`
    : '팀 저장소의 새 기록을 받는다';
  let last = null;
  try { last = JSON.parse(lsGet('qa.lastPulled') || 'null'); } catch (_) { /* 없음 */ }
  const parts = [];
  if (u.incoming.length) {
    const app = u.incoming.some((c) => c.areas.includes('앱'));
    parts.push(`<div class="upd-group"><h3>받을 업데이트 ${u.incoming.length}개 <button id="updPull" class="primary">최신 받기</button>${app ? '<span class="muted">앱이 바뀐 것이 있어 받은 뒤 다시 시작한다</span>' : ''}</h3>${updItems(u.incoming, 'upd-new')}</div>`);
  } else {
    parts.push('<p class="muted">받을 업데이트가 없습니다 — 최신입니다.</p>');
  }
  if (last && last.commits && last.commits.length) {
    const at = new Date(last.at);
    const when = `${at.getMonth() + 1}/${at.getDate()} ${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
    parts.push(`<div class="upd-group"><h3>마지막으로 받은 업데이트 <span class="muted">${when} · ${last.commits.length}개</span></h3>${updItems(last.commits)}</div>`);
  }
  if (u.recent.length) parts.push(`<details class="sect"><summary>최근 기록 ${u.recent.length}개</summary>${updItems(u.recent)}</details>`);
  $('#updList').innerHTML = parts.join('');
  $('#updCard').hidden = false;
  const pullBtn = document.getElementById('updPull');
  if (pullBtn) pullBtn.onclick = () => $('#scenPull').click();
}

// 받은 것에 앱 코드가 있으면 다시 시작해야 반영된다 — 앱을 켤 때 받은 것이면 바로, 쓰는 중이면 버튼으로
let pendingDeps = false;
async function handleAppUpdate(r, auto) {
  if (!r || !r.appUpdated) return;
  pendingDeps = pendingDeps || !!r.depsUpdated;
  if (auto && !(await qa.runActive()).length) {
    $('#scenMsg').textContent = pendingDeps ? '앱 새 버전 — 필요한 구성요소를 설치하고 다시 시작합니다…' : '앱 새 버전 — 다시 시작합니다…';
    try { await qa.appRestart(pendingDeps); return; } catch (err) { $('#scenMsg').textContent = err.message; }
  }
  $('#appUpdate').hidden = false;
}
$('#appRestart').addEventListener('click', async () => {
  $('#appRestart').disabled = true;
  $('#scenMsg').textContent = pendingDeps ? '구성요소 설치 후 다시 시작합니다…' : '다시 시작합니다…';
  try { await qa.appRestart(pendingDeps); } catch (err) { $('#scenMsg').textContent = err.message; $('#appRestart').disabled = false; }
});

async function scenDo(label, fn, { reload = false, auto = false } = {}) {
  if (scenBusy) return;
  scenBusy = true;
  $('#scenMsg').textContent = `${label} 중…`;
  $('#scenMsg').style.color = '';
  try {
    const r = await fn();
    if (r === null) { $('#scenMsg').textContent = ''; return; }
    // 받은 기록을 남겨 둔다 — 앱이 업데이트돼 다시 시작해도 준비 탭에서 무엇이 들어왔는지 본다
    if (r && Array.isArray(r.pulled) && r.pulled.length) lsSet('qa.lastPulled', JSON.stringify({ at: new Date().toISOString(), commits: r.pulled }));
    $('#scenMsg').textContent = r && r.note ? r.note : `${label} 완료`;
    clearTimeout(state.scenMsgTimer);
    state.scenMsgTimer = setTimeout(() => { if (!scenBusy) $('#scenMsg').textContent = ''; }, 5000);
    if (reload) { await loadPresets(); await loadSuites(); }
    await handleAppUpdate(r, auto);
  } catch (err) {
    $('#scenMsg').textContent = err.message;
    $('#scenMsg').style.color = 'var(--fail)';
  } finally {
    scenBusy = false;
    await refreshScenario();
  }
}

$('#scenPull').addEventListener('click', () => scenDo('최신 받기', () => qa.scenarioPull(), { reload: true }));
$('#scenPush').addEventListener('click', async () => {
  const st = await refreshScenario();
  let message = null;
  if (st && st.changed.length) {
    message = await askText(`무엇을 바꿨나요? 한 줄로 적어 주세요. (바뀐 파일: ${st.changed.slice(0, 5).map((c) => c.file).join(', ')}${st.changed.length > 5 ? ' …' : ''})`, '');
    if (!message) return;
  }
  await scenDo('변경 공유', () => qa.scenarioPush(message), { reload: true });
});
$('#scenOpen').addEventListener('click', () => qa.scenarioOpen());
setInterval(() => { if (!document.hidden && !scenBusy) refreshScenario(); }, 10000);
// 팀 저장소에 새 기록(앱 업데이트 포함)이 올라왔는지 가끔 확인해 「받을 기록 N개」로 보여 준다
setInterval(() => { if (!scenBusy) qa.scenarioFetch().then(() => refreshScenario()).catch(() => {}); }, 5 * 60 * 1000);

qa.on('setup:line', (line) => { const log = $('#setupLog'); log.textContent += line + '\n'; log.scrollTop = log.scrollHeight; });
qa.on('setup:exit', async ({ code }) => {
  $('#setupLog').textContent += `\n— 끝남 (exit ${code}) —\n`;
  await runSetupCheck();
});
$('#setupRecheck').addEventListener('click', () => runSetupCheck());
function alertInline(button, text) {
  const old = button.textContent;
  button.textContent = text;
  setTimeout(() => { button.textContent = old; }, 1200);
}

// ---------- 되감기 케이스 ----------
async function loadSuites() {
  const list = await qa.casesList();
  const fill = (sel, kind, keep) => {
    sel.innerHTML = list.filter((x) => x.kind === kind).map((x) => `<option value="${esc(x.file)}">${esc(x.file)} (${x.count})</option>`).join('');
    if (keep && list.some((x) => x.file === keep)) sel.value = keep;
  };
  fill($('#rwSuite'), 'rewind', state.rwFile);
  showSuiteAuthors(list);
  if ($('#rwSuite').value) await openRewindSuite($('#rwSuite').value);
}
// 묶음을 만든 사람(GitHub 아이디) — git 기록을 읽어 늦게 채운다. 아직 올리지 않은 묶음은 「공유 전」
let suiteAuthorCache = {};
async function showSuiteAuthors(list) {
  const paint = () => {
    for (const sel of [$('#rwSuite')]) {
      for (const o of sel.options) {
        const x = list.find((y) => y.file === o.value);
        if (!x) continue;
        const who = o.value in suiteAuthorCache ? ` · ${suiteAuthorCache[o.value] || '공유 전'}` : '';
        o.textContent = `${x.file} (${x.count})${who}`;
      }
    }
  };
  paint();
  try { suiteAuthorCache = Object.assign({}, suiteAuthorCache, await qa.casesAuthors()); paint(); } catch (_) { /* 이름 없이 둔다 */ }
}
$('#rwSuite').addEventListener('change', () => openRewindSuite($('#rwSuite').value));

async function openRewindSuite(file) {
  state.rwFile = file;
  state.rwSuite = await qa.casesRead(file);
  state.rwSuite.cases = (state.rwSuite.cases || []).map(caseModel.normalizeCase);
  state.rwIndex = 0;
  renderCaseList();
  renderForm();
  setDirty(false);
  refreshRunLabel();
}

function currentCase() {
  return state.rwSuite && state.rwSuite.cases[state.rwIndex];
}

function renderCaseList() {
  const cases = (state.rwSuite && state.rwSuite.cases) || [];
  $('#rwCount').textContent = `케이스 ${cases.length}`;
  $('#rwCases').innerHTML = cases.map((c, i) => {
    const bad = caseModel.validateCase(c).length;
    return `<li data-i="${i}" class="${i === state.rwIndex ? 'active' : ''}"><span class="li-title">${c.title ? esc(c.title) : '<span class="muted">제목 없는 케이스</span>'}</span> <span class="li-id">${esc(c.id)}</span>`
      + `<small>${esc(c.map)} · ${c.plays}판 · 조건 ${(c.triggers || []).length}개${bad ? ` · <span class="v-FAIL">고칠 것 ${bad}</span>` : ''}</small></li>`;
  }).join('') || '<li class="muted">케이스가 없다 — 「+ 추가」</li>';
  $$('#rwCases li[data-i]').forEach((li) => li.addEventListener('click', () => {
    readForm();
    state.rwIndex = Number(li.dataset.i);
    renderCaseList();
    renderForm();
  }));
}

// 카드 이름 — 기기에서 한 번 받아 두고 칸에는 「이름 (id)」로 보여 준다
let cardNames = {};
let cardIdByName = {};
const cardLabel = (id) => (cardNames[id] ? `${cardNames[id]} (${id})` : String(id));
function applyCards(cards) {
  cardNames = {};
  cardIdByName = {};
  for (const cat of ['cookie', 'pet', 'treasure']) {
    for (const { id, name } of cards[cat] || []) {
      cardNames[id] = name;
      if (name && !(name in cardIdByName)) cardIdByName[name] = id;
    }
  }
  const opts = (list) => (list || []).map((x) => `<option value="${esc(cardLabel(x.id))}"></option>`).join('');
  const none = '<option value="없음"></option>';
  $('#cookieList').innerHTML = opts(cards.cookie);
  $('#cookie2List').innerHTML = none + opts(cards.cookie);
  $('#petList').innerHTML = opts(cards.pet);
  $('#treasureList').innerHTML = none + opts(cards.treasure);
}
try {
  const saved = JSON.parse(localStorage.getItem('qa.cardNames') || 'null');
  if (saved) applyCards(saved);
} catch (_) { /* 기억해 둔 목록이 없으면 id 로만 쓴다 */ }

const cardText = (v) => (v === 'random' || v === undefined ? '' : v === 0 ? '없음' : cardLabel(v));
const cardValue = (s) => {
  const t = String(s).trim();
  if (!t || t === 'random' || t === '무작위') return 'random';
  if (t === '없음') return 0;
  const m = /\((\d+)\)\s*$/.exec(t);
  if (m) return Number(m[1]);
  const n = Number(t);
  if (Number.isInteger(n)) return n;
  return t in cardIdByName ? cardIdByName[t] : t;
};

function renderForm() {
  const c = currentCase();
  $('#rwForm').style.visibility = c ? 'visible' : 'hidden';
  if (!c) return;
  for (const el of $$('[data-k]', $('#rwForm'))) el.value = c[el.dataset.k] ?? '';
  for (const key of ['cookie1', 'cookie2', 'pet']) $(`[data-card="${key}"]`).value = cardText(c.cards[key]);
  c.cards.treasures.forEach((v, i) => { $(`[data-card="t${i}"]`).value = cardText(v); });
  const inp = c.input || { mode: 'none' };
  for (const el of $$('[data-in]', $('#rwForm'))) {
    const v = inp[el.dataset.in];
    if (el.type === 'checkbox') el.checked = v !== false;
    else el.value = v ?? (el.dataset.in === 'mode' ? 'random' : '');
  }
  renderTriggers(c.triggers);
  renderCardSummary(c);
  showErrors(caseModel.validateCase(c));
}

function renderCardSummary(c) {
  const fixed = ['cookie1', 'cookie2', 'pet'].filter((k) => c.cards[k] !== 'random').length + c.cards.treasures.filter((t) => t !== 'random').length;
  $('#rwCardSummary').textContent = fixed ? `고정 ${fixed}개` : '모두 무작위';
}

function setDirty(dirty) {
  state.rwDirty = dirty;
  $('#rwStatus').textContent = dirty ? '● 저장하지 않은 변경' : '';
  $('#rwStatus').style.color = dirty ? 'var(--warn)' : '';
  $('#rwCheck').textContent = dirty ? '저장 후 검사' : '케이스 검사';
}

// 게임 되감기 창의 「5초 전·10초 전·15초 전」과 같다 — 그만큼 쌓이지 않았으면 고를 수 있는 가장 앞 지점
const POINTS = [[0, '기본값'], [1, '5초 전'], [2, '10초 전'], [3, '15초 전']];
function renderTriggers(triggers) {
  $('#rwTriggers').innerHTML = triggers.map((t) => `<tr>
    <td><select class="tt">${caseModel.TRIGGERS.map((x) => `<option value="${x}" ${x === t.type ? 'selected' : ''}>${{ interval: 'N초마다 반복', afterRevive: '체력 0 부활 뒤', afterBonusReturn: '보너스타임 복귀 뒤' }[x]}</option>`).join('')}</select>
      <div class="muted tiny">${t.type === 'interval' ? '시작·직전 되감기 기준으로 반복' : '그 일이 일어난 뒤 기다릴 시간'}</div></td>
    <td><input class="td short" type="number" min="0" step="0.5" value="${esc(t.delaySec ?? 0)}" aria-label="${t.type === 'interval' ? '반복 간격(초)' : '대기 시간(초)'}"></td>
    <td><input class="tc short" type="number" min="1" value="${esc(t.count ?? 1)}" aria-label="판당 횟수"></td>
    <td><select class="tp" aria-label="되감을 지점">${POINTS.map(([v, l]) => `<option value="${v}" ${Number(t.point ?? 0) === v ? 'selected' : ''}>${l}</option>`).join('')}</select></td>
    <td><button class="tdel" title="이 조건 삭제" aria-label="이 조건 삭제">✕</button></td></tr>`).join('');
  $$('#rwTriggers .tdel').forEach((b, i) => b.addEventListener('click', () => {
    readForm();
    currentCase().triggers.splice(i, 1);
    renderForm();
    setDirty(true);
  }));
}

function num(v) {
  if (v === '' || v === null || v === undefined) return undefined;
  const n = Number(v);
  return Number.isNaN(n) ? v : n;
}

function readForm() {
  const c = currentCase();
  if (!c) return;
  for (const el of $$('[data-k]', $('#rwForm'))) {
    const k = el.dataset.k;
    c[k] = ['plays', 'timeoutSec', 'seed', 'stopAfterSec'].includes(k) ? num(el.value) : el.value.trim();
  }
  c.cards = {
    cookie1: cardValue($('[data-card="cookie1"]').value),
    cookie2: cardValue($('[data-card="cookie2"]').value),
    pet: cardValue($('[data-card="pet"]').value),
    treasures: [0, 1, 2].map((i) => cardValue($(`[data-card="t${i}"]`).value)),
  };
  c.triggers = $$('#rwTriggers tr').map((tr) => {
    const t = { type: $('.tt', tr).value, delaySec: num($('.td', tr).value) ?? 0, count: num($('.tc', tr).value) };
    const point = Number($('.tp', tr).value);
    if (point) t.point = point;
    return t;
  });
  const input = {};
  for (const el of $$('[data-in]', $('#rwForm'))) {
    if (el.type === 'checkbox') input[el.dataset.in] = el.checked;
    else if (el.dataset.in === 'mode') input.mode = el.value;
    else if (el.dataset.in === 'recording') { if (el.value.trim()) input.recording = el.value.trim(); }
    else if (el.value !== '') input[el.dataset.in] = num(el.value);
  }
  c.input = input.mode === 'none' ? { mode: 'none' } : input;
  renderCardSummary(c);
  showErrors(caseModel.validateCase(c));
}

function showErrors(errs) {
  $('#rwErrors').innerHTML = errs.map((e) => `<li>${esc(e)}</li>`).join('');
}
$('#rwForm').addEventListener('change', (e) => {
  readForm();
  renderCaseList();
  if (e.target.classList.contains('tt')) renderForm(); // 조건 종류에 따라 설명이 바뀐다
  setDirty(true);
});

$('#rwAddCase').addEventListener('click', () => {
  if (!state.rwSuite) return;
  readForm();
  const n = state.rwSuite.cases.length + 1;
  const c = caseModel.defaultCase(`RW-${String(n).padStart(2, '0')}`);
  const preset = state.presets[$('#rwPreset').value];
  state.rwSuite.cases.push(preset ? caseModel.applyPreset(c, preset) : c);
  state.rwIndex = state.rwSuite.cases.length - 1;
  renderCaseList();
  renderForm();
  setDirty(true);
});
$('#rwDelCase').addEventListener('click', async () => {
  if (!state.rwSuite || !currentCase()) return;
  const last = state.rwSuite.cases.length === 1;
  const what = `「${currentCase().title || currentCase().id}」 케이스`;
  if (!confirm(last ? `${what}가 이 묶음의 마지막 케이스입니다. 묶음 파일(${state.rwFile})까지 삭제할까요?` : `${what}를 삭제할까요? 바로 저장합니다.`)) return;
  if (last) {
    try {
      await qa.casesDelete(state.rwFile);
      state.rwFile = null;
      setDirty(false);
      await loadSuites();
      if (!$('#rwSuite').value) { state.rwSuite = null; renderCaseList(); renderForm(); }
      toast($('#rwStatus'), '묶음을 삭제했습니다 — 「변경 공유」로 올리면 팀 저장소에서도 지워집니다');
    } catch (e) { toast($('#rwStatus'), e.message, true); }
    return;
  }
  readForm();
  state.rwSuite.cases.splice(state.rwIndex, 1);
  state.rwIndex = Math.max(0, state.rwIndex - 1);
  renderCaseList();
  renderForm();
  setDirty(true);
  await saveRewind();
});
$('#rwAddTrigger').addEventListener('click', () => {
  readForm();
  currentCase().triggers.push({ type: 'afterRevive', delaySec: 3, count: 1 });
  renderForm();
  setDirty(true);
});
$('#rwNewSuite').addEventListener('click', async () => {
  const name = await askText('새 묶음 파일 이름(영문·숫자·-, 확장자 없이)', 'rewind-new');
  if (!name) return;
  const file = `${name.replace(/\.json$/, '')}.json`;
  const createdBy = await qa.ghLogin().catch(() => '');
  const suite = Object.assign({ suite: name, kind: 'rewind' }, createdBy ? { createdBy } : {}, { cases: [caseModel.defaultCase('RW-01')] });
  try {
    await qa.casesWrite(file, suite);
    state.rwFile = file;
    await loadSuites();
  } catch (e) { toast($('#rwStatus'), e.message, true); }
});
async function saveRewind() {
  readForm();
  const errs = caseModel.validateSuite(state.rwSuite);
  if (errs.length) { showErrors(errs); toast($('#rwStatus'), '고칠 것이 있어 저장하지 않았습니다', true); return false; }
  try {
    await qa.casesWrite(state.rwFile, state.rwSuite);
    setDirty(false);
    toast($('#rwStatus'), '저장했습니다');
    return true;
  } catch (e) { toast($('#rwStatus'), e.message, true); return false; }
}
$('#rwSave').addEventListener('click', saveRewind);
$('#rwCheck').addEventListener('click', async () => {
  if (state.rwDirty && !(await saveRewind())) return;
  const r = await qa.casesCheck(state.rwFile);
  toast($('#rwStatus'), r.ok ? `검사 통과 · 케이스 ${r.cases}개` : `검사 실패: ${(r.errors || []).join(' / ')}`, !r.ok);
});
$('#rwGoRun').addEventListener('click', async () => {
  if (state.rwDirty && !(await saveRewind())) return;
  $('#runKind').value = 'rewind';
  activateTab('run');
});
$('#rwLoadCards').addEventListener('click', async (e) => {
  e.preventDefault();
  const platform = ['ios', 'aos'].find((p) => $(`.runPlat[value="${p}"]`).checked) || 'ios';
  toast($('#rwStatus'), `${platform} 에서 카드 목록 받는 중…`);
  try {
    const cards = await qa.deviceCards(platform);
    const named = ['cookie', 'pet', 'treasure'].some((cat) => (cards[cat] || []).some((x) => x.name));
    if (!named) throw new Error('기기에 깔린 게임이 카드 이름을 주지 않는 옛 빌드다 — 새 빌드를 설치한 뒤 다시 누른다');
    try { localStorage.setItem('qa.cardNames', JSON.stringify(cards)); } catch (_) { /* 이번 실행 동안만 쓴다 */ }
    if (currentCase()) readForm();
    applyCards(cards);
    renderForm();
    toast($('#rwStatus'), `쿠키 ${cards.cookie.length} · 펫 ${cards.pet.length} · 보물 ${cards.treasure.length} — 카드 칸에 이름을 입력하면 목록이 뜬다`);
  } catch (err) { toast($('#rwStatus'), err.message, true); }
});
$('#rwLoadMaps').addEventListener('click', async (e) => {
  e.preventDefault();
  const platform = ['ios', 'aos'].find((p) => $(`.runPlat[value="${p}"]`).checked) || 'ios';
  toast($('#rwStatus'), `${platform} 에서 맵 목록 받는 중…`);
  try {
    const maps = await qa.deviceMaps(platform);
    applyMaps(maps);
    try { localStorage.setItem('qa.maps', JSON.stringify(maps)); } catch (_) { /* 이번 실행 동안만 쓴다 */ }
    toast($('#rwStatus'), `맵 ${maps.length}개 — 맵 칸에 입력하면 목록이 뜬다`);
  } catch (e) { toast($('#rwStatus'), e.message, true); }
});

function applyMaps(maps) {
  $('#mapList').innerHTML = (maps || []).map((m) => `<option value="${esc(m)}">`).join('');
}
try { applyMaps(JSON.parse(localStorage.getItem('qa.maps') || '[]')); } catch (_) { /* 받은 적 없으면 비워 둔다 */ }

// 게임 서버 프리셋 — 기기 탭에서 고르면 실행기가 서버 선택 창에서 그것을 고른다
function applyServerPresets(names) {
  $('#serverPresetList').innerHTML = (names || []).map((n) => `<option value="${esc(n)}">`).join('');
}
async function loadServerPresets(quiet) {
  try {
    const names = await qa.presetsServer();
    applyServerPresets(names);
    try { localStorage.setItem('qa.serverPresets', JSON.stringify(names)); } catch (_) { /* 이번 실행 동안만 */ }
    if (!quiet) toast($('#serverPresetStatus'), `프리셋 ${names.length}개 — 칸을 누르면 목록이 뜬다`);
  } catch (e) { if (!quiet) toast($('#serverPresetStatus'), e.message, true); }
}
async function initServerPreset() {
  try { applyServerPresets(JSON.parse(localStorage.getItem('qa.serverPresets') || '[]')); } catch (_) { /* 없으면 받는다 */ }
  const info = await qa.kitInfo();
  $('#serverPreset').value = info.settings.serverPreset || '';
  if (!$('#serverPresetList').options.length) loadServerPresets(true);
}
$('#loadServerPresets').addEventListener('click', () => loadServerPresets(false));
$('#serverPreset').addEventListener('change', async () => {
  const v = $('#serverPreset').value.trim();
  const known = [...$('#serverPresetList').options].map((o) => o.value);
  if (v && known.length && !known.includes(v)) { toast($('#serverPresetStatus'), `「${v}」은(는) 목록에 없는 프리셋이다`, true); return; }
  await qa.settingsWrite({ serverPreset: v });
  toast($('#serverPresetStatus'), v ? `다음 테스트부터 「${v}」로 들어간다` : '기본(gb-qa-126)으로 들어간다');
});

// 프리셋
async function loadPresets() {
  state.presets = await qa.presetsRead();
  $('#rwPreset').innerHTML = Object.keys(state.presets).map((k) => `<option>${esc(k)}</option>`).join('');
}
$('#rwApplyPreset').addEventListener('click', () => {
  readForm();
  const preset = state.presets[$('#rwPreset').value];
  if (!preset) return;
  state.rwSuite.cases[state.rwIndex] = caseModel.applyPreset(currentCase(), preset);
  renderForm();
  setDirty(true);
});
$('#rwSavePreset').addEventListener('click', async () => {
  readForm();
  const name = await askText('프리셋 이름', $('#rwPreset').value || '내 프리셋');
  if (!name) return;
  state.presets[name] = caseModel.presetFromCase(currentCase());
  await qa.presetsWrite(state.presets);
  await loadPresets();
  $('#rwPreset').value = name;
});

// Claude 로 채우기
$('#rwNlGo').addEventListener('click', async () => {
  readForm();
  const request = $('#rwNl').value.trim();
  if (!request) return;
  toast($('#rwNlStatus'), 'Claude 가 초안을 만드는 중…');
  $('#rwNlGo').disabled = true;
  try {
    const r = await qa.claudeCaseDraft(request, currentCase());
    state.rwSuite.cases[state.rwIndex] = r.draft;
    renderCaseList();
    renderForm();
    setDirty(true);
    toast($('#rwNlStatus'), `채웠다 — 확인 뒤 「저장」${r.errors.length ? ` (고칠 것 ${r.errors.length}개)` : ''}${r.cost ? ` · $${r.cost.toFixed(3)}` : ''}`);
  } catch (e) { toast($('#rwNlStatus'), e.message, true); }
  $('#rwNlGo').disabled = false;
});

// ---------- 아웃게임 — 테스트 시트 TC · 시나리오 ----------
// 탭을 고르면 그 탭의 TC 가 나온다. 시나리오 파일(scenarios/<탭>/<TC 키>.json)이 있으면 ✓, 없으면 「만들기」.
// 시나리오는 Claude 탭에서 담당자와 함께 만들고 고친다(사람의 교정·유의사항은 파일의 notes 에 남는다)
const og = { sheet: null, scenarios: [], tab: '', selKey: '' };
const tabDirName = (tab) => String(tab).replace(/[/\\:]/g, '_');
const tcPath = (tc) => [tc.main, tc.sub1, tc.sub2, tc.sub3].filter(Boolean).map((v) => v.replace(/\s*\n\s*/g, ' ')).join(' › ');
const stClass = (v) => (v === 'N/T' ? 'st-NT' : `st-${String(v).replace(/[^\w]/g, '')}`);
function scenarioOf(tab, tc) {
  const byKey = og.scenarios.find((x) => x.tab === tab && x.key === tc.key);
  if (byKey) return { s: byKey, changed: false };
  // 시트 문구가 바뀌었으면 키가 달라진다 — 같은 탭·같은 번호의 시나리오를 「문구 바뀜」으로 보여 준다
  const byNo = og.scenarios.find((x) => x.tab === tab && String(x.no) === String(tc.no) && !(og.sheetKeys || new Set()).has(`${tab}\u001f${x.key}`));
  return byNo ? { s: byNo, changed: true } : null;
}
async function loadOutgame() {
  const r = await qa.sheetCurrent().catch(() => ({}));
  og.scDir = await qa.scenariosDir().catch(() => '');
  og.sheet = r.cache || null;
  og.scenarios = await qa.scenariosList().catch(() => []);
  og.sheetKeys = new Set();
  for (const t of (og.sheet && og.sheet.tabs) || []) for (const tc of t.tcs) og.sheetKeys.add(`${t.name}\u001f${tc.key}`);
  const cur = r.current;
  if (cur && cur.url && !$('#ogSheetUrl').value) $('#ogSheetUrl').value = cur.url;
  $('#ogSheetOpen').hidden = !(cur && cur.url);
  $('#ogSheetOpen').dataset.url = (cur && cur.url) || '';
  if (og.sheet) {
    const at = og.sheet.loadedAt ? new Date(og.sheet.loadedAt) : null;
    const when = at ? `${at.getMonth() + 1}/${at.getDate()} ${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}` : '';
    const total = og.sheet.tabs.reduce((n, t) => n + t.tcs.length, 0);
    toast($('#ogSheetStatus'), `「${og.sheet.title || '시트'}」 · 탭 ${og.sheet.tabs.length}개 · TC ${total}개 · 시나리오 ${og.scenarios.length}개${when ? ` · ${when} 에 읽음` : ''}${cur && cur.setBy ? ` · 링크 ${cur.setBy}` : ''}`);
  }
  const tabs = (og.sheet && og.sheet.tabs) || [];
  const keep = og.tab || lsGet('qa.ogTab');
  $('#ogTab').innerHTML = tabs.map((t) => {
    const n = t.tcs.filter((tc) => scenarioOf(t.name, tc)).length;
    return `<option value="${esc(t.name)}">${esc(t.name)} (${t.tcs.length}${n ? ` · 시나리오 ${n}` : ''})</option>`;
  }).join('');
  if (tabs.some((t) => t.name === keep)) $('#ogTab').value = keep;
  og.tab = $('#ogTab').value;
  renderOutgame();
}
function renderOutgame() {
  const tab = ((og.sheet && og.sheet.tabs) || []).find((t) => t.name === og.tab);
  const onlyAuto = $('#ogOnlyAuto').checked;
  const q = $('#ogSearch').value.trim().toLowerCase();
  const rows = [];
  let shown = 0;
  let withSc = 0;
  let lastSection = null;
  for (const tc of (tab && tab.tcs) || []) {
    const sc = scenarioOf(tab.name, tc);
    if (sc) withSc += 1;
    if (onlyAuto && !sc) continue;
    if (q && !`${tc.no} ${tcPath(tc)} ${tc.expected} ${tc.section}`.toLowerCase().includes(q)) continue;
    if (tc.section !== lastSection) {
      lastSection = tc.section;
      if (tc.section) rows.push(`<tr class="sec"><td colspan="5">${esc(tc.section)}</td></tr>`);
    }
    shown += 1;
    const pick = sc ? `<input type="checkbox" class="og-pick" data-file="${esc(sc.s.file)}" title="체크하면 「체크한 시나리오 실행으로」에 들어간다"${state.ogSelected.has(sc.s.file) ? ' checked' : ''}>` : '';
    const mark = !sc ? `<button class="og-make" data-key="${esc(tc.key)}">만들기</button>`
      : sc.changed ? `<span class="sc-warn" title="시트 문구가 시나리오를 만들 때와 다르다 — 확인 후 고친다">✓ 문구 바뀜</span>`
        : `<span class="sc-ok" title="단계 ${sc.s.steps}개 · 채점 지점 ${sc.s.scoring}개${sc.s.notes ? ` · 메모 ${sc.s.notes}개` : ''}${sc.s.lastVerdict ? ` · 마지막 ${sc.s.lastVerdict}` : ''}">✓</span>${sc.s.scoring ? ` <span class="muted sc-n">채점 ${sc.s.scoring}</span>` : ''}${sc.s.lastVerdict ? ` <span class="st ${verdictCls(sc.s.lastVerdict)}">${esc(VERDICT_KO[sc.s.lastVerdict] || sc.s.lastVerdict)}</span>` : ''}`;
    rows.push(`<tr class="tc-row${og.selKey === tc.key ? ' sel' : ''}" data-key="${esc(tc.key)}">
      <td class="no">${esc(tc.no)}</td><td class="st">${esc(tc.priority)}</td><td class="path">${esc(tcPath(tc))}</td>
      <td class="exp">${tc.expected ? esc(tc.expected) : '<span class="muted">(기대 결과 없음)</span>'}</td>
      <td class="st sc">${pick}${mark}</td></tr>`);
  }
  $('#ogTable tbody').innerHTML = rows.join('');
  $('#ogEmpty').hidden = shown > 0;
  $('#ogEmpty').textContent = !og.sheet ? '테스트 시트를 아직 읽지 않았습니다 — 위에 시트 링크를 넣고 「불러오기」를 누른다.'
    : !tab ? '탭을 고른다.'
      : onlyAuto && !withSc ? '이 탭에는 아직 시나리오가 없습니다 — 「시나리오 있는 것만」을 끄고 TC 의 「만들기」를 누른다.' : '맞는 TC 가 없습니다.';
  $('#ogStatus').textContent = tab ? `TC ${tab.tcs.length}개 · 시나리오 ${withSc}개${shown !== tab.tcs.length ? ` · ${shown}개 보임` : ''}` : '';
  $$('#ogTable .og-pick').forEach((cb) => {
    cb.addEventListener('click', (e) => e.stopPropagation());
    cb.addEventListener('change', () => {
      if (cb.checked) state.ogSelected.add(cb.dataset.file); else state.ogSelected.delete(cb.dataset.file);
      paintOgPick();
    });
  });
  paintOgPick();
  $$('#ogTable tr.tc-row').forEach((tr) => tr.addEventListener('click', (e) => {
    og.selKey = tr.dataset.key;
    $$('#ogTable tr.tc-row').forEach((x) => x.classList.toggle('sel', x === tr));
    showTcDetail(e.target.closest('.og-make') ? 'make' : '');
  }));
  if (og.selKey) showTcDetail('');
}
async function showTcDetail(action) {
  const tab = ((og.sheet && og.sheet.tabs) || []).find((t) => t.name === og.tab);
  const tc = tab && tab.tcs.find((x) => x.key === og.selKey);
  const box = $('#ogDetail');
  if (!tc) { box.hidden = true; $('.og-split').classList.remove('with-detail'); return; }
  const sc = scenarioOf(tab.name, tc);
  const data = sc ? await qa.scenariosRead(sc.s.file).catch(() => null) : null;
  const notes = (data && data.notes) || [];
  box.innerHTML = `<h3>${esc(tab.name)} · No.${esc(tc.no)}</h3>
    <div class="muted">${esc(tc.section || '')}</div>
    <div class="exp">${esc(tc.expected || '(기대 결과 없음)')}</div>
    <dl><dt>분류</dt><dd>${esc(tcPath(tc))}</dd><dt>중요도</dt><dd>${esc(tc.priority)}</dd>
      ${tc.jira ? `<dt>JIRA</dt><dd>${esc(tc.jira)}</dd>` : ''}${tc.comment ? `<dt>Comment</dt><dd>${esc(tc.comment)}</dd>` : ''}
      <dt>시트 줄</dt><dd>${tc.row}</dd><dt>TC 키</dt><dd><code>${esc(tc.key)}</code></dd></dl>
    <h3>시나리오</h3>
    ${data ? `<p>${sc.changed ? '<span class="sc-warn">시트 문구가 바뀌었다 — 시나리오가 아직 옛 문구 기준이다</span><br>' : ''}단계 ${((data.case || {}).steps || []).length}개 · ${esc(data.createdBy || '')} ${esc((data.updatedAt || '').slice(0, 16).replace('T', ' '))}<br><code>scenarios/${esc(sc.s.file)}</code></p>
      ${scoringHtml(data, sc.s.file)}
      ${notes.length ? `<div class="muted">교정·유의사항</div><ul class="notes">${notes.map((n) => `<li>${esc(typeof n === 'string' ? n : `${n.text || ''}${n.by ? ` — ${n.by}` : ''}`)}</li>`).join('')}</ul>` : ''}
      <button id="ogClaude" class="primary">Claude 와 고치기</button>`
      : '<p class="muted">시나리오 파일이 아직 없다. Claude 가 기기에서 화면을 확인하며 단계를 추측해 만들고 한 번 돌려 본다. 그다음 교정·유의사항을 말하면 시나리오를 고친다.</p><button id="ogClaude" class="primary">Claude 와 만들기</button>'}
    <button id="ogDetailClose">닫기</button>`;
  box.hidden = false;
  $$('#ogDetail img').forEach((img) => img.addEventListener('click', () => window.open(img.src)));
  $$('#ogDetail .sc-confirm').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true;
    try { await qa.scenariosConfirm(sc.s.file, b.dataset.name); showTcDetail(''); } catch (e) { b.disabled = false; alert(e.message); }
  }));
  $('.og-split').classList.add('with-detail');
  $('#ogDetailClose').onclick = () => { og.selKey = ''; box.hidden = true; $('.og-split').classList.remove('with-detail'); $$('#ogTable tr.tc-row.sel').forEach((x) => x.classList.remove('sel')); };
  $('#ogClaude').onclick = () => askClaudeScenario(tab.name, tc, sc && sc.s.file);
  if (action === 'make') askClaudeScenario(tab.name, tc, null);
}
// 채점표 — 시나리오를 만들며 「여기 캡처해」로 정한 지점. 채점은 조건(게임 화면 정보)으로 하고, 캡처는 참고 그림이다.
// 조건은 사람이 「조건 확정」을 눌러야 채점에 쓰인다. 조건으로 못 옮긴 것은 「사람 확인」으로 남아 실행 후 캡처를 사람이 본다
const selText = (sel) => (typeof sel === 'string' ? sel : Object.entries(sel || {}).filter(([k]) => !['min', 'max'].includes(k)).map(([k, v]) => (k === 'text' ? `「${v}」` : v)).join(' · '));
function expectLines(exp) {
  const e = exp || {};
  const out = [];
  if (e.scene) out.push(`화면: ${[].concat(e.scene).join(' 또는 ')}`);
  for (const x of e.tappable || []) out.push(`누를 수 있음: ${selText(x)}`);
  for (const x of e.present || []) out.push(`보임: ${selText(x)}`);
  for (const x of e.absent || []) out.push(`안 보임: ${selText(x)}`);
  for (const x of e.disabled || []) out.push(`비활성: ${selText(x)}`);
  for (const x of e.count || []) out.push(`개수 ${x.min ?? 0}${x.max !== undefined ? `~${x.max}` : ' 이상'}: ${selText(x.any || x)}`);
  for (const x of e.text || []) out.push(`글자: ${selText(x.select)} ${'equals' in x ? `= 「${x.equals}」` : `에 「${x.contains}」 포함`}`);
  return out;
}
const verdictCls = (v) => stClass(v === 'PASS' ? 'Pass' : v === 'FAIL' ? 'Fail' : 'Block');
const VERDICT_KO = { PASS: '통과', FAIL: '실패', HUMAN: '사람 확인', REVIEW: '확인 필요', ERROR: '진행 실패', UNSURE: '확인 필요', NOT_RUN: '미실행', DONE: '진행', FAILED: '진행 실패' };
function scoringHtml(data, file) {
  const points = data.scoring || [];
  const last = data.lastRun || null;
  const base = `${og.scDir}/${file.replace(/\.json$/, '')}`;
  const lastLine = last ? `<p class="muted">마지막 실행 ${esc((last.at || '').slice(5, 16).replace('T', ' '))} · ${esc(last.platform || '')} · <span class="st ${verdictCls(last.verdict)}">${esc(VERDICT_KO[last.verdict] || last.verdict || '-')}</span>${last.reason ? ` · ${esc(last.reason)}` : ''}</p>` : '';
  if (!points.length) return `${lastLine}${(last && (last.actions || []).length) ? `<div class="muted">마지막 실행 액션 ${(last.actions || []).length}개</div>` : ''}<p class="muted">채점표가 아직 없다 — 시나리오를 만들며 「여기 캡처해」라고 하면 그 화면이 채점 지점으로 등록되고, Claude 가 조건 초안을 만든다.</p>`;
  const rows = points.map((p) => {
    const lines = expectLines(p.expect);
    const confirmHtml = p.confirmed ? `<span class="sc-ok">확정</span> <span class="muted">${esc(p.confirmedBy || '')}</span>`
      : `<span class="sc-warn">확정 전</span> <button class="sc-confirm" data-name="${esc(p.name)}">조건 확정</button>`;
    const refs = Object.keys(p.platforms || {}).map((pl) => `<figure><img src="${fileUrl(`${base}/${pl}/${p.name}.png`)}" loading="lazy"><figcaption>${pl === 'aos' ? 'AOS' : 'iOS'} 참고</figcaption></figure>`).join('');
    const vals = (p.values || []).map((v) => `<div>${esc(v.label)} = <strong>${esc(v.value)}</strong></div>`).join('');
    const lc = last && last.checkpoints && last.checkpoints[p.name];
    const res = lc ? `<span class="st ${verdictCls(lc.verdict)}">${esc(VERDICT_KO[lc.verdict] || lc.verdict || '-')}</span>${(lc.failed || []).map((f) => `<div class="sc-fail">✗ ${esc(f)}</div>`).join('')}${lc.shot ? `<figure><img src="${fileUrl(`${state.kit}/${lc.shot}`)}" loading="lazy"><figcaption>${esc(last.platform)} 실행 캡처</figcaption></figure>` : ''}` : '<span class="muted">-</span>';
    return `<tr><td><strong>${esc(p.name)}</strong>${p.label ? `<div class="muted">${esc(p.label)}</div>` : ''}<div>${confirmHtml}</div></td>
      <td>${lines.length ? `<ul class="sc-checks">${lines.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>` : '<span class="muted">조건 없음</span>'}${vals}
        ${p.human ? `<div class="sc-human">사람 확인: ${esc(p.humanNote || '캡처를 보고 판단')}</div>` : ''}${p.compareImage ? '<div class="muted">참고 그림과 화면 비교도 한다</div>' : ''}
        <div class="sc-refs">${refs}</div></td><td>${res}</td></tr>`;
  }).join('');
  const acts = (last && last.actions) || [];
  const flowLine = acts.length ? `<div class="muted">마지막 실행 흐름 (액션 ${acts.length}개)</div><div class="flow small">${acts.map((x, n) => `<figure class="flow-item"><div class="flow-n">${n + 1}</div>${x.shot ? `<img loading="lazy" src="${fileUrl(`${state.kit}/${x.shot}`)}">` : '<div class="noshot">-</div>'}<figcaption>${esc(x.label || '')}<br><span class="chip v-${chipOf(x.verdict)}">${esc(VERDICT_KO[x.verdict] || (x.verdict === 'DONE' ? '진행' : x.verdict === 'FAILED' ? '진행 실패' : x.verdict))}</span></figcaption></figure>`).join('')}</div>` : '';
  return `${lastLine}${flowLine}<div class="muted">채점표 — 조건으로 채점, 그림은 참고</div><table class="grid scoring"><thead><tr><th>지점</th><th>조건</th><th>마지막 결과</th></tr></thead><tbody>${rows}</tbody></table>`;
}
function askClaudeScenario(tabName, tc, file) {
  const target = file || `${tabDirName(tabName)}/${tc.key}.json`;
  const head = `테스트 시트 「${(og.sheet && og.sheet.title) || ''}」의 「${tabName}」 탭 TC No.${tc.no}`;
  const info = [`- 구간: ${tc.section || '-'}`, `- 분류: ${tcPath(tc) || '-'}`, `- 중요도: ${tc.priority || '-'}`, `- 기대 결과: ${tc.expected || '(없음)'}`,
    tc.comment ? `- 시트 Comment: ${tc.comment}` : '', `- TC 키: ${tc.key} · 시트 ${tc.row}번째 줄`, `- 시나리오 파일: scenarios/${target} (형식은 scenarios/README.md)`].filter(Boolean).join('\n');
  const prompt = file
    ? `${head} 시나리오를 이어서 고치자.\n${info}\n\n파일을 먼저 읽고 지금 단계와 notes 를 확인해줘. 내가 말하는 교정·유의사항은 notes 에 남기고 시나리오에 반영한 뒤 한 플랫폼에서 다시 돌려 결과를 알려줘.\n\n`
    : `${head} 시나리오를 만들어줘.\n${info}\n\n기기에서 직접 화면을 확인하면서 단계를 추측해 시나리오 파일을 만들고, 한 플랫폼에서 한 번 돌려 결과와 확신이 없는 부분을 알려줘. 내가 교정하거나 유의사항을 말하면 notes 에 남기고 시나리오를 고친다. 내가 「여기 캡처해」라고 하면 그 지점을 채점표에 등록하고(tools/scenario_capture.py, 그 자리에 checkpoint 단계) 채점 조건 초안을 보여줘 — 조건은 내가 확정한다.`;
  activateTab('chat');
  if (!file || !state.chatSession) $('#chatNew').click();
  $('#chatInput').value = prompt;
  $('#chatInput').focus();
}
// 체크한 시나리오 → 실행 탭(아웃게임). 탭을 바꿔도 체크는 남는다
function paintOgPick() {
  const n = state.ogSelected.size;
  $('#ogToRun').disabled = !n;
  $('#ogToRun').textContent = n ? `체크한 시나리오 ${n}개 실행으로` : '체크한 시나리오 실행으로';
}
$('#ogPickAll').addEventListener('click', () => {
  const boxes = $$('#ogTable .og-pick');
  const all = boxes.length && boxes.every((b) => b.checked);
  boxes.forEach((b) => { if (all) state.ogSelected.delete(b.dataset.file); else state.ogSelected.add(b.dataset.file); });
  renderOutgame();
});
$('#ogToRun').addEventListener('click', () => {
  if (!state.ogSelected.size) return;
  $('#runKind').value = 'outgame';
  activateTab('run');
});
$('#ogTab').addEventListener('change', () => { og.tab = $('#ogTab').value; lsSet('qa.ogTab', og.tab); og.selKey = ''; $('#ogDetail').hidden = true; $('.og-split').classList.remove('with-detail'); renderOutgame(); });
$('#ogOnlyAuto').addEventListener('change', renderOutgame);
$('#ogSearch').addEventListener('input', renderOutgame);
$('#ogSheetOpen').addEventListener('click', () => qa.externalOpen($('#ogSheetOpen').dataset.url));
async function sheetLoad(how) {
  const url = $('#ogSheetUrl').value.trim();
  const status = $('#ogSheetStatus');
  if (how !== 'file' && !url) { toast(status, '시트 링크를 넣는다', true); return; }
  const buttons = [$('#ogSheetLoad'), $('#ogSheetFile')];
  buttons.forEach((b) => { b.disabled = true; });
  try {
    if (how !== 'file') toast(status, '시트를 받는 중… 회사 계정 전용 시트면 브라우저가 xlsx 를 내려받는다(로그인을 물으면 회사 계정으로). 시트가 크면 1분 넘게 걸린다');
    const r = how === 'file' ? await qa.sheetLoadFile(url) : await qa.sheetLoad(url);
    if (r === null) { toast(status, ''); return; }
    await loadOutgame();
    if (r.skipped && r.skipped.length) toast(status, `${$('#ogSheetStatus').textContent} · TC 가 아닌 탭 ${r.skipped.join(', ')} 은 뺐다`);
  } catch (e) {
    toast(status, e.message, true);
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}
$('#ogSheetLoad').addEventListener('click', () => sheetLoad('link'));
$('#ogSheetFile').addEventListener('click', () => sheetLoad('file'));

// ---------- 기본 기능 — 고정 시트(CRO_버젼별 기본기능)의 TC 탭 ----------
// TC 는 저장소 사본(basic/tc.json)에서 바로 보여 주고, 「시트에서 다시 읽기」로 고친다.
// 시나리오는 대분류 하나(모드리스트는 중분류 하나)에 하나 — basic/scenarios/…json. 안이 TC 구간으로 나뉘고 판정은 TC 별로 나온다.
// 버전을 넣고 체크한 시나리오를 돌리면 runs/basic-<버전>-… 에 남고, 함께 시작한 기기가 모두 끝나면 Claude 탭에서 시트의 <버전> 탭에 바로 쓴다
const bs = { data: null, sel: null };   // sel: { kind: 'scen'|'tc', key }
const BS_CLASS = { 화면: 'c-screen', 상태: 'c-state', 시간: 'c-time', 플레이: 'c-play', 수동: 'c-manual' };
const bsTcs = () => Object.fromEntries((((bs.data || {}).tc || {}).tcs || []).map((t) => [t.id, t]));
async function loadBasic() {
  bs.data = await qa.basicRead().catch((e) => { toast($('#bsStatus'), e.message, true); return null; });
  const d = bs.data || {};
  const sheet = d.sheet || {};
  $('#bsTitle').textContent = sheet.title || '기본 기능 시트';
  $('#bsOpen').hidden = !sheet.url;
  if (!$('#bsVersion').value) $('#bsVersion').value = lsGet('qa.bsVersion');
  const tcs = (d.tc && d.tc.tcs) || [];
  const groups = d.groups || [];
  const at = d.tc && d.tc.readAt ? d.tc.readAt.slice(0, 16).replace('T', ' ') : '';
  const autoTc = groups.reduce((n, g) => n + g.auto.length, 0);
  $('#bsInfo').textContent = tcs.length
    ? `TC ${tcs.length}개 · 시나리오 ${groups.length}개(만든 것 ${groups.filter((g) => g.exists).length}) · 자동화된 TC ${autoTc}개${at ? ` · 시트에서 읽은 시각 ${at}` : ''}`
    : '아직 TC 사본이 없다 — 「시트에서 다시 읽기」를 누른다';
  for (const f of [...state.bsSelected]) if (!groups.some((g) => g.file === f && g.auto.length)) state.bsSelected.delete(f);
  renderBasic();
}
function renderBasic() {
  const d = bs.data || {};
  const T = bsTcs();
  const cls = $('#bsClass').value;
  const onlyAuto = $('#bsOnlyAuto').checked;
  const q = $('#bsSearch').value.trim().toLowerCase();
  const rows = [];
  let shownTc = 0;
  let shownScen = 0;
  for (const g of d.groups || []) {
    if (onlyAuto && !g.auto.length) continue;
    const ids = g.tcs.filter((id) => {
      const t = T[id] || {};
      if (cls && t.class !== cls) return false;
      return !q || `${g.name} ${t.id} ${t.sub} ${t.check} ${t.judge}`.toLowerCase().includes(q);
    });
    if (!ids.length) continue;
    shownScen += 1;
    shownTc += ids.length;
    const pick = g.auto.length ? `<input type="checkbox" class="bs-pick" data-file="${esc(g.file)}" title="체크하면 「체크한 시나리오 실행으로」에 들어간다"${state.bsSelected.has(g.file) ? ' checked' : ''}>` : '';
    const btn = g.exists ? `<button class="bs-make" data-file="${esc(g.file)}">고치기</button>` : `<button class="bs-make" data-file="${esc(g.file)}">만들기</button>`;
    const sel = bs.sel && bs.sel.kind === 'scen' && bs.sel.key === g.file;
    rows.push(`<tr class="scen-row${sel ? ' sel' : ''}" data-file="${esc(g.file)}"><td class="pick">${pick}</td><td colspan="4"><strong>${esc(g.name)}</strong> <span class="muted">TC ${g.tcs.length}개 · 자동화 ${g.auto.length}개${g.exists ? '' : ' · 시나리오 없음'}</span></td><td class="st sc">${btn}</td></tr>`);
    for (const id of ids) {
      const t = T[id] || {};
      const n = g.steps[id];
      const mark = n ? `<span class="sc-ok" title="단계 ${n}개">✓</span>` : g.reasons[id] ? `<span class="muted" title="${esc(g.reasons[id])}">제외</span>` : '<span class="muted">-</span>';
      const tsel = bs.sel && bs.sel.kind === 'tc' && bs.sel.key === id;
      rows.push(`<tr class="tc-row${tsel ? ' sel' : ''}" data-id="${esc(id)}" data-file="${esc(g.file)}"><td></td><td class="no">${esc(id.replace('TC-', ''))}</td><td class="st">${esc(t.priority)}</td>
        <td class="exp">${g.sub || !t.sub ? '' : `<span class="muted">${esc(t.sub)} · </span>`}${esc(t.check)}</td><td><span class="cls ${BS_CLASS[t.class] || ''}">${esc(t.class)}</span></td><td class="st sc">${mark}</td></tr>`);
    }
  }
  $('#bsTable tbody').innerHTML = rows.join('');
  $('#bsEmpty').hidden = shownTc > 0;
  $('#bsEmpty').textContent = !(d.tc && d.tc.tcs || []).length ? 'TC 사본이 없습니다 — 위의 「시트에서 다시 읽기」를 누른다.' : '맞는 TC 가 없습니다.';
  $('#bsCount').textContent = `시나리오 ${shownScen}개 · TC ${shownTc}개 보임`;
  $$('#bsTable .bs-pick').forEach((cb) => {
    cb.addEventListener('click', (e) => e.stopPropagation());
    cb.addEventListener('change', () => { if (cb.checked) state.bsSelected.add(cb.dataset.file); else state.bsSelected.delete(cb.dataset.file); paintBsPick(); });
  });
  $$('#bsTable tr.scen-row').forEach((tr) => tr.addEventListener('click', (e) => {
    bs.sel = { kind: 'scen', key: tr.dataset.file };
    paintBsSel();
    showBasicDetail(e.target.closest('.bs-make') ? 'claude' : '');
  }));
  $$('#bsTable tr.tc-row').forEach((tr) => tr.addEventListener('click', () => { bs.sel = { kind: 'tc', key: tr.dataset.id, file: tr.dataset.file }; paintBsSel(); showBasicDetail(''); }));
  paintBsPick();
  if (bs.sel) showBasicDetail('');
}
function paintBsSel() {
  $$('#bsTable tr.scen-row').forEach((x) => x.classList.toggle('sel', !!bs.sel && bs.sel.kind === 'scen' && x.dataset.file === bs.sel.key));
  $$('#bsTable tr.tc-row').forEach((x) => x.classList.toggle('sel', !!bs.sel && bs.sel.kind === 'tc' && x.dataset.id === bs.sel.key));
}
function paintBsPick() {
  const n = state.bsSelected.size;
  $('#bsToRun').disabled = !n;
  $('#bsToRun').textContent = n ? `체크한 시나리오 ${n}개 실행으로` : '체크한 시나리오 실행으로';
}
const bsGroup = (file) => ((bs.data || {}).groups || []).find((g) => g.file === file);
const bsLines = (s) => String(s || '').split('\n').filter(Boolean);
function showBasicDetail(action) {
  const box = $('#bsDetail');
  const split = $('#tab-basic .og-split');
  const close = () => { bs.sel = null; box.hidden = true; split.classList.remove('with-detail'); paintBsSel(); };
  const T = bsTcs();
  const g = bs.sel && bsGroup(bs.sel.kind === 'scen' ? bs.sel.key : bs.sel.file);
  if (!g) { close(); return; }
  if (bs.sel.kind === 'tc') {
    const t = T[bs.sel.key];
    if (!t) { close(); return; }
    const n = g.steps[t.id];
    box.innerHTML = `<h3>${esc(t.id)} · ${esc(t.area)} › ${esc(t.sub)}</h3>
      <div class="exp">${esc(t.check)}</div>
      <dl><dt>중요도</dt><dd>${esc(t.priority)}</dd><dt>자동화 구분</dt><dd><span class="cls ${BS_CLASS[t.class] || ''}">${esc(t.class)}</span></dd>
        ${t.needs ? `<dt>사전 조건</dt><dd>${esc(t.needs)}</dd>` : ''}${t.note ? `<dt>비고</dt><dd>${esc(t.note)}</dd>` : ''}
        <dt>시나리오</dt><dd>${esc(g.name)} — ${n ? `이 TC 구간 단계 ${n}개` : g.reasons[t.id] ? `제외: ${esc(g.reasons[t.id])}` : '이 TC 구간은 아직 비어 있다'}</dd></dl>
      <h3>판정 항목</h3><ul class="sc-checks">${bsLines(t.judge).map((l) => `<li>${esc(l)}</li>`).join('') || '<li class="muted">없음</li>'}</ul>
      <button id="bsScen">시나리오 보기</button> <button id="bsDetailClose">닫기</button>`;
    box.hidden = false;
    split.classList.add('with-detail');
    $('#bsScen').onclick = () => { bs.sel = { kind: 'scen', key: g.file }; paintBsSel(); showBasicDetail(''); };
    $('#bsDetailClose').onclick = close;
    return;
  }
  box.innerHTML = `<h3>시나리오 ${esc(g.name)}</h3>
    <p class="muted">${g.exists ? `<code>basic/scenarios/${esc(g.file)}</code> · 진입 단계 ${g.entry}개${g.setup ? ` · 준비(마카롱 등) ${g.setup}개` : ''}${g.notes ? ` · 메모 ${g.notes}개` : ''}` : '아직 시나리오 파일이 없다'}</p>
    <table class="grid scoring"><thead><tr><th>TC</th><th>판정 항목</th><th>구간</th></tr></thead><tbody>${g.tcs.map((id) => {
      const t = T[id] || {};
      const n = g.steps[id];
      return `<tr><td><strong>${esc(id)}</strong><div><span class="cls ${BS_CLASS[t.class] || ''}">${esc(t.class)}</span></div></td><td><ul class="sc-checks">${bsLines(t.judge).map((l) => `<li>${esc(l)}</li>`).join('')}</ul></td>
        <td>${n ? `<span class="sc-ok">✓</span> 단계 ${n}` : g.reasons[id] ? `<span class="muted">제외 — ${esc(g.reasons[id])}</span>` : '<span class="muted">비어 있음</span>'}</td></tr>`;
    }).join('')}</tbody></table>
    <button id="bsClaude" class="primary">${g.exists ? 'Claude 와 고치기' : 'Claude 와 만들기'}</button> <button id="bsDetailClose">닫기</button>`;
  box.hidden = false;
  split.classList.add('with-detail');
  $('#bsDetailClose').onclick = close;
  $('#bsClaude').onclick = () => askClaudeBasic(g);
  if (action === 'claude') askClaudeBasic(g);
}
function askClaudeBasic(g) {
  const T = bsTcs();
  const list = g.tcs.map((id) => {
    const t = T[id] || {};
    return `- ${id} [${t.class}] ${t.check}\n${bsLines(t.judge).map((l) => `  · ${l}`).join('\n')}${t.needs ? `\n  사전 조건: ${t.needs}` : ''}${t.note ? `\n  비고: ${t.note}` : ''}`;
  }).join('\n');
  const file = `basic/scenarios/${g.file}`;
  const make = g.sub ? `python3 tools/basic_scenario.py new "${g.area}" "${g.sub}"` : `python3 tools/basic_scenario.py new "${g.area}"`;
  const prompt = g.exists
    ? `기본 기능 시나리오 「${g.name}」를 이어서 고치자. 파일: ${file} (형식은 basic/README.md 「시나리오 파일」)\n\nTC:\n${list}\n\n파일을 먼저 읽고 지금 구간과 notes 를 확인해줘. 내가 말하는 교정·유의사항은 notes 에 남기고 반영한 뒤 한 플랫폼에서 다시 돌려(python3 tools/basic_run.py ${JSON.stringify(`../${file}`)} --platform aos --version 시험) TC 별 결과를 알려줘.\n\n`
    : `기본 기능 시나리오 「${g.name}」를 만들어줘. 파일: ${file} (없으면 ${make} 로 빈 구간부터, 형식은 basic/README.md 「시나리오 파일」)\n\nTC:\n${list}\n\n기기에서 직접 화면을 확인하면서 이 화면까지 들어가는 entry 와 TC 구간별 단계를 만든다. 판정 항목 한 줄이 채점 지점(checkpoint) 하나다. 화면 정보로 판정할 수 없는 줄은 사람 확인으로 남기고, 자동화할 수 없는 TC(수동·다른 계정 필요 등)는 구간의 reason 에 이유를 적는다. 다 만들면 한 플랫폼에서 돌려(python3 tools/basic_run.py ${JSON.stringify(`../${file}`)} --platform aos --version 시험) TC 별 결과와 확신이 없는 부분을 알려줘.`;
  activateTab('chat');
  if (!g.exists || !state.chatSession) $('#chatNew').click();
  $('#chatInput').value = prompt;
  $('#chatInput').focus();
}
$('#bsClass').addEventListener('change', renderBasic);
$('#bsOnlyAuto').addEventListener('change', renderBasic);
$('#bsSearch').addEventListener('input', renderBasic);
$('#bsVersion').addEventListener('change', () => { lsSet('qa.bsVersion', $('#bsVersion').value.trim()); });
$('#bsOpen').addEventListener('click', () => { const u = ((bs.data || {}).sheet || {}).url; if (u) qa.externalOpen(u); });
$('#bsPickAll').addEventListener('click', () => {
  const boxes = $$('#bsTable .bs-pick');
  const all = boxes.length && boxes.every((b) => b.checked);
  boxes.forEach((b) => { if (all) state.bsSelected.delete(b.dataset.file); else state.bsSelected.add(b.dataset.file); });
  renderBasic();
});
$('#bsToRun').addEventListener('click', () => {
  const ver = $('#bsVersion').value.trim();
  if (!ver) { toast($('#bsStatus'), '버전을 넣는다(예: 14.50) — 결과를 시트의 그 이름 탭에 쓴다', true); $('#bsVersion').focus(); return; }
  lsSet('qa.bsVersion', ver);
  $('#runKind').value = 'basic';
  activateTab('run');
});
$('#bsRefresh').addEventListener('click', async () => {
  const b = $('#bsRefresh');
  b.disabled = true;
  toast($('#bsStatus'), '시트를 받는 중… 브라우저가 xlsx 를 내려받는다(로그인을 물으면 회사 계정으로). 앱이 읽고 나면 그 파일을 지운다');
  try {
    const r = await qa.basicRefresh();
    await loadBasic();
    toast($('#bsStatus'), r.changed ? `TC ${r.tcs}개를 읽었다 — 시트 문구가 바뀌어 저장소 사본을 고쳤다. 준비 탭 「변경 공유」로 올리면 팀도 같은 TC 를 본다` : `TC ${r.tcs}개를 읽었다 — 바뀐 것이 없다`);
  } catch (e) { toast($('#bsStatus'), e.message, true); }
  b.disabled = false;
});

// ---------- 실행 ----------
function refreshRunLabel() {
  const kind = $('#runKind').value;
  $('#runRelaunchWrap').style.display = kind !== 'rewind' ? '' : 'none';
  $('#runActionCapWrap').style.display = kind !== 'rewind' ? '' : 'none';
  const ver = $('#bsVersion').value.trim() || lsGet('qa.bsVersion');
  $('#runSuiteLabel').textContent = kind === 'rewind'
    ? `${(state.rwFile || '-').replace(/\.json$/, '')} · 케이스 ${((state.rwSuite || {}).cases || []).length}개`
    : kind === 'basic' ? `기본 기능 ${ver || '(버전 없음)'} · 시나리오 ${state.bsSelected.size}개${state.bsSelected.size ? ` · ${[...state.bsSelected].slice(0, 4).map((f) => f.replace(/\.json$/, '').replace('/', ' › ')).join(', ')}${state.bsSelected.size > 4 ? ' …' : ''}` : ' — 기본 기능 탭에서 체크한다'}`
    : `아웃게임 시나리오 ${state.ogSelected.size}개${state.ogSelected.size ? ` · ${[...state.ogSelected].slice(0, 3).map((f) => f.split('/')[0]).filter((v, i, a) => a.indexOf(v) === i).join(', ')}` : ' — 아웃게임 탭에서 체크한다'}`;
  syncRunPanels();
}
function syncRunPanels() {
  const on = $$('.runPlat').filter((x) => x.checked).map((x) => x.value);
  const busy = new Set(state.runBusy || []);
  let shown = 0;
  for (const panel of $$('.run-panel')) {
    const visible = on.includes(panel.dataset.platform) || busy.has(panel.dataset.platform) || panel.dataset.used === '1';
    panel.hidden = !visible;
    if (visible) shown += 1;
  }
  $('#runPanels').classList.toggle('one', shown <= 1);
}
$$('.runPlat').forEach((x) => x.addEventListener('change', syncRunPanels));

// 판 진행 — 실행기 출력 「[aos] PASS   RW-01#2 …」 를 세고, 마지막 진행 줄을 보여 준다
const runTimers = {};
function runPanelStart(platform) {
  const panel = $(`.run-panel[data-platform="${platform}"]`);
  panel.dataset.used = '1';
  panel.dataset.counts = JSON.stringify({ PASS: 0, FAIL: 0, ERROR: 0, UNSURE: 0 });
  $('.rp-report', panel).hidden = true;
  $(`#counts-${platform}`).innerHTML = '';
  $(`#now-${platform}`).textContent = '시작하는 중…';
  setRunState(platform, '실행 중', 'running');
  const started = Date.now();
  clearInterval(runTimers[platform]);
  const tick = () => {
    const sec = Math.floor((Date.now() - started) / 1000);
    $(`#elapsed-${platform}`).textContent = `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
  };
  tick();
  runTimers[platform] = setInterval(tick, 1000);
  state.runBusy = [...new Set([...(state.runBusy || []), platform])];
  syncRunPanels();
}
function setRunState(platform, text, kind) {
  const el = $(`#state-${platform}`);
  el.textContent = text;
  el.className = `badge ${kind || ''}`;
}
function runPanelLine(platform, line) {
  const m = /\]\s+(PASS|FAIL|ERROR|UNSURE|REVIEW)\s+(\S+)/.exec(line);
  const panel = $(`.run-panel[data-platform="${platform}"]`);
  if (m) {
    const counts = JSON.parse(panel.dataset.counts || '{}');
    const v = m[1] === 'REVIEW' ? 'UNSURE' : m[1];
    counts[v] = (counts[v] || 0) + 1;
    panel.dataset.counts = JSON.stringify(counts);
    const label = { PASS: '통과', FAIL: '실패', ERROR: '진행 실패', UNSURE: '확인 필요' };
    $(`#counts-${platform}`).innerHTML = Object.entries(counts).filter(([, n]) => n).map(([k, n]) => `<span class="chip v-${k}">${label[k]} ${n}</span>`).join('');
    $(`#now-${platform}`).textContent = `${m[2].replace('#', ' · ')}판 ${label[v]}`;
  } else if (line.trim() && !line.startsWith('{')) {
    $(`#now-${platform}`).textContent = line.replace(/^\[\w+\]\s*/, '').slice(0, 140);
  }
}
$('#runKind').addEventListener('change', refreshRunLabel);

function logLine(platform, text, cls) {
  const pre = $(`#log-${platform}`);
  const span = document.createElement('span');
  const m = /\b(PASS|FAIL|ERROR|UNSURE|REVIEW)\b/.exec(text);
  span.className = cls || (m ? `v-${m[1] === 'REVIEW' ? 'UNSURE' : m[1]}` : '');
  span.textContent = `${text}\n`;
  pre.appendChild(span);
  pre.scrollTop = pre.scrollHeight;
}

$('#runStart').addEventListener('click', async () => {
  const kind = $('#runKind').value;
  const platforms = $$('.runPlat').filter((x) => x.checked).map((x) => x.value);
  if (!platforms.length) return;
  if (kind === 'rewind') {
    readForm();
    const errs = caseModel.validateSuite(state.rwSuite);
    if (errs.length) { alert(`되감기 케이스에 고칠 것이 있다:\n${errs.join('\n')}`); return; }
    await qa.casesWrite(state.rwFile, state.rwSuite);
  } else if (kind === 'basic') {
    if (!state.bsSelected.size) { alert('기본 기능 탭에서 실행할 시나리오를 하나 이상 체크한다'); return; }
    if (!($('#bsVersion').value.trim() || lsGet('qa.bsVersion'))) { alert('기본 기능 탭에 버전을 넣는다(예: 14.50)'); return; }
  } else if (!state.ogSelected.size) { alert('아웃게임 탭에서 실행할 시나리오를 하나 이상 체크한다'); return; }
  // 기본 기능은 함께 시작한 기기가 모두 끝나면 결과를 시트의 <버전> 탭에 바로 쓰기 시작한다(run:exit)
  state.bsBatch = kind === 'basic' ? { version: $('#bsVersion').value.trim() || lsGet('qa.bsVersion'), waiting: new Set(platforms), runs: [] } : null;
  for (const platform of platforms) {
    $(`#log-${platform}`).textContent = '';
    runPanelStart(platform);
    try {
      await qa.runStart({
        kind, platform,
        suiteFile: kind === 'rewind' ? state.rwFile : null,
        scenarioFiles: kind === 'outgame' ? [...state.ogSelected] : kind === 'basic' ? [...state.bsSelected] : [],
        version: kind === 'basic' ? ($('#bsVersion').value.trim() || lsGet('qa.bsVersion')) : '',
        relaunch: $('#runRelaunch').checked,
        actionCapture: $('#runActionCap').checked,
      });
      logLine(platform, `▶ ${kind === 'rewind' ? `되감기 ${state.rwFile}` : kind === 'basic' ? `기본 기능 시나리오 ${state.bsSelected.size}개` : `시나리오 ${state.ogSelected.size}개`} 시작`, 'muted');
    } catch (e) {
      logLine(platform, e.message, 'v-ERROR');
      clearInterval(runTimers[platform]);
      setRunState(platform, '시작 실패', 'bad');
      $(`#now-${platform}`).textContent = e.message;
      if (state.bsBatch) state.bsBatch.waiting.delete(platform);
    }
  }
});
// 맵 녹화 — 고른 기기에서 이 케이스의 맵을 사람이 한 판 플레이하고, 끝나면 위치별 입력이 recordings/<맵>.json 으로 저장된다
$('#rwRecord').addEventListener('click', async () => {
  readForm();
  const c = currentCase();
  if (!c) return;
  const platforms = $$('.runPlat').filter((x) => x.checked).map((x) => x.value);
  if (!platforms.length) { alert('실행 탭에서 녹화할 기기를 하나 고른다'); return; }
  const platform = platforms[0];
  activateTab('run');
  $(`#log-${platform}`).textContent = '';
  runPanelStart(platform);
  try {
    await qa.runStart({ kind: 'rewind', platform, suiteFile: state.rwFile, recordCase: c });
    logLine(platform, `▶ 맵 녹화 ${c.map} — 기기에서 직접 한 판 플레이하세요. 판이 끝나면 녹화가 저장됩니다`, 'muted');
  } catch (e) {
    logLine(platform, e.message, 'v-ERROR');
    setRunState(platform, '시작 실패', 'bad');
  }
});
$('#runStop').addEventListener('click', async () => {
  for (const platform of ['ios', 'aos']) if (await qa.runStop(platform)) logLine(platform, '■ 중지 요청', 'muted');
});
qa.on('run:line', ({ platform, line }) => { logLine(platform, line); runPanelLine(platform, line); });
qa.on('run:exit', async ({ platform, code, runName }) => {
  clearInterval(runTimers[platform]);
  state.runBusy = (state.runBusy || []).filter((p) => p !== platform);
  // 종료 코드는 실행기가 끝까지 돌았는지일 뿐이고 판정 통과가 아니다 — 판정은 위 집계로 본다
  setRunState(platform, runName ? '실행 종료' : '중단됨', runName ? 'done' : 'bad');
  $(`#now-${platform}`).textContent = runName ? '끝났습니다 — 결과는 리포트에서 확인합니다' : `실행기가 결과 없이 끝났습니다 (상세 로그 확인)`;
  const btn = $(`.run-panel[data-platform="${platform}"] .rp-report`);
  btn.hidden = !runName;
  btn.onclick = () => { activateTab('reports'); openRun(runName); };
  logLine(platform, `■ 끝남 exit ${code}${runName ? ` → 리포트 ${runName}` : ''}`, code === 0 ? 'v-PASS' : 'v-ERROR');
  const batch = state.bsBatch;
  if (!batch || !batch.waiting.has(platform)) return;
  batch.waiting.delete(platform);
  if (runName && runName.startsWith('basic-')) batch.runs.push(runName);
  if (batch.waiting.size) {
    $(`#now-${platform}`).textContent = `끝났습니다 — 다른 기기가 끝나면 시트 「${batch.version}」 탭에 함께 씁니다`;
    return;
  }
  state.bsBatch = null;
  if (!batch.runs.length) return;
  const sent = writeBasicSheet(batch.version, batch.runs);
  for (const p of ['ios', 'aos']) {
    if (!batch.runs.some((n) => n.includes(`-${p}-`))) continue;
    $(`#now-${p}`).textContent = sent
      ? `끝났습니다 — 시트 「${batch.version}」 탭에 결과를 쓰는 중입니다(Claude 탭)`
      : '끝났습니다 — Claude 대화가 진행 중이라 시트 쓰기를 시작하지 못했습니다. 리포트의 「시트에 결과 쓰기」를 누릅니다';
  }
});

// 기본 기능 결과 → 시트의 <버전> 탭. 쓰기는 Claude 가 Google Sheets·Drive 연결로 한다(앱은 시트 계정을 다루지 않는다).
// 새 대화를 열고 바로 보낸다. 다른 대화가 진행 중이면 끊지 않고 false 를 돌려준다
function writeBasicSheet(version, runNames) {
  if (!$('#chatStop').hidden) return false;
  const prompt = `기본 기능 결과를 시트에 써줘. 버전 「${version}」 탭이다.\n실행 폴더: ${runNames.map((n) => `runs/${n}`).join(', ')}\n\nbasic/README.md 「결과 쓰기」 절차대로 한다 — 탭이 없으면 만들고, A열로 행을 찾아 담당자 칸과 실행한 플랫폼의 판정·근거·결과 칸만 쓴다(결과 칸의 캡처는 Drive 의 버전 폴더를 먼저 찾아 거기에 올려 링크로). 사람이 적은 결과는 덮어쓰지 않는다. 다 쓰면 몇 개를 썼는지와 건너뛴 것을 알려줘.`;
  activateTab('chat');
  $('#chatNew').click();
  $('#chatInput').value = prompt;
  $('#chatSend').click();
  return true;
}

// ---------- 리포트 ----------
function runTitle(name) {
  // 실행 폴더 이름: <묶음>-<ios|aos>-<YYYYMMDD-HHMMSS>
  const m = /^(.*)-(ios|aos|mac)-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})\d{2}$/.exec(name);
  if (!m) return { title: name, sub: '' };
  const basic = /^basic-(.+)$/.exec(m[1]);
  return { title: m[1] === 'scenario' ? '아웃게임 시나리오' : basic ? `기본 기능 ${basic[1]}` : m[1], sub: `${{ ios: 'iOS', aos: 'Android', mac: 'macOS' }[m[2]]} · ${m[4]}/${m[5]} ${m[6]}:${m[7]}` };
}
const chipOf = (v) => ({ HUMAN: 'UNSURE', DONE: 'PASS', FAILED: 'ERROR' }[v] || v);
// 액션 캡처와 채점 지점을 실행 순서대로
function flowOf(c) {
  const items = (c.actions || []).map((x) => Object.assign({ kind: 'action' }, x));
  for (const cp of c.checkpoints || []) items.push({ kind: 'checkpoint', step: cp.step, label: cp.name, verdict: cp.verdict, shot: cp.shot });
  return items.sort((a, b) => (a.step ?? 1e6) - (b.step ?? 1e6));
}
// 아웃게임 시나리오 실행 리포트 — 위에 TC 별 상태 표, 아래에 지점별 캡처가 든 상세. 표의 줄을 누르면 그 TC 상세로 간다
function renderScenarioRun(run) {
  const cases = (run.results && run.results.cases) || [];
  const ko = VERDICT_KO;
  const abs = (p) => (!p ? '' : p.startsWith('/') ? p : `${run.dir}/${p}`);
  const counts = {};
  for (const c of cases) counts[c.verdict] = (counts[c.verdict] || 0) + 1;
  $('#repCounts').innerHTML = [`<span class="chip">TC ${cases.length}</span>`,
    ...Object.entries(counts).map(([v, n]) => `<span class="chip v-${v === 'HUMAN' ? 'UNSURE' : v}">${ko[v] || v} ${n}</span>`)].join('');
  const why = (c) => {
    const parts = [];
    if (c.error) parts.push(`${c.error.kind} at ${c.error.step}: ${c.error.detail}`);
    else if (c.reason) parts.push(c.reason);
    for (const cp of c.checkpoints || []) {
      const bad = (cp.checks || []).filter((x) => !x.ok).map((x) => x.check);
      if (bad.length) parts.push(`${cp.name}: ${bad.join('; ')}`);
      if (cp.verdict === 'HUMAN') parts.push(`${cp.name}: 사람 확인 — ${cp.human || ''}`);
    }
    return parts.join(' / ');
  };
  const rows = cases.map((c, i) => {
    const sc = c.scenario || {};
    const thumbs = (c.checkpoints || []).filter((cp) => cp.shot).map((cp) => `<img class="thumb" src="${fileUrl(abs(cp.shot))}" title="${esc(cp.name)} · ${esc(ko[cp.verdict] || cp.verdict)}" loading="lazy">`).join('');
    return `<tr data-i="${i}"><td>${esc(sc.tab || '')}</td><td>${esc(sc.no || '')}</td><td class="muted">${esc(sc.path || c.title || c.id)}</td><td>${esc(sc.expected || '')}</td>
      <td><span class="chip v-${c.verdict === 'HUMAN' ? 'UNSURE' : c.verdict}">${esc(ko[c.verdict] || c.verdict)}</span></td><td>${esc(why(c)) || '-'}</td><td class="thumbs">${thumbs}</td></tr>`;
  }).join('');
  $('#repBody').innerHTML = cases.length
    ? `<table class="grid summary-table"><thead><tr><th>탭</th><th>No</th><th>분류</th><th>기대 결과</th><th>판정</th><th>사유</th><th>캡처</th></tr></thead><tbody>${rows}</tbody></table>`
    : '<p class="muted">실행한 TC 가 없습니다</p>';
  // 사람이 볼 것 — 실패한 지점, 사람 확인 지점, 진행이 멈춘 액션
  const look = (run.results && run.results.attention) || [];
  const lookHtml = `<div class="attention-box"><h3>사람이 볼 것 ${look.length ? look.length : ''}</h3>${look.length
    ? `<table class="grid"><thead><tr><th>탭</th><th>No</th><th>지점·액션</th><th>판정</th><th>왜</th><th>캡처</th></tr></thead><tbody>${look.map((x) => {
      const i = cases.findIndex((c) => c.id === x.case);
      return `<tr data-i="${i}"><td>${esc(x.tab)}</td><td>${esc(x.no)}</td><td>${esc(x.what)}</td><td><span class="chip v-${chipOf(x.verdict)}">${esc(ko[x.verdict] || x.verdict)}</span></td><td>${esc(x.why)}</td><td>${x.shot ? `<img class="thumb" src="${fileUrl(abs(x.shot))}" loading="lazy">` : '-'}</td></tr>`;
    }).join('')}</tbody></table>`
    : '<p class="muted">없음 — 모든 지점이 조건을 통과했고 사람 확인 지점이 없다.</p>'}</div>`;
  $('#repBody').innerHTML = lookHtml + $('#repBody').innerHTML;
  $('#repFull').open = true;
  $('#repPlays').innerHTML = cases.map((c, i) => {
    const sc = c.scenario || {};
    const labels = sc.labels || {};
    const err = c.error ? `<div class="play-reason">진행 실패: ${esc(c.error.kind)} at ${esc(c.error.step)} — ${esc(c.error.detail)}</div>${c.error.shot ? `<div class="gallery play-figs"><figure><img loading="lazy" src="${fileUrl(abs(c.error.shot))}"><figcaption>실패 시점</figcaption></figure></div>` : ''}` : '';
    const flow = flowOf(c);
    const strip = flow.length ? `<div class="flow">${flow.map((x, n) => `<figure class="flow-item ${x.kind}"><div class="flow-n">${n + 1}</div>${x.shot ? `<img loading="lazy" src="${fileUrl(abs(x.shot))}">` : '<div class="noshot">캡처 없음</div>'}<figcaption>${x.kind === 'checkpoint' ? '채점 ' : ''}${esc(x.label)}<br><span class="chip v-${chipOf(x.verdict)}">${esc(ko[x.verdict] || x.verdict)}</span></figcaption></figure>`).join('')}</div>` : '';
    const cps = (c.checkpoints || []).map((cp) => `<div class="sc-point"><div><strong>${esc(cp.name)}</strong> ${esc(labels[cp.name] || '')} · <span class="chip v-${cp.verdict === 'HUMAN' ? 'UNSURE' : cp.verdict}">${esc(ko[cp.verdict] || cp.verdict)}</span></div>
      ${(cp.checks || []).length ? `<ul class="sc-checks">${cp.checks.map((x) => `<li class="${x.ok ? 'ok' : 'bad'}">${x.ok ? '✓' : '✗'} ${esc(x.check)}${x.ok ? '' : ` <span class="muted">(${esc(x.detail)})</span>`}</li>`).join('')}</ul>` : ''}
      ${cp.human ? `<div class="sc-human">사람 확인: ${esc(cp.human)}</div>` : ''}
      ${cp.shot ? `<div class="gallery play-figs"><figure><img loading="lazy" src="${fileUrl(abs(cp.shot))}"><figcaption>${esc(cp.name)}</figcaption></figure></div>` : '<div class="muted">캡처 없음</div>'}</div>`).join('');
    return `<section id="play-${i}" class="play-card v-${c.verdict}">
      <div class="play-head"><span class="chip v-${c.verdict === 'HUMAN' ? 'UNSURE' : c.verdict}">${esc(ko[c.verdict] || c.verdict)}</span> <strong>${esc(sc.tab || '')} · No.${esc(sc.no || '')}</strong><span class="spacer"></span><button class="revealplay" data-rel="${esc(c.id)}">캡처 폴더</button></div>
      <div class="play-reason">${esc(sc.path || '')}${sc.expected ? ` — ${esc(sc.expected)}` : ''}</div>${err}${strip ? `<div class="muted">흐름 — 실행 순서대로(액션은 진행 여부, 채점은 조건 판정)</div>${strip}` : ''}${cps}</section>`;
  }).join('');
  $('#repAttention').hidden = true;
  $$('#repBody tr[data-i]').forEach((tr) => tr.addEventListener('click', () => focusPlay(tr.dataset.i)));
  $$('#repBody img, #repPlays img').forEach((img) => img.addEventListener('click', (e) => { e.stopPropagation(); window.open(img.src); }));
  $$('#repPlays .revealplay').forEach((b) => b.addEventListener('click', () => qa.runsOpenFile(state.repName, b.dataset.rel).catch((e) => toast($('#repStatus'), e.message, true))));
  toast($('#repStatus'), '');
}
async function loadRuns() {
  const runs = await qa.runsList();
  $('#repList').innerHTML = runs.map((r) => {
    const t = runTitle(r.name);
    return `<li data-name="${esc(r.name)}" title="${esc(r.name)}" class="${r.name === state.repName ? 'active' : ''}">${esc(t.title)}<small>${esc(t.sub || new Date(r.mtime).toLocaleString())}${r.summary ? ' · 요약 있음' : ''}</small></li>`;
  }).join('');
  $('#repEmpty').hidden = runs.length > 0;
  $('#repView').hidden = runs.length === 0;
  if (!runs.some((r) => r.name === state.repName)) state.repName = null;
  if (!state.repName && runs.length) openRun(runs[0].name);
  $$('#repList li[data-name]').forEach((li) => {
    li.addEventListener('click', () => openRun(li.dataset.name));
    li.addEventListener('contextmenu', (e) => { e.preventDefault(); qa.runsMenu(li.dataset.name); });
  });
}
qa.on('runs:deleted', async (name) => {
  if (state.repName === name) state.repName = null;
  await loadRuns();
});
$('#repRefresh').addEventListener('click', loadRuns);
// 기본 기능 결과를 시트에 다시 쓰기(실행이 끝날 때 자동으로 쓰지 못했거나 다시 쓸 때)
$('#repSheet').addEventListener('click', async () => {
  const name = state.repName;
  const m = /^basic-(.+)-(ios|aos)-(\d{8}-\d{6})$/.exec(name || '');
  if (!m) return;
  // 같은 버전의 다른 플랫폼 실행이 있으면 함께 쓴다(가장 최근 것)
  const runs = await qa.runsList().catch(() => []);
  const other = runs.map((r) => r.name).find((n) => n !== name && n.startsWith(`basic-${m[1]}-${m[2] === 'ios' ? 'aos' : 'ios'}-`));
  if (!writeBasicSheet(m[1], [name, other].filter(Boolean))) toast($('#repStatus'), 'Claude 대화가 진행 중이다 — 끝난 뒤 다시 누른다', true);
});
$('#repGoRun').addEventListener('click', () => activateTab('run'));

function fileUrl(p) {
  return `file://${p.split('/').map(encodeURIComponent).join('/')}`;
}

async function openRun(name) {
  state.repName = name;
  $$('#repList li').forEach((li) => li.classList.toggle('active', li.dataset.name === name));
  $('#repOpen').disabled = true;
  const run = await qa.runsRead(name);
  if (state.repName !== name) return;
  const t = runTitle(name);
  $('#repName').textContent = `${t.title}${t.sub ? ` · ${t.sub}` : ''}`;
  $('#repName').title = name;
  $('#repOpen').disabled = false;
  state.repRel = run.report ? 'report.md' : '';
  $('#repPath').textContent = run.dir ? `${run.dir}/${state.repRel}`.replace(/\/$/, '') : '';
  // 아웃게임 시나리오 실행 — 판이 아니라 TC(시나리오) 단위로 그린다
  // 기본 기능 실행 — 시트의 버전 탭에 결과를 쓰는 버튼
  $('#repSheet').hidden = !(run.results && run.results.kind === 'basic');
  if (run.results && (['scenario', 'basic'].includes(run.results.kind) || (run.results.cases || []).some((c) => Array.isArray(c.checkpoints)))) {
    renderScenarioRun(run);
    return;
  }
  // 집계는 results.json 에서 — 리포트 본문을 읽지 않아도 결과가 보이게
  const all = [];
  for (const c of ((run.results || {}).cases || [])) for (const p of (c.plays || [])) all.push(p);
  const label = { PASS: '통과', FAIL: '실패', ERROR: '진행 실패', UNSURE: '확인 필요' };
  $('#repCounts').innerHTML = all.length
    ? [`<span class="chip">판 ${all.length}</span>`, ...['PASS', 'FAIL', 'ERROR', 'UNSURE'].map((v) => [v, all.filter((p) => p.verdict === v).length]).filter(([, n]) => n).map(([v, n]) => `<span class="chip v-${v}">${label[v]} ${n}</span>`)].join('')
    : '';
  // 전체 표는 결과 데이터로 직접 그린다 — 캡처 썸네일을 판 줄에 붙이고, 줄을 누르면 아래 판 칸으로 간다
  $('#repBody').innerHTML = all.length ? summaryTable(run, all, label)
    : (run.report ? marked.parse(run.report) : '<p class="muted">상세 리포트가 만들어지지 않았습니다</p>');
  $('#repFull').open = true;
  renderPlays(run, all, label);
  $$('#repBody tr[data-i]').forEach((tr) => tr.addEventListener('click', () => focusPlay(tr.dataset.i)));
  $$('#repBody img').forEach((img) => img.addEventListener('click', (e) => { e.stopPropagation(); window.open(img.src); }));
  $$('#repBody .openlog').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); qa.runsOpenFile(state.repName, b.dataset.rel); }));
  // ERROR·FAIL 판마다 진단 버튼
  const plays = [];
  for (const c of ((run.results || {}).cases || [])) {
    for (const p of (c.plays || [])) if (['ERROR', 'FAIL', 'UNSURE'].includes(p.verdict)) plays.push(p);
  }
  $('#repAttention').hidden = !plays.length;
  $('#repDiagnose').innerHTML = plays.map((p) => `<div class="diag"><div class="diag-head"><span class="chip v-${p.verdict}">${label[p.verdict] || p.verdict}</span> <strong>${esc(p.case)} · ${p.play}판</strong><span class="spacer"></span><button data-case="${esc(p.case)}" data-play="${p.play}">AI 진단</button></div><div class="diag-reason">${esc(p.reason)}</div><div class="md out" hidden></div></div>`).join('');
  $$('#repDiagnose button').forEach((b) => b.addEventListener('click', async () => {
    const out = $('.out', b.parentElement);
    out.hidden = false;
    out.textContent = '진단 중…';
    b.disabled = true;
    try {
      const r = await qa.claudeDiagnose(name, b.dataset.case, Number(b.dataset.play));
      out.innerHTML = marked.parse(r.text);
    } catch (e) { out.textContent = e.message; }
    b.disabled = false;
  }));
  toast($('#repStatus'), '');
}
// 판마다 한 칸 — 판정·조합·되감기 시각·캡처(조합/직전/직후/실패)·실패 로그
// 실제로 돌아간 거리로 적는다(게임 창의 「N초 전」) — 고른 지점이 아직 없어 앞 지점으로 간 경우도 그대로 보인다
const pointText = (x) => (x.at !== null && x.at !== undefined && x.to !== null && x.to !== undefined ? `${Math.round(x.at - x.to)}초 전` : '-');
const fmtT = (t) => (t === null || t === undefined ? '-' : `${Number(t).toFixed(2)}초`);
function comboHtml(p) {
  const n = p.cardNames;
  if (!n) {
    const c = p.cards || {};
    return esc(c.cookie1 ? `${c.cookie1} · ${c.cookie2} · ${c.pet} · ${(c.treasures || []).join(' / ')}` : '-');
  }
  return [['쿠키1', n.cookie1], ['쿠키2', n.cookie2], ['펫', n.pet], ['보물', n.treasures.join(' / ')]]
    .map(([k, v]) => `<span class="combo-item"><b>${k}</b> ${esc(v)}</span>`).join('');
}
function summaryTable(run, all, label) {
  const head = '<tr><th>케이스</th><th>판</th><th>판정</th><th>사유</th><th>조합</th><th>되감기(요청 → 돌아간 인게임 시각)</th><th>충돌</th><th>부활</th><th>구멍 구출</th><th>이어달리기</th><th>보너스타임</th><th>캡처</th></tr>';
  const rows = all.map((p, i) => {
    const base = `${run.dir}/${p.case}/play${p.play}`;
    const rw = (p.rewinds || []).map((x) => `${fmtT(x.at)} → ${fmtT(x.to)} ${esc(x.result)}`).join('<br>') || '-';
    const n = (type) => (p.events || []).filter((e) => e.type === type).length;
    const crashes = n('crash');
    const shots = (p.figures || []).map((f) => `<img class="thumb" loading="lazy" src="${fileUrl(`${base}/${f.file}`)}" title="${esc(f.label)}${f.t !== null && f.t !== undefined ? ` · ${fmtT(f.t)}` : ''}">`).join('');
    const log = p.gameLog ? `<button class="openlog" data-rel="${esc(`${p.case}/play${p.play}/${p.gameLog}`)}">게임 로그</button>` : '';
    return `<tr data-i="${i}" class="v-${p.verdict}" title="눌러서 아래 상세로 이동"><td>${esc(p.case)}</td><td>${p.play}</td><td><span class="chip v-${p.verdict}">${label[p.verdict] || p.verdict}</span></td><td>${esc(p.reason)}</td><td class="combo-cell">${comboHtml(p)}</td><td>${rw}</td><td>${crashes}회</td><td>${n('revive')}</td><td>${n('rescue_click')}</td><td>${n('relay_click')}</td><td>${n('bonus_enter')}</td><td class="thumbs">${shots || '-'}${log}</td></tr>`;
  }).join('');
  return `<table class="grid summary-table"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
}
function focusPlay(i) {
  const card = $(`#play-${i}`);
  if (!card) return;
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  card.classList.remove('flash');
  void card.offsetWidth;
  card.classList.add('flash');
}
function renderPlays(run, all, label) {
  $('#repPlays').innerHTML = all.map((p, i) => {
    const base = `${run.dir}/${p.case}/play${p.play}`;
    const rewinds = (p.rewinds || []).length
      ? `<table class="grid rewinds"><thead><tr><th>#</th><th>트리거</th><th>요청한 인게임 시각</th><th>돌아간 인게임 시각</th><th>지점</th><th>결과</th></tr></thead><tbody>${p.rewinds.map((x, i) => `<tr><td>${i + 1}</td><td>${esc(x.trigger || '-')}</td><td>${fmtT(x.at)}</td><td>${fmtT(x.to)}</td><td>${pointText(x)}</td><td>${esc(x.result)}</td></tr>`).join('')}</tbody></table>`
      : '<div class="muted">되감기 없음</div>';
    const figs = (p.figures || []).map((f) => `<figure><img loading="lazy" src="${fileUrl(`${base}/${f.file}`)}"><figcaption>${esc(f.label)}${f.t !== null && f.t !== undefined ? ` · ${fmtT(f.t)}` : ''}</figcaption></figure>`).join('');
    const log = (p.gameLog ? `<button class="openlog" data-rel="${esc(`${p.case}/play${p.play}/${p.gameLog}`)}">게임 로그 열기</button>` : '')
      + `<button class="revealplay" data-rel="${esc(`${p.case}/play${p.play}`)}" title="이 판의 캡처·로그가 든 폴더를 Finder 에서 연다">캡처 폴더</button>`;
    return `<section id="play-${i}" class="play-card v-${p.verdict}">
      <div class="play-head"><span class="chip v-${p.verdict}">${label[p.verdict] || p.verdict}</span> <strong>${esc(p.case)} · ${p.play}판</strong><span class="spacer"></span>${log}</div>
      <div class="play-reason">${esc(p.reason)} · 충돌 ${(p.events || []).filter((e) => e.type === 'crash').length}회</div>
      <div class="combo">${comboHtml(p)}</div>
      ${rewinds}
      ${figs ? `<div class="gallery play-figs">${figs}</div>` : ''}
    </section>`;
  }).join('');
  $$('#repPlays img').forEach((img) => img.addEventListener('click', () => window.open(img.src)));
  $$('#repPlays .openlog').forEach((b) => b.addEventListener('click', () => qa.runsOpenFile(state.repName, b.dataset.rel)));
  $$('#repPlays .revealplay').forEach((b) => b.addEventListener('click', () => qa.runsOpenFile(state.repName, b.dataset.rel).catch((e) => toast($('#repStatus'), e.message, true))));
}
$('#repOpen').addEventListener('click', () => state.repName && qa.runsOpen(state.repName));
$('#repReveal').addEventListener('click', () => state.repName && qa.runsReveal(state.repName, state.repRel || '').catch((e) => toast($('#repStatus'), e.message, true)));

// ---------- Claude 대화 ----------
let botEl = null;
let botText = '';
$('#chatSend').addEventListener('click', async () => {
  const text = $('#chatInput').value.trim();
  if (!text) return;
  $('#chatInput').value = '';
  $('#chatStarters').hidden = true;
  const me = document.createElement('div');
  me.className = 'me';
  me.textContent = text;
  $('#chatLog').appendChild(me);
  botEl = document.createElement('div');
  botEl.className = 'bot md';
  botEl.textContent = '…';
  $('#chatLog').appendChild(botEl);
  botText = '';
  state.chatId += 1;
  setChatBusy(true);
  try { await qa.claudeChat(state.chatId, text, state.chatSession, state.chatAllow || []); } catch (e) { botEl.textContent = e.message; setChatBusy(false); }
});
// 진행 중에는 보내기 자리에 멈추기를 둔다
function setChatBusy(busy) {
  $('#chatSend').hidden = busy;
  $('#chatStop').hidden = !busy;
}
$$('#chatStarters button').forEach((b) => b.addEventListener('click', () => { $('#chatInput').value = b.dataset.prompt; $('#chatInput').focus(); }));
$('#chatInput').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('#chatSend').click(); });
$('#chatStop').addEventListener('click', () => qa.claudeStop(state.chatId));
$('#chatNew').addEventListener('click', () => {
  state.chatSession = null;
  state.chatAllow = [];
  $$('#chatLog > :not(#chatStarters)').forEach((el) => el.remove());
  $('#chatStarters').hidden = false;
});
qa.on('claude:chunk', ({ chatId, text }) => {
  if (chatId !== state.chatId || !botEl) return;
  botText += text;
  botEl.innerHTML = marked.parse(botText);
  $('#chatLog').scrollTop = $('#chatLog').scrollHeight;
});
qa.on('claude:done', ({ chatId, ok, sessionId, cost, error, denials }) => {
  if (chatId !== state.chatId) return;
  setChatBusy(false);
  if (sessionId) state.chatSession = sessionId;
  const foot = document.createElement('div');
  foot.className = 'muted';
  foot.textContent = ok ? (cost ? `$${cost.toFixed(3)}` : '') : `오류: ${error}`;
  $('#chatLog').appendChild(foot);
  if (denials && denials.length) showDenials(denials);
});
// Claude 가 허용 목록 밖의 명령을 하려다 멈춘 것 — 사람이 보고 허용하면 그 대화를 이어서 다시 하게 한다
function showDenials(denials) {
  const box = document.createElement('div');
  box.className = 'denials';
  const label = (d) => (d.tool === 'Bash' ? (d.input && d.input.command) || '' : `${d.tool} ${(d.input && (d.input.file_path || d.input.path)) || ''}`);
  box.innerHTML = `<strong>허락이 필요해 멈춘 작업 ${denials.length}개</strong>
    <ul>${denials.map((d) => `<li><code>${esc(label(d))}</code></li>`).join('')}</ul>
    <div class="row"><button class="primary" data-how="once">이번 대화에서 허용하고 이어가기</button>
    <button data-how="always" title="${esc(denials.map((d) => d.always).join('\n'))}">항상 허용하고 이어가기</button>
    <span class="muted">항상 허용: ${esc(denials.map((d) => d.always).join(', '))}</span></div>`;
  $('#chatLog').appendChild(box);
  $('#chatLog').scrollTop = $('#chatLog').scrollHeight;
  $$('button', box).forEach((b) => b.addEventListener('click', async () => {
    $$('button', box).forEach((x) => { x.disabled = true; });
    const always = b.dataset.how === 'always';
    if (always) {
      const info = await qa.kitInfo();
      await qa.settingsWrite({ chatAllow: [...new Set([...(info.settings.chatAllow || []), ...denials.map((d) => d.always)])] });
    }
    state.chatAllow = [...new Set([...(state.chatAllow || []), ...denials.map((d) => d.once)])];
    box.querySelector('.row').insertAdjacentHTML('beforeend', `<span class="muted"> — ${always ? '항상' : '이번 대화에서'} 허용했다</span>`);
    $('#chatInput').value = '허용했다. 막혔던 작업을 다시 실행해서 이어가.';
    $('#chatSend').click();
  }));
}

// ---------- 시작 ----------
(async () => {
  $$('input[list]').forEach(attachCombo);
  initServerPreset();
  // 필수 도구가 빠져 있으면 「준비」 탭부터 보여준다
  runSetupCheck().then((r) => { if (r && r.fail) $('#tabs button[data-tab="setup"]').click(); });
  await loadDevices();
  const scenSt = await refreshScenario();
  if (scenSt && !scenSt.ready) $('#tabs button[data-tab="setup"]').click();
  // 받아 둔 저장소가 있으면 시작할 때 남이 바꾼 것을 받아 온다
  if (scenSt && scenSt.ready && scenSt.upstream) await scenDo('받기', () => qa.scenarioPull(), { auto: true });
  await loadPresets();
  await loadSuites();
  for (const r of await qa.runActive()) runPanelStart(r.platform);
  syncRunPanels();
})();
