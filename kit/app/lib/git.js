// 시나리오 저장소 — 팀 저장소(기본 devsisters/cro-qa)를 받아(clone) 두고 「받기」·「올리기」만 한다.
// 비개발자가 쓰므로 충돌은 자동으로 합치지 않고 원래 상태로 되돌린 뒤 알린다. 인증은 gh(GitHub CLI) 로그인을 쓴다.
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');
const kit = require('./kit');

const GITIGNORE = 'runs/\n.DS_Store\n*.tmp-*\n';
const README = `# QA 시나리오

QA 자동화 키트의 케이스·문서를 공유하는 저장소다. QA 앱(키트 app/)이 이 저장소를 받아 두고 「받기」·「올리기」로 주고받는다.

| 폴더 | 내용 |
|---|---|
| cases/ | 케이스 묶음(JSON). \`kind: rewind\` 는 되감기, 나머지는 아웃게임 |
| docs/ | 사람이 쓰는 시나리오 문서(md) |
| presets/ | 되감기 입력 프리셋 |

실행 결과(runs/)·기기 ID·앱 설정은 각자 컴퓨터에만 둔다.
`;

function git(dir, args, { timeout = 120000 } = {}) {
  return new Promise((resolve) => {
    const env = Object.assign(kit.toolEnv(), { GIT_TERMINAL_PROMPT: '0', LC_ALL: 'C' });
    execFile('git', ['-C', dir, ...args], { env, timeout, maxBuffer: 16 * 1024 * 1024 }, (err, stdout, stderr) => {
      resolve({ code: err ? (typeof err.code === 'number' ? err.code : -1) : 0, out: String(stdout || ''), err: String(stderr || (err && err.message) || '') });
    });
  });
}

const fail = (step, r) => {
  const text = (r.err || r.out).trim();
  if (/Authentication|could not read Username|403|denied|Repository not found/i.test(text)) {
    throw new Error(`${step} 실패 — GitHub 로그인이나 저장소 권한이 필요하다(「준비」 탭). ${text.split('\n').slice(-1)[0]}`);
  }
  throw new Error(`${step} 실패: ${text.split('\n').slice(-3).join(' / ')}`);
};

function teamRepo() {
  return kit.readSettings().scenarioRepo || 'devsisters/cro-qa';
}

function normalizeRemote(remote) {
  const v = String(remote || '').trim();
  if (/^[\w.-]+\/[\w.-]+$/.test(v)) return `https://github.com/${v.replace(/\.git$/, '')}.git`;
  if (/^(https:\/\/|git@|file:\/\/)[\w.@:/-]+$/.test(v)) return v;
  throw new Error('저장소 주소가 올바르지 않다(예: devsisters/cro-qa)');
}

/** 받아 둘 기본 위치 — 문서 폴더 아래 저장소 이름 */
function defaultDir() {
  return path.join(os.homedir(), 'Documents', teamRepo().replace(/\.git$/, '').split('/').pop());
}

/** 키트(앱)가 팀 저장소 안에 들어 있으면 그 저장소 폴더 — 따로 받기 없이 이 폴더를 시나리오 저장소로 쓴다 */
function kitRepoDir() {
  let dir = kit.P.kit;
  for (let i = 0; i < 4; i += 1) {
    if (fs.existsSync(path.join(dir, '.git'))) return dir;
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return null;
}

/** 키트가 저장소 안에서 차지하는 경로(예: kit). 저장소 밖이면 null */
function kitPathIn(dir) {
  const rel = path.relative(dir, kit.P.kit);
  return rel && !rel.startsWith('..') && !path.isAbsolute(rel) ? rel.split(path.sep).join('/') : null;
}

function root() {
  const dir = kit.readSettings().scenarioDir;
  if (!dir || !path.isAbsolute(dir) || !fs.existsSync(dir)) throw new Error('팀 저장소를 아직 받지 않았다(「준비」 탭)');
  return dir;
}

/** porcelain v1 -b 출력 → 브랜치·앞섬/뒤짐·바뀐 파일 */
function parseStatus(text) {
  const lines = String(text || '').split('\n').filter(Boolean);
  const head = lines[0] && lines[0].startsWith('## ') ? lines.shift().slice(3) : '';
  const m = /^(?:No commits yet on )?([^.\s]+)(?:\.\.\.(\S+))?(?: \[(.*)\])?/.exec(head) || [];
  const track = m[3] || '';
  return {
    branch: m[1] || '',
    upstream: /gone/.test(track) ? '' : (m[2] || ''), // 빈 저장소를 받으면 원격 브랜치 없이 [gone] 으로 남는다
    ahead: Number((/ahead (\d+)/.exec(track) || [])[1] || 0),
    behind: Number((/behind (\d+)/.exec(track) || [])[1] || 0),
    changed: lines.map((l) => ({ code: l.slice(0, 2).trim(), file: l.slice(3) })),
  };
}

async function status() {
  const repo = teamRepo();
  // 앱이 팀 저장소 안에서 실행되면(QA 가 저장소를 받아 앱을 띄운 경우) 그 저장소를 그대로 쓴다
  if (!kit.readSettings().scenarioDir && kitRepoDir()) kit.writeSettings({ scenarioDir: kitRepoDir() });
  const dir = kit.readSettings().scenarioDir;
  if (!dir || !fs.existsSync(path.join(dir, '.git'))) return { ready: false, repo, defaultDir: defaultDir() };
  const st = await git(dir, ['status', '--porcelain=v1', '-b']);
  const remote = await git(dir, ['remote', 'get-url', 'origin']);
  return Object.assign({ ready: true, repo, dir, remote: remote.code === 0 ? remote.out.trim() : '' }, parseStatus(st.out));
}

const noIdentity = (r) => r.code && /tell me who you are|user\.email|user\.name/i.test(r.err);

/** 빈 저장소를 처음 받은 사람이 기본 폴더와 키트 샘플을 넣는다(이 컴퓨터에만 기록, 「올리기」 때 올라간다). */
async function seedIfEmpty(dir) {
  const head = await git(dir, ['rev-parse', '--verify', 'HEAD']);
  if (head.code === 0) return false;
  await git(dir, ['symbolic-ref', 'HEAD', 'refs/heads/main']);
  for (const sub of ['cases', 'docs', 'presets']) fs.mkdirSync(path.join(dir, sub), { recursive: true });
  fs.writeFileSync(path.join(dir, '.gitignore'), GITIGNORE);
  fs.writeFileSync(path.join(dir, 'README.md'), README);
  fs.writeFileSync(path.join(dir, 'docs', '.gitkeep'), '');
  for (const f of fs.readdirSync(kit.P.cases).filter((n) => n.endsWith('.json'))) fs.copyFileSync(path.join(kit.P.cases, f), path.join(dir, 'cases', f));
  if (fs.existsSync(kit.P.presets)) fs.copyFileSync(kit.P.presets, path.join(dir, 'presets', 'rewind-input.json'));
  let r = await git(dir, ['add', '-A']);
  if (r.code) fail('git add', r);
  r = await git(dir, ['commit', '-m', '시나리오 저장소 시작 — 키트 샘플 케이스·프리셋']);
  if (noIdentity(r)) throw new Error('git 사용자 이름이 없다. 「준비」 탭의 「git 사용자 이름」을 먼저 채운 뒤 다시 누른다');
  if (r.code) fail('첫 기록', r);
  return true;
}

/**
 * 팀 저장소를 이 컴퓨터에 준비한다. dir 를 안 주면 문서 폴더 아래 저장소 이름.
 * 이미 같은 저장소가 받아져 있으면 그 폴더를 쓰고, 없으면 받는다(clone).
 */
async function connect(dir) {
  const target = dir || defaultDir();
  if (!path.isAbsolute(target)) throw new Error('전체 경로여야 한다');
  const url = normalizeRemote(teamRepo());
  const same = (u) => u.trim().replace(/\.git$/, '').toLowerCase() === url.replace(/\.git$/, '').toLowerCase();
  if (fs.existsSync(path.join(target, '.git'))) {
    const r = await git(target, ['remote', 'get-url', 'origin']);
    if (!same(r.out)) throw new Error(`${target} 은 다른 저장소다(${r.out.trim() || '원격 없음'}). 다른 위치를 고른다`);
  } else {
    if (fs.existsSync(target) && fs.readdirSync(target).filter((n) => n !== '.DS_Store').length) throw new Error(`${target} 에 이미 다른 파일이 있다. 다른 위치를 고른다`);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const r = await git(path.dirname(target), ['clone', url, target], { timeout: 300000 });
    if (r.code) fail('받기', r);
  }
  kit.writeSettings({ scenarioDir: target });
  const seeded = await seedIfEmpty(target);
  return Object.assign(await status(), { note: seeded ? '빈 저장소라 샘플 케이스를 넣었다. 「올리기」를 누르면 팀 저장소에 올라간다' : '팀 저장소를 받았다' });
}

/** 받기 — 내 변경을 잠시 치워 두고 원격 변경을 위에 얹는다. 충돌이면 원래대로 되돌리고 알린다. */
async function pull() {
  const dir = root();
  const st = await status();
  if (!st.upstream) {
    const f = await git(dir, ['fetch', 'origin'], { timeout: 300000 });
    if (f.code) fail('받기', f);
    const remoteBranch = await git(dir, ['rev-parse', '--verify', `origin/${st.branch}`]);
    if (remoteBranch.code !== 0) return Object.assign(await status(), { note: '팀 저장소에 아직 올라간 것이 없다. 「올리기」를 누르면 올라간다' });
    await git(dir, ['branch', '--set-upstream-to', `origin/${st.branch}`]);
  }
  const before = (await git(dir, ['rev-parse', 'HEAD'])).out.trim();
  const r = await git(dir, ['pull', '--rebase', '--autostash'], { timeout: 300000 });
  if (r.code) {
    await git(dir, ['rebase', '--abort']);
    const conflicts = (r.out + r.err).split('\n').filter((l) => /CONFLICT/.test(l)).map((l) => l.replace(/^.*in /, ''));
    if (!conflicts.length) fail('받기', r);
    const e = new Error(`같은 부분을 다른 사람도 고쳤다(충돌): ${conflicts.join(', ')}. 받기 전 상태로 되돌렸다. Claude 탭에 「시나리오 저장소 충돌 해결해줘」라고 하거나 고친 사람과 맞춘다`);
    e.conflicts = conflicts;
    throw e;
  }
  // 받은 것 중에 이 앱(키트) 파일이 있으면 다시 시작해야 반영된다. 의존성이 바뀌었으면 다시 시작 전에 npm install
  const out = await status();
  const kitRel = kitPathIn(dir);
  const after = (await git(dir, ['rev-parse', 'HEAD'])).out.trim();
  if (kitRel && before && after && before !== after) {
    const files = (await git(dir, ['diff', '--name-only', before, after])).out.split('\n').filter(Boolean);
    out.appUpdated = files.some((f) => f.startsWith(`${kitRel}/app/`) || f.startsWith(`${kitRel}/tools/`));
    out.depsUpdated = files.some((f) => f === `${kitRel}/app/package.json` || f === `${kitRel}/app/package-lock.json`);
  }
  return out;
}

/** 팀 저장소에 새 기록이 있는지만 확인한다(받지는 않는다) */
async function fetch() {
  const dir = root();
  await git(dir, ['fetch', 'origin'], { timeout: 120000 });
  return status();
}

/** 올리기 — 바뀐 파일을 기록하고, 남의 변경을 먼저 받은 뒤 올린다. */
async function push(message) {
  const dir = root();
  let st = await status();
  if (st.changed.length) {
    if (!String(message || '').trim()) throw new Error('무엇을 바꿨는지 한 줄 적는다');
    let r = await git(dir, ['add', '-A']);
    if (r.code) fail('git add', r);
    r = await git(dir, ['commit', '-m', String(message).trim()]);
    if (noIdentity(r)) throw new Error('git 사용자 이름이 없다. 「준비」 탭의 「git 사용자 이름」을 먼저 채운다');
    if (r.code) fail('기록', r);
  }
  await pull();
  st = await status();
  const r = await git(dir, st.upstream ? ['push'] : ['push', '-u', 'origin', 'HEAD'], { timeout: 300000 });
  if (r.code) fail('올리기', r);
  return status();
}

module.exports = { status, connect, pull, push, fetch, kitRepoDir, kitPathIn, parseStatus, normalizeRemote, defaultDir, teamRepo };
