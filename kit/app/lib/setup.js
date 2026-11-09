// 처음 세팅 점검 — 키트·앱이 쓰는 도구가 이 맥에 있는지 보고, 없으면 고칠 방법(앱에서 설치·터미널 명령·링크)을 준다.
// 명령은 이 파일의 표에 있는 것만 실행한다. 화면은 점검 id·동작 id 만 넘긴다.
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile, spawn } = require('child_process');
const kit = require('./kit');

const BUNDLE = 'com.devsisters.enterprise.gb';
const PACKAGE = 'com.devsisters.gb';

function sh(cmd, args, { timeout = 20000, env } = {}) {
  return new Promise((resolve) => {
    execFile(cmd, args, { env: env || kit.toolEnv(), timeout, maxBuffer: 16 * 1024 * 1024 }, (err, stdout, stderr) => {
      resolve({ code: err ? (typeof err.code === 'number' ? err.code : -1) : 0, out: String(stdout || ''), err: String(stderr || (err && err.message) || '') });
    });
  });
}

const firstExisting = (paths) => paths.find((p) => p && fs.existsSync(p)) || null;
const brewPath = () => firstExisting(['/opt/homebrew/bin/brew', '/usr/local/bin/brew']);
const lastLine = (s) => String(s || '').trim().split('\n').filter(Boolean).pop() || '';
const q = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`;

/** 각 점검의 「고치는 방법」. run=앱 안에서 실행, terminal=터미널 창에서 실행(비밀번호·대화형), open=링크, apply=앱 설정 변경 */
function actionTable(settings) {
  const brew = brewPath() || 'brew';
  return {
    brew: { label: 'Homebrew 설치', kind: 'terminal', command: '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' },
    clt: { label: 'Command Line Tools 설치', kind: 'run', argv: ['xcode-select', '--install'], command: 'xcode-select --install' },
    xcode: { label: 'App Store 에서 Xcode 열기', kind: 'open', url: 'macappstore://apps.apple.com/app/id497799835' },
    xcodeFirst: { label: 'Xcode 추가 구성요소 설치', kind: 'terminal', command: `sudo DEVELOPER_DIR=${q(settings.developerDir)} xcodebuild -runFirstLaunch` },
    adb: { label: 'adb 설치', kind: 'run', argv: [brew, 'install', '--cask', 'android-platform-tools'], command: 'brew install --cask android-platform-tools' },
    node: { label: 'Node.js 설치', kind: 'run', argv: [brew, 'install', 'node'], command: 'brew install node' },
    nodeUp: { label: 'Node.js 올리기', kind: 'run', argv: [brew, 'upgrade', 'node'], command: 'brew upgrade node' },
    chrome: { label: 'Chrome 내려받기', kind: 'open', url: 'https://www.google.com/chrome/' },
    claude: { label: 'Claude Code 설치', kind: 'terminal', command: 'curl -fsSL https://claude.ai/install.sh | bash' },
    gh: { label: 'GitHub CLI 설치', kind: 'run', argv: [brew, 'install', 'gh'], command: 'brew install gh' },
    ghLogin: { label: 'GitHub 로그인', kind: 'terminal', command: 'gh auth login --hostname github.com --git-protocol https --web && gh auth setup-git\n# 화면에 나온 8자리 코드를 복사 → 브라우저에서 붙여 넣고 회사 GitHub 계정으로 승인한다' },
    ghSetupGit: { label: 'git 에 GitHub 로그인 연결', kind: 'run', argv: ['gh', 'auth', 'setup-git'], command: 'gh auth setup-git' },
    gitIdentity: { label: 'GitHub 계정으로 이름 설정', kind: 'run', argv: ['/bin/sh', '-c', 'u=$(gh api user) || exit 1; l=$(printf %s "$u" | /usr/bin/python3 -c "import json,sys;d=json.load(sys.stdin);print(d[\'login\'])"); n=$(printf %s "$u" | /usr/bin/python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get(\'name\') or d[\'login\'])"); i=$(printf %s "$u" | /usr/bin/python3 -c "import json,sys;print(json.load(sys.stdin)[\'id\'])"); git config --global user.name "$n" && git config --global user.email "$i+$l@users.noreply.github.com" && echo "이름: $n"'], command: 'git config --global user.name "<이름>" && git config --global user.email "<GitHub noreply 메일>"' },
    claudeLogin: { label: '터미널에서 로그인', kind: 'terminal', command: `${q(settings.claude)}\n# 로그인 화면이 나오면 안내대로 로그인한 뒤 /exit 로 나온다` },
  };
}

function act(table, ...ids) {
  return ids.map((id) => Object.assign({ id }, table[id]));
}

async function checkPython(settings, table) {
  const r = await sh(settings.python, ['--version']);
  const m = /(\d+)\.(\d+)/.exec(r.out + r.err);
  const ok = r.code === 0 && m && (Number(m[1]) > 3 || (Number(m[1]) === 3 && Number(m[2]) >= 9));
  return {
    id: 'python', title: 'Python 3.9 이상', need: '필수', status: ok ? 'OK' : 'FAIL',
    detail: r.code === 0 ? lastLine(r.out + r.err) : '없음',
    fix: ok ? '' : 'macOS Command Line Tools 에 들어 있다. 설치 창이 뜨면 「설치」를 누른다',
    actions: ok ? [] : act(table, 'clt'),
  };
}

async function checkBrew(table) {
  const brew = brewPath();
  return {
    id: 'brew', title: 'Homebrew', need: 'adb·Node 설치용', status: brew ? 'OK' : 'WARN', detail: brew || '없음',
    fix: brew ? '' : '터미널에서 설치한다. 맥 로그인 비밀번호를 묻는다. 끝나고 「다시 점검」',
    actions: brew ? [] : act(table, 'brew'),
  };
}

async function checkXcode(settings, table) {
  const out = [];
  const dir = settings.developerDir;
  const others = fs.existsSync('/Applications') ? fs.readdirSync('/Applications').filter((n) => /^Xcode.*\.app$/.test(n)) : [];
  if (!fs.existsSync(dir)) {
    const alt = others.map((n) => `/Applications/${n}/Contents/Developer`).find((p) => fs.existsSync(p));
    out.push({
      id: 'xcode', title: 'Xcode', need: 'iOS', status: 'FAIL', detail: `${dir} 없음${others.length ? ` · 설치된 것: ${others.join(', ')}` : ''}`,
      fix: alt ? `설정의 Xcode 경로를 ${alt} 로 바꾼다` : 'App Store 에서 Xcode 를 설치하고 한 번 실행한다(용량이 크다)',
      actions: alt ? [{ id: 'useXcode', label: '이 Xcode 쓰기', kind: 'apply', settings: { developerDir: alt } }] : act(table, 'xcode'),
    });
    return out;
  }
  const v = await sh('xcrun', ['devicectl', '--version']);
  const first = await sh('xcodebuild', ['-checkFirstLaunchStatus']);
  out.push({
    id: 'xcode', title: 'Xcode', need: 'iOS', status: v.code === 0 && first.code === 0 ? 'OK' : (v.code === 0 ? 'WARN' : 'FAIL'),
    detail: v.code === 0 ? `${dir} · devicectl ${lastLine(v.out)}` : lastLine(v.err).slice(-160),
    fix: v.code !== 0 ? 'Xcode 를 한 번 실행해 추가 구성요소 설치를 끝낸다' : (first.code !== 0 ? '추가 구성요소 설치가 안 끝났다. 터미널에서 설치한다(비밀번호를 묻는다)' : ''),
    actions: v.code !== 0 || first.code !== 0 ? act(table, 'xcodeFirst') : [],
  });
  if (v.code === 0) {
    const cap = await sh('xcrun', ['devicectl', 'device', 'capture', 'screenshot', '--help']);
    out.push({
      id: 'iosCapture', title: 'iOS 화면 캡처', need: 'iOS', status: cap.code === 0 ? 'OK' : 'FAIL',
      detail: cap.code === 0 ? '사용 가능' : '이 Xcode 의 devicectl 에 capture screenshot 이 없다',
      fix: cap.code === 0 ? '' : 'Xcode 를 최신으로 올린다(App Store → 업데이트)', actions: cap.code === 0 ? [] : act(table, 'xcode'),
    });
  }
  return out;
}

async function checkAdb(table) {
  const r = await sh('adb', ['version']);
  const ok = r.code === 0;
  return {
    id: 'adb', title: 'adb (Android Platform Tools)', need: 'Android', status: ok ? 'OK' : 'FAIL',
    detail: ok ? (r.out.split('\n')[0] || '').trim() : '없음',
    fix: ok ? '' : (brewPath() ? '「adb 설치」를 누른다' : '먼저 Homebrew 를 설치한다'),
    actions: ok ? [] : act(table, 'adb'),
  };
}

async function checkClaude(settings, table) {
  const v = await sh(settings.claude, ['--version']);
  if (v.code !== 0) {
    return [{
      id: 'claude', title: 'Claude Code CLI', need: 'Claude 기능', status: 'WARN', detail: `${settings.claude} 실행 안 됨`,
      fix: '설치한 뒤 「다시 점검」. 이미 설치했는데 이렇게 나오면 터미널의 `which claude` 결과를 아래 설정의 Claude CLI 에 넣는다',
      actions: act(table, 'claude'),
    }];
  }
  const out = [{ id: 'claude', title: 'Claude Code CLI', need: 'Claude 기능', status: 'OK', detail: lastLine(v.out), fix: '', actions: [] }];
  const a = await sh(settings.claude, ['auth', 'status'], { timeout: 20000 });
  let loggedIn = null;
  try { loggedIn = JSON.parse(a.out).loggedIn === true; } catch { /* 옛 버전은 auth status 가 없다 */ }
  out.push({
    id: 'claudeLogin', title: 'Claude 로그인', need: 'Claude 기능',
    status: loggedIn ? 'OK' : (loggedIn === false ? 'WARN' : 'WARN'),
    detail: loggedIn ? '로그인됨' : (loggedIn === false ? '로그인 안 됨' : '확인 못 함(CLI 버전이 낮을 수 있다)'),
    fix: loggedIn ? '' : '터미널에서 claude 를 실행해 각자 계정으로 로그인한다',
    actions: loggedIn ? [] : act(table, 'claudeLogin'),
  });
  return out;
}

async function checkNode(table) {
  const r = await sh('node', ['--version']);
  const major = r.code === 0 ? Number((r.out.trim().replace(/^v/, '').split('.')[0]) || 0) : 0;
  return {
    id: 'node', title: 'Node.js 22 이상', need: '선택 · 계정 상태·서버 시간 케이스', status: major >= 22 ? 'OK' : 'WARN',
    detail: r.code === 0 ? r.out.trim() : '없음', fix: major >= 22 ? '' : '화면 확인·되감기만 돌리면 없어도 된다',
    actions: major >= 22 ? [] : act(table, r.code === 0 ? 'nodeUp' : 'node'),
  };
}

async function checkChrome(table) {
  const ok = fs.existsSync('/Applications/Google Chrome.app');
  return {
    id: 'chrome', title: 'Google Chrome', need: '선택 · 계정 상태·서버 시간 케이스', status: ok ? 'OK' : 'WARN',
    detail: ok ? '설치됨' : '없음', fix: ok ? '' : '화면 확인·되감기만 돌리면 없어도 된다', actions: ok ? [] : act(table, 'chrome'),
  };
}

/** 시나리오 공유(git·GitHub) — 원격이 없을 때도 이 컴퓨터 안에서는 쓸 수 있으므로 필수는 git 하나다. */
async function checkGit(table) {
  const out = [];
  const g = await sh('git', ['--version']);
  out.push({
    id: 'git', title: 'git', need: '시나리오 공유', status: g.code === 0 ? 'OK' : 'FAIL', detail: g.code === 0 ? g.out.trim() : '없음',
    fix: g.code === 0 ? '' : 'macOS Command Line Tools 에 들어 있다', actions: g.code === 0 ? [] : act(table, 'clt'),
  });
  const gh = await sh('gh', ['--version']);
  if (gh.code !== 0) {
    out.push({ id: 'gh', title: 'GitHub CLI (gh)', need: '시나리오 공유', status: 'WARN', detail: '없음', fix: 'GitHub 로그인을 브라우저로 할 수 있게 해 준다', actions: act(table, 'gh') });
    return out;
  }
  out.push({ id: 'gh', title: 'GitHub CLI (gh)', need: '시나리오 공유', status: 'OK', detail: gh.out.split('\n')[0].trim(), fix: '', actions: [] });
  const auth = await sh('gh', ['auth', 'status', '--hostname', 'github.com']);
  if (auth.code !== 0) {
    out.push({ id: 'ghLogin', title: 'GitHub 로그인', need: '시나리오 공유', status: 'WARN', detail: '로그인 안 됨', fix: '터미널 창이 열리면 Enter → 나온 코드를 브라우저에 붙여 넣고 승인한다', actions: act(table, 'ghLogin') });
    return out;
  }
  out.push({ id: 'ghLogin', title: 'GitHub 로그인', need: '시나리오 공유', status: 'OK', detail: '로그인됨', fix: '', actions: [] });
  const helper = await sh('git', ['config', '--global', '--get-all', 'credential.https://github.com.helper']);
  const linked = /gh(\s|$)|auth git-credential/.test(helper.out);
  out.push({
    id: 'ghSetupGit', title: 'git ↔ GitHub 로그인 연결', need: '시나리오 공유', status: linked ? 'OK' : 'WARN',
    detail: linked ? '연결됨' : '안 됨', fix: linked ? '' : 'git 이 올리기·받기 때 gh 로그인을 쓰게 한다', actions: linked ? [] : act(table, 'ghSetupGit'),
  });
  const name = await sh('git', ['config', '--global', 'user.name']);
  const mail = await sh('git', ['config', '--global', 'user.email']);
  const named = name.out.trim() && mail.out.trim();
  out.push({
    id: 'gitIdentity', title: 'git 사용자 이름', need: '시나리오 공유', status: named ? 'OK' : 'WARN',
    detail: named ? name.out.trim() : '없음', fix: named ? '' : '누가 바꿨는지 기록에 남는 이름이다. GitHub 계정 이름으로 채운다', actions: named ? [] : act(table, 'gitIdentity'),
  });
  return out;
}

/** 기기에 게임(DEBUG 빌드)이 깔렸는지. 기기가 저장돼 있을 때만 본다. */
async function checkGameApps() {
  const devices = kit.readDevices();
  const out = [];
  const ios = (devices.ios || {}).device;
  if (ios) {
    const tmp = path.join(os.tmpdir(), `qa-apps-${process.pid}-${Date.now()}.json`);
    const r = await sh('xcrun', ['devicectl', 'device', 'info', 'apps', '--device', ios, '--bundle-id', BUNDLE, '--json-output', tmp], { timeout: 40000 });
    const apps = (((kit.readJson(tmp, {}) || {}).result || {}).apps) || [];
    fs.rmSync(tmp, { force: true });
    const ok = r.code === 0 && apps.length > 0;
    out.push({
      id: 'gameIos', title: 'iOS 기기의 게임 앱', need: 'iOS', status: ok ? 'OK' : (r.code === 0 ? 'FAIL' : 'WARN'),
      detail: ok ? `${apps[0].name || BUNDLE} ${apps[0].bundleVersion || ''}`.trim() : (r.code === 0 ? `${BUNDLE} 없음` : `기기 조회 실패: ${lastLine(r.err).slice(-120)}`),
      fix: ok ? '' : (r.code === 0 ? 'CI(Cookiepot)의 DEBUG(InternalBuild) 빌드를 설치한다. 릴리즈 빌드에는 자동화 연결이 없다' : '기기가 잠겨 있거나 연결이 끊겼다. 잠금을 풀고 「다시 점검」'),
      actions: [],
    });
  }
  const aos = (devices.aos || {}).device;
  if (aos) {
    const r = await sh('adb', ['-s', aos, 'shell', 'pm', 'path', PACKAGE]);
    const ok = r.code === 0 && r.out.includes('package:');
    out.push({
      id: 'gameAos', title: 'Android 기기의 게임 앱', need: 'Android', status: ok ? 'OK' : (r.code === 0 || /not found|no devices/.test(r.err) ? 'FAIL' : 'WARN'),
      detail: ok ? `${PACKAGE} 설치됨` : (r.code === 0 ? `${PACKAGE} 없음` : lastLine(r.err).slice(-120)),
      fix: ok ? '' : 'CI(Cookiepot)의 DEBUG 빌드 APK 를 설치한다. 기기가 unauthorized 면 기기 화면의 「USB 디버깅 허용」을 누른다',
      actions: [],
    });
  }
  if (!ios && !aos) {
    out.push({ id: 'gameNone', title: '기기의 게임 앱', need: '기기', status: 'WARN', detail: '고른 기기가 없다', fix: '기기를 케이블로 연결한다. 「기기」 탭에서 자동으로 고른다', actions: [] });
  }
  return out;
}

async function runChecks() {
  const settings = kit.readSettings();
  const table = actionTable(settings);
  const groups = await Promise.all([
    checkPython(settings, table), checkBrew(table), checkXcode(settings, table), checkAdb(table),
    checkClaude(settings, table), checkGit(table), checkGameApps(), checkNode(table), checkChrome(table),
  ]);
  return groups.flat().map((c) => Object.assign(c, { actions: c.actions.map((a) => Object.assign({}, a, { argv: undefined })) }));
}

function findAction(actionId) {
  const settings = kit.readSettings();
  const a = actionTable(settings)[actionId];
  if (!a) throw new Error(`모르는 동작: ${actionId}`);
  return a;
}

/** 터미널 창을 열어 명령을 실행한다. .command 파일을 여는 방식이라 자동화 권한을 묻지 않는다. */
function openInTerminal(command) {
  const file = path.join(os.tmpdir(), `qa-setup-${Date.now()}.command`);
  fs.writeFileSync(file, `#!/bin/zsh\nexport PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"\n${command}\necho\necho "끝났습니다. QA 앱에서 「다시 점검」을 누르세요. 이 창은 닫아도 됩니다."\n`, { mode: 0o755 });
  return new Promise((resolve, reject) => execFile('open', ['-a', 'Terminal', file], (err) => (err ? reject(err) : resolve(file))));
}

/** 앱 안에서 설치 명령을 돌린다. 줄마다 onLine, 끝나면 onExit(code). */
function runAction(actionId, onLine, onExit) {
  const a = findAction(actionId);
  if (a.kind !== 'run') throw new Error('앱 안에서 실행하는 동작이 아니다');
  const child = spawn(a.argv[0], a.argv.slice(1), { env: Object.assign(kit.toolEnv(), { NONINTERACTIVE: '1', HOMEBREW_NO_ENV_HINTS: '1' }), stdio: ['ignore', 'pipe', 'pipe'] });
  const feed = (c) => String(c).split('\n').filter(Boolean).forEach(onLine);
  child.stdout.on('data', feed);
  child.stderr.on('data', feed);
  child.on('close', (code) => onExit(code));
  child.on('error', (err) => { onLine(String(err.message)); onExit(-1); });
  return child;
}

module.exports = { runChecks, findAction, openInTerminal, runAction, actionTable };
