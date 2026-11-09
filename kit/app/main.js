'use strict';

const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { app, BrowserWindow, ipcMain, dialog, shell, Menu, nativeTheme } = require('electron');
const kit = require('./lib/kit');
const claude = require('./lib/claude');
const model = require('./lib/caseModel');
const setup = require('./lib/setup');
const scen = require('./lib/git');

let win = null;
const runners = new Map(); // platform → { child, kind, suiteFile }
const chats = new Map();   // chat id → child
let setupChild = null;

function send(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

function createWindow() {
  win = new BrowserWindow({
    width: 1400,
    height: 900,
    title: 'QA 자동화',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  if (process.env.QA_APP_SMOKE) {
    // 점검용: 화면 콘솔을 터미널로 내보내고 몇 초 뒤 닫는다
    win.webContents.on('console-message', (event) => console.log(`[renderer:${event.level}] ${event.message}`));
    win.webContents.on('did-finish-load', () => {
      console.log('[smoke] loaded');
      setTimeout(async () => {
        const probe = await win.webContents.executeJavaScript(
          `JSON.stringify({ tabs: document.querySelectorAll('.tab').length, setupRows: document.querySelectorAll('#setupRows tr').length, setupHidden: document.querySelector('#setupSection').hidden, activeTab: document.querySelector('#tabs button.active').dataset.tab, scenSetup: document.querySelector('#scenSetup').textContent.trim().slice(0, 60), scen: document.querySelector('#scenWhere').textContent + ' ' + document.querySelector('#scenState').textContent, setupStatus: document.querySelector('#setupStatus').textContent, iosStatus: document.querySelector('tr[data-platform=ios] .device-status').textContent, suites: document.querySelector('#rwSuite').options.length, cases: document.querySelectorAll('#rwCases li[data-i]').length, kit: document.querySelector('#kitPath').textContent, marked: typeof marked, model: typeof caseModel })`);
        console.log(`[smoke] ${probe}`);
        if (process.env.QA_APP_SHOT) {
          // 점검용: 탭마다 화면을 PNG 로 남긴다
          for (const tab of ['setup', 'devices', 'rewind', 'outgame', 'run', 'reports', 'chat']) {
            await win.webContents.executeJavaScript(`document.querySelector('#tabs button[data-tab="${tab}"]').click()`);
            await new Promise((r) => setTimeout(r, 800));
            const img = await win.webContents.capturePage();
            fs.writeFileSync(path.join(process.env.QA_APP_SHOT, `${tab}.png`), img.toPNG());
          }
        }
        if (process.env.QA_APP_STEPS && process.env.QA_APP_SHOT) {
          // 점검용: [{ "js": 화면에서 돌릴 코드, "wait": ms, "shot": 파일 이름 }] 순서대로 조작하고 캡처한다
          for (const step of JSON.parse(fs.readFileSync(process.env.QA_APP_STEPS, 'utf8'))) {
            if (step.js) console.log(`[step] ${await win.webContents.executeJavaScript(step.js).catch((e) => `error ${e.message}`)}`);
            await new Promise((r) => setTimeout(r, step.wait || 800));
            if (step.shot) fs.writeFileSync(path.join(process.env.QA_APP_SHOT, `${step.shot}.png`), (await win.webContents.capturePage()).toPNG());
          }
        }
        app.quit();
      }, 25000);
    });
  }
  win.on('close', (event) => {
    if (runners.size === 0) return;
    const choice = dialog.showMessageBoxSync(win, {
      type: 'warning', buttons: ['실행 중지하고 닫기', '취소'], defaultId: 1, cancelId: 1,
      message: `실행 중인 테스트가 ${runners.size}개 있다. 닫으면 중지한다.`,
      detail: 'iOS 는 실행기를 멈추면 앱도 함께 끝난다(콘솔 연결 종료).',
    });
    if (choice === 1) event.preventDefault();
    else for (const r of runners.values()) r.child.kill('SIGINT');
  });
}

app.whenReady().then(() => {
  if (process.env.QA_APP_THEME) nativeTheme.themeSource = process.env.QA_APP_THEME; // 점검용: light|dark 강제
  createWindow();
});
app.on('window-all-closed', () => app.quit());

const handle = (channel, fn) => ipcMain.handle(channel, async (_event, ...args) => {
  try {
    return { ok: true, value: await fn(...args) };
  } catch (err) {
    return { ok: false, error: String(err && err.message ? err.message : err) };
  }
});

// --- 파일 ---
handle('kit:info', () => ({ kit: kit.P.kit, settings: kit.readSettings() }));
handle('cases:list', () => kit.listCases());
handle('cases:read', (name) => kit.readCase(name));
handle('cases:write', (name, suite) => {
  if (suite && suite.kind === 'rewind') {
    const errs = model.validateSuite(suite);
    if (errs.length) throw new Error(errs.join('\n'));
  }
  kit.writeCase(name, suite);
  return true;
});
// 묶음 파일 삭제 — 케이스를 모두 지운 묶음. 「변경 공유」로 올리면 팀 저장소에서도 지워진다
handle('cases:delete', (name) => {
  const file = kit.caseFile(name);
  if (fs.existsSync(file)) fs.unlinkSync(file);
  return true;
});
handle('cases:authors', () => scen.suiteAuthors(kit.listCases().map((x) => x.file)));
handle('gh:login', () => scen.ghLogin());
// 게임 서버 프리셋 목록 — 게임 서버 선택 창과 같은 주소에서 이름만 받는다
handle('presets:server', async () => {
  const r = await fetch('https://crepe.devspie.com/presets/list', { signal: AbortSignal.timeout(15000) });
  if (!r.ok) throw new Error(`프리셋 목록을 받지 못했다(HTTP ${r.status}) — 사내망·VPN 연결을 확인한다`);
  const data = await r.json();
  return (data.presets || []).map((p) => p.name).filter((n) => typeof n === 'string' && n);
});
handle('cases:check', (name) => new Promise((resolve) => {
  const { execFile } = require('child_process');
  const settings = kit.readSettings();
  execFile(settings.python, [kit.P.rewindRunner, kit.caseFile(name), '--check'], { cwd: kit.P.kit, env: kit.toolEnv() },
    (err, stdout) => {
      try { resolve(JSON.parse(stdout)); } catch { resolve({ ok: false, errors: [String(err ? err.message : stdout)] }); }
    });
}));
handle('runs:list', () => kit.listRuns());
handle('runs:read', (name) => kit.readRun(name));
handle('runs:open', (name) => shell.openPath(kit.runDir(name)));
// Finder 에서 실행 폴더 안의 파일·폴더를 선택한 채로 보여 준다(리포트·판별 캡처 폴더)
handle('runs:reveal', (name, rel) => {
  const dir = kit.runDir(name);
  const target = path.resolve(dir, String(rel || ''));
  if ((target !== dir && !target.startsWith(dir + path.sep)) || !fs.existsSync(target)) throw new Error('실행 폴더 안의 경로가 아니다');
  shell.showItemInFolder(target);
  return target;
});
// 실행 폴더 안의 파일만 연다(실패 판의 게임 로그 등)
handle('runs:openFile', (name, rel) => {
  const dir = kit.runDir(name);
  const target = path.resolve(dir, String(rel || ''));
  if (!target.startsWith(dir + path.sep) || !fs.existsSync(target)) throw new Error('실행 폴더 안의 파일이 아니다');
  return shell.openPath(target);
});
// 리포트 목록 오른쪽 클릭 메뉴 — 삭제는 그 실행 폴더(리포트·로그·캡처) 전체를 휴지통으로 옮긴다
async function deleteRun(name) {
  const dir = kit.runDir(name);
  if (!fs.existsSync(dir)) return;
  const busy = [...runners.keys()].some((platform) => name.includes(`-${platform}-`));
  if (busy) {
    dialog.showMessageBox(win, { type: 'info', message: '이 기기에서 테스트가 돌고 있어 지금은 지울 수 없다. 끝난 뒤 지운다.' });
    return;
  }
  const choice = await dialog.showMessageBox(win, {
    type: 'warning', buttons: ['삭제', '취소'], defaultId: 1, cancelId: 1,
    message: `「${name}」 결과를 삭제할까요?`,
    detail: '리포트·요약·로그·캡처가 든 폴더 전체를 휴지통으로 옮깁니다. 휴지통에서 되살릴 수 있습니다.',
  });
  if (choice.response !== 0) return;
  await shell.trashItem(dir);
  send('runs:deleted', name);
}
handle('runs:menu', (name) => {
  const dir = kit.runDir(name);
  Menu.buildFromTemplate([
    { label: '폴더 열기', click: () => shell.openPath(dir) },
    { type: 'separator' },
    { label: '삭제…', click: () => deleteRun(name).catch((err) => dialog.showErrorBox('삭제 실패', String(err.message || err))) },
  ]).popup({ window: win });
  return true;
});
handle('presets:read', () => kit.readPresets());
handle('presets:write', (presets) => { kit.writePresets(presets); return true; });
handle('devices:read', () => kit.readDevices());
handle('devices:write', (devices) => kit.writeDevices(devices));
handle('settings:write', (settings) => kit.writeSettings(settings));

// --- 기기 ---
handle('devices:discover', () => kit.discoverDevices());
handle('device:launch', (platform) => {
  // 아이콘으로 켠 게임은 브리지가 꺼져 있다 — 브리지 켜는 환경값을 넣어 다시 띄운다
  if (runners.has(platform)) throw new Error('이 기기에서 테스트가 돌고 있다. 끝나거나 중지한 뒤 띄운다');
  return kit.gbDevice('launch', platform, [], 90000);
});
handle('device:ping', (platform) => kit.gbDevice('ping', platform, [], 20000));
handle('device:scene', (platform) => kit.gbDevice('scene', platform, [], 20000));
handle('device:maps', async (platform) => {
  const r = await kit.gbDevice('testmode', platform, ['--json', JSON.stringify({ op: 'maps' })], 30000);
  if (!r.ok) throw new Error(r.error || '맵 목록을 받지 못했다(앱이 떠 있고 브리지가 연결돼야 한다)');
  return r.result.maps;
});

// 쿠키·펫·보물 id 와 게임 언어 이름 — 카드 칸에서 이름으로 고를 수 있게 한다
handle('device:cards', async (platform) => {
  const out = {};
  for (const cat of ['cookie', 'pet', 'treasure']) {
    const r = await kit.gbDevice('testmode', platform, ['--json', JSON.stringify({ op: 'cards', category: cat })], 30000);
    if (!r.ok) throw new Error(r.error || '카드 목록을 받지 못했다(앱이 떠 있고 브리지가 연결돼야 한다)');
    const names = r.result.names || [];
    out[cat] = r.result.ids.map((id, i) => ({ id, name: names[i] || '' }));
  }
  return out;
});

// --- 처음 세팅 ---
handle('setup:check', () => setup.runChecks());
handle('setup:action', async (actionId, mode) => {
  const a = setup.findAction(actionId);
  if (mode === 'terminal' && a.command) { await setup.openInTerminal(a.command); return { terminal: true }; }
  if (a.kind === 'open') { await shell.openExternal(a.url); return { opened: a.url }; }
  if (a.kind === 'terminal') { await setup.openInTerminal(a.command); return { terminal: true }; }
  if (a.kind === 'run') {
    if (setupChild) throw new Error('다른 설치가 진행 중이다');
    send('setup:line', `$ ${a.command}`);
    setupChild = setup.runAction(actionId, (line) => send('setup:line', line), (code) => { setupChild = null; send('setup:exit', { actionId, code }); });
    return { started: true };
  }
  throw new Error('지원하지 않는 동작');
});

// --- 시나리오 저장소(팀 git) ---
handle('scenario:status', () => scen.status());
handle('scenario:connect', async (pick) => {
  let dir = null;
  if (pick) {
    const r = await dialog.showOpenDialog(win, { title: '받아 둘 폴더(비어 있는 폴더) 또는 이미 받은 폴더', defaultPath: scen.defaultDir(), properties: ['openDirectory', 'createDirectory'] });
    if (r.canceled) return null;
    dir = r.filePaths[0];
  }
  return scen.connect(dir);
});
handle('scenario:pull', () => scen.pull());
handle('scenario:fetch', () => scen.fetch());
// 앱 업데이트 — 받은 앱 코드를 쓰려면 다시 띄운다. 의존성이 바뀌었으면 먼저 npm install
handle('app:restart', async (deps) => {
  if (runners.size) throw new Error('실행 중인 테스트가 끝난 뒤 다시 시작한다');
  if (deps) {
    await new Promise((resolve, reject) => {
      const child = spawn('npm', ['ci', '--no-audit', '--no-fund'], { cwd: __dirname, env: kit.toolEnv() });
      let err = '';
      child.stderr.on('data', (d) => { err += d; });
      child.on('error', reject);
      child.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`npm ci 실패(exit ${code}): ${err.trim().split('\n').slice(-2).join(' / ')}`))));
    });
  }
  app.relaunch();
  app.exit(0);
  return true;
});
handle('scenario:push', (message) => scen.push(message));
handle('scenario:open', () => shell.openPath(kit.scenarioRoot() || kit.P.cases));

// --- 실행 ---
handle('run:start', (opts) => {
  const { platform } = opts;
  if (runners.has(platform)) throw new Error(`${platform} 에서 이미 실행 중이다`);
  const child = kit.startRunner(opts,
    (line, stream) => send('run:line', { platform, line, stream }),
    (code, last) => {
      runners.delete(platform);
      let runName = null;
      const out = last && (last.out || (last.results && path.dirname(last.results)));
      if (out) runName = path.basename(out);
      send('run:exit', { platform, code, last, runName });
    });
  runners.set(platform, { child, kind: opts.kind, suiteFile: opts.suiteFile });
  return { started: true };
});
handle('run:stop', (platform) => {
  const r = runners.get(platform);
  if (!r) return false;
  r.child.kill('SIGINT');
  setTimeout(() => { if (runners.get(platform) === r) r.child.kill('SIGTERM'); }, 5000);
  return true;
});
handle('run:active', () => [...runners.entries()].map(([platform, r]) => ({ platform, kind: r.kind, suiteFile: r.suiteFile })));

// --- Claude ---
handle('claude:summary', async (runName) => {
  kit.runDir(runName);
  const r = await claude.ask(claude.summaryPrompt(runName));
  if (!r.ok) throw new Error(r.error);
  fs.writeFileSync(path.join(kit.runDir(runName), 'summary.md'), r.text.trim() + '\n');
  return r;
});
handle('claude:diagnose', async (runName, caseId, play) => {
  kit.runDir(runName);
  if (!/^[\w.-]+$/.test(String(caseId)) || !Number.isInteger(play)) throw new Error('케이스·판 번호가 올바르지 않다');
  const r = await claude.ask(claude.diagnosePrompt(runName, caseId, play));
  if (!r.ok) throw new Error(r.error);
  fs.writeFileSync(path.join(kit.runDir(runName), `diagnosis-${caseId}-play${play}.md`), r.text.trim() + '\n');
  return r;
});
handle('claude:caseDraft', async (request, current) => {
  const r = await claude.ask(claude.caseDraftPrompt(request, current));
  if (!r.ok) throw new Error(r.error);
  const draft = model.normalizeCase(model.extractJsonObject(r.text));
  return { draft, errors: model.validateCase(draft), cost: r.cost };
});
handle('claude:chat', (chatId, message, sessionId) => {
  if (chats.has(chatId)) throw new Error('이전 답을 기다리는 중이다');
  const child = claude.chat(message, sessionId,
    (text) => send('claude:chunk', { chatId, text }),
    (result) => { chats.delete(chatId); send('claude:done', Object.assign({ chatId }, result)); });
  chats.set(chatId, child);
  return true;
});
handle('claude:stop', (chatId) => {
  const child = chats.get(chatId);
  if (child) child.kill('SIGINT');
  return Boolean(child);
});
