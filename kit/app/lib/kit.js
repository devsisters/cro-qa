// 키트 폴더(cases·runs·presets·devices.json)와 키트 Python 도구를 다룬다. 실행 판정은 전부 키트 도구가 한다.
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn, execFile } = require('child_process');

const KIT = path.resolve(__dirname, '..', '..');
const P = {
  kit: KIT,
  cases: path.join(KIT, 'cases'),
  runs: path.join(KIT, 'runs'),
  presets: path.join(KIT, 'presets', 'rewind-input.json'),
  devices: path.join(KIT, 'tools', 'device_flows', 'devices.json'),
  workspace: path.join(KIT, 'workspace'),
  settings: path.join(KIT, 'workspace', 'app-settings.json'),
  gbDevice: path.join(KIT, 'tools', 'gb_device.py'),
  rewindRunner: path.join(KIT, 'tools', 'rewind_runner.py'),
  caseRunner: path.join(KIT, 'tools', 'case_runner.py'),
};

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (err) {
    if (fallback !== undefined) return fallback;
    throw err;
  }
}

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2) + '\n');
  fs.renameSync(tmp, file);
}

/** 시나리오 폴더(git 저장소)를 정했으면 거기, 아니면 키트 안. 케이스·프리셋·문서가 이 아래에 있다. */
function scenarioRoot() {
  const dir = module.exports.readSettings().scenarioDir; // 테스트에서 설정을 바꿔 끼울 수 있게 exports 를 거친다
  return dir && path.isAbsolute(dir) && fs.existsSync(dir) ? dir : null;
}
function casesDir() {
  const root = scenarioRoot();
  return root ? path.join(root, 'cases') : P.cases;
}
function presetsFile() {
  const root = scenarioRoot();
  const own = root && path.join(root, 'presets', 'rewind-input.json');
  return own && fs.existsSync(own) ? own : (root ? own : P.presets);
}

/** cases/ 안의 파일 이름만 받는다 — 경로 탈출을 막는다. */
function caseFile(name) {
  if (typeof name !== 'string' || !/^[\w가-힣][\w.\-가-힣]*\.json$/.test(name)) throw new Error(`케이스 파일 이름이 올바르지 않다: ${name}`);
  return path.join(casesDir(), name);
}

function runDir(name) {
  // 점으로 시작하는 이름(.., .hidden)은 받지 않는다
  if (typeof name !== 'string' || !/^[\w가-힣][\w.\-가-힣]*$/.test(name)) throw new Error(`실행 폴더 이름이 올바르지 않다: ${name}`);
  return path.join(P.runs, name);
}

function listCases() {
  const dir = casesDir();
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .map((f) => {
      const suite = readJson(path.join(dir, f), null);
      return {
        file: f,
        kind: suite && suite.kind === 'rewind' ? 'rewind' : 'outgame',
        suite: (suite && suite.suite) || f.replace(/\.json$/, ''),
        count: (suite && Array.isArray(suite.cases) && suite.cases.length) || 0,
        broken: suite === null,
      };
    })
    .sort((a, b) => a.file.localeCompare(b.file));
}

function readCase(name) {
  return readJson(caseFile(name));
}

function writeCase(name, suite) {
  writeJson(caseFile(name), suite);
}

function listRuns() {
  if (!fs.existsSync(P.runs)) return [];
  return fs.readdirSync(P.runs, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => {
      const dir = path.join(P.runs, d.name);
      const has = (f) => fs.existsSync(path.join(dir, f));
      return { name: d.name, mtime: fs.statSync(dir).mtimeMs, report: has('report.md'), summary: has('summary.md'), results: has('results.json') };
    })
    .filter((r) => r.report || r.results)
    .sort((a, b) => b.mtime - a.mtime);
}

function readRun(name) {
  const dir = runDir(name);
  const read = (f) => (fs.existsSync(path.join(dir, f)) ? fs.readFileSync(path.join(dir, f), 'utf8') : '');
  const images = [];
  const walk = (d, depth) => {
    if (depth > 4) return;
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const full = path.join(d, e.name);
      if (e.isDirectory()) walk(full, depth + 1);
      else if (e.name.endsWith('.png') && !full.includes(`${path.sep}crops${path.sep}`)) images.push(path.relative(dir, full));
    }
  };
  walk(dir, 0);
  images.sort();
  return { name, dir, report: read('report.md'), summary: read('summary.md'), results: readJson(path.join(dir, 'results.json'), null), images };
}

function readPresets() {
  const file = presetsFile();
  return readJson(fs.existsSync(file) ? file : P.presets, {});
}

function writePresets(presets) {
  writeJson(presetsFile(), presets);
}

function readDevices() {
  return readJson(P.devices, { ios: { platform: 'ios', device: '' }, aos: { platform: 'android', device: '' } });
}

function writeDevices(devices) {
  const current = readDevices();
  for (const key of ['ios', 'aos']) {
    if (devices[key] && typeof devices[key].device === 'string') {
      current[key] = Object.assign({}, current[key], { device: devices[key].device.trim() });
    }
  }
  writeJson(P.devices, current);
  return current;
}

function readSettings() {
  return Object.assign({ python: 'python3', claude: 'claude', developerDir: '/Applications/Xcode.app/Contents/Developer', scenarioDir: '' }, readJson(P.settings, {}));
}

function writeSettings(settings) {
  const allowed = {};
  for (const key of ['python', 'claude', 'developerDir', 'scenarioDir', 'scenarioRepo', 'serverPreset']) if (typeof settings[key] === 'string') allowed[key] = settings[key].trim();
  if (allowed.scenarioDir && !path.isAbsolute(allowed.scenarioDir)) throw new Error('시나리오 폴더는 전체 경로여야 한다');
  // 앱 안 Claude 에 사람이 「항상 허용」한 도구 규칙(이 컴퓨터에만)
  if (Array.isArray(settings.chatAllow)) allowed.chatAllow = settings.chatAllow.filter((r) => typeof r === 'string' && r.length < 400);
  writeJson(P.settings, Object.assign(readSettings(), allowed));
  return readSettings();
}

/** 키트 도구가 쓰는 환경. GUI 로 띄운 앱은 셸 PATH 를 못 받으니 흔한 경로를 붙인다. */
function toolEnv() {
  const settings = readSettings();
  const extra = ['/opt/homebrew/bin', '/usr/local/bin', path.join(process.env.HOME || '', '.local/bin')];
  return Object.assign({}, process.env, {
    PATH: [...extra, process.env.PATH || ''].join(':'),
    DEVELOPER_DIR: settings.developerDir,
    PYTHONUNBUFFERED: '1',
  });
}

function platformArgs(platform) {
  const devices = readDevices();
  const cfg = devices[platform] || {};
  const args = ['--platform', platform === 'aos' ? 'android' : platform, '--checkout', P.workspace];
  if (cfg.device) args.push('--device', cfg.device);
  return args;
}

/** devicectl list devices --json-output 결과에서 실기기만 뽑는다. connected 가 연결(터널 연결)된 기기다. */
function parseIosDevices(json) {
  const devices = (((json || {}).result || {}).devices) || [];
  return devices
    .filter((d) => ((d.hardwareProperties || {}).reality || 'physical') === 'physical' && ((d.hardwareProperties || {}).platform || 'iOS') === 'iOS')
    .map((d) => {
      const hw = d.hardwareProperties || {};
      const conn = d.connectionProperties || {};
      return {
        id: d.identifier,
        name: (d.deviceProperties || {}).name || hw.marketingName || hw.deviceType || d.identifier,
        model: hw.marketingName || hw.deviceType || '',
        os: (d.deviceProperties || {}).osVersionNumber || '',
        state: conn.tunnelState || 'unknown',
        connected: conn.tunnelState === 'connected',
      };
    });
}

/** adb devices -l 결과. state 가 device 인 것만 연결로 본다(unauthorized·offline 은 제외). */
function parseAdbDevices(text) {
  return String(text || '').split('\n').slice(1)
    .map((line) => line.trim().split(/\s+/))
    .filter((cols) => cols.length >= 2 && cols[0])
    .map(([serial, st, ...rest]) => {
      const kv = Object.fromEntries(rest.filter((x) => x.includes(':')).map((x) => [x.slice(0, x.indexOf(':')), x.slice(x.indexOf(':') + 1)]));
      return { id: serial, name: (kv.model || serial).replace(/_/g, ' '), model: kv.model || '', os: '', state: st, connected: st === 'device' };
    });
}

function execText(cmd, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    execFile(cmd, args, { env: toolEnv(), timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err) reject(new Error(String(stderr || err.message).trim().slice(-300)));
      else resolve(String(stdout));
    });
  });
}

/** 맥에 연결된 iOS·Android 기기를 찾는다. 한쪽이 실패해도 다른 쪽은 돌려준다. */
async function discoverDevices() {
  const out = { ios: [], aos: [], errors: {} };
  const tmp = path.join(os.tmpdir(), `qa-devicectl-${process.pid}-${Date.now()}.json`);
  await Promise.all([
    execText('xcrun', ['devicectl', 'list', 'devices', '--json-output', tmp], 30000)
      .then(() => { out.ios = parseIosDevices(readJson(tmp, {})); })
      .catch((err) => { out.errors.ios = err.message; })
      .finally(() => fs.rmSync(tmp, { force: true })),
    execText('adb', ['devices', '-l'], 15000)
      .then((text) => { out.aos = parseAdbDevices(text); })
      .catch((err) => { out.errors.aos = err.message; }),
  ]);
  return out;
}

/** gb_device.py 를 한 번 부르고 마지막 JSON 줄을 돌려준다. */
function gbDevice(op, platform, extraArgs = [], timeoutMs = 30000) {
  const settings = readSettings();
  return new Promise((resolve) => {
    execFile(settings.python, [P.gbDevice, op, ...platformArgs(platform), ...extraArgs], { cwd: KIT, env: toolEnv(), timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024 },
      (err, stdout) => {
        const lines = String(stdout || '').trim().split('\n').filter((l) => l.startsWith('{'));
        try {
          resolve(JSON.parse(lines[lines.length - 1]));
        } catch {
          resolve({ ok: false, error: err ? String(err.message).slice(-300) : '응답 없음' });
        }
      });
  });
}

/** 실행기(rewind_runner·case_runner)를 띄운다. 줄마다 onLine, 끝나면 onExit(code, lastJson). */
/** 맵 녹화·재생 파일 폴더 — 시나리오 저장소가 있으면 그 안(팀이 같이 쓴다), 없으면 키트 안 */
function recordingsDir() {
  const root = scenarioRoot();
  return path.join(root || KIT, 'recordings');
}

function startRunner({ kind, suiteFile, platform, caseIds, relaunch, recordCase }, onLine, onExit) {
  const settings = readSettings();
  let file;
  if (kind === 'rewind' && recordCase) {
    // 맵 녹화 — 지금 케이스를 사람이 한 판 플레이하도록 바꿔 임시 묶음으로 돌린다(케이스 파일은 그대로 둔다)
    const c = JSON.parse(JSON.stringify(recordCase));
    c.id = 'REC'; c.plays = 1; c.triggers = []; c.timeoutSec = Math.max(900, c.timeoutSec || 0);
    c.input = { mode: 'record', rescue: true, relay: true, seed: 1 };
    file = path.join(P.runs, '_record-suite.json');
    fs.mkdirSync(P.runs, { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ suite: 'record', kind: 'rewind', cases: [c] }, null, 1));
  } else {
    file = caseFile(suiteFile);
  }
  const devices = readDevices();
  const deviceId = (devices[platform] || {}).device;
  const args = kind === 'rewind'
    ? [P.rewindRunner, file, '--platform', platform]
    : [P.caseRunner, file, '--platform', platform];
  if (deviceId) args.push('--device', deviceId);
  if (caseIds && caseIds.length) args.push('--case', caseIds.join(','));
  if (kind === 'rewind') args.push('--recordings', recordingsDir());
  if (kind !== 'rewind' && relaunch) args.push('--relaunch');
  // 기기 탭에서 고른 게임 서버 프리셋 — 서버 선택 창이 뜨면 이것을 고른다(묶음에 적힌 프리셋보다 우선)
  if (settings.serverPreset) args.push('--preset', settings.serverPreset);
  const child = spawn(settings.python, args, { cwd: KIT, env: toolEnv() });
  let lastJson = null;
  let buffer = '';
  const feed = (chunk, stream) => {
    buffer += chunk.toString();
    let idx;
    while ((idx = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 1);
      if (line.startsWith('{')) {
        try { lastJson = JSON.parse(line); } catch { /* 진행 줄 */ }
      }
      onLine(line, stream);
    }
  };
  child.stdout.on('data', (c) => feed(c, 'out'));
  child.stderr.on('data', (c) => feed(c, 'err'));
  child.on('close', (code) => onExit(code, lastJson));
  child.on('error', (err) => onExit(-1, { ok: false, error: String(err.message) }));
  return child;
}

module.exports = {
  P, readJson, writeJson, listCases, readCase, writeCase, listRuns, readRun, runDir,
  readPresets, writePresets, readDevices, writeDevices, readSettings, writeSettings, toolEnv, gbDevice, startRunner,
  parseIosDevices, parseAdbDevices, discoverDevices, scenarioRoot, casesDir, presetsFile, caseFile, recordingsDir,
};
