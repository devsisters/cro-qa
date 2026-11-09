'use strict';
// 팀 저장소 대신 로컬 bare 저장소로 두 사람(A·B)의 받기·올리기·충돌을 흉내 낸다
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const kit = require('../lib/kit');
const scen = require('../lib/git');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'qa-scen-'));
const bare = path.join(tmp, 'remote.git');
let current = '';
const realRead = kit.readSettings;
const realWrite = kit.writeSettings;
kit.readSettings = () => Object.assign(realRead(), { scenarioDir: current, scenarioRepo: `file://${bare}` });
kit.writeSettings = (s) => { if (s.scenarioDir !== undefined) current = s.scenarioDir; return kit.readSettings(); };
Object.assign(process.env, { GIT_AUTHOR_NAME: 't', GIT_AUTHOR_EMAIL: 't@t', GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@t' });
test.after(() => { kit.readSettings = realRead; kit.writeSettings = realWrite; fs.rmSync(tmp, { recursive: true, force: true }); });

const caseOf = (dir) => JSON.parse(fs.readFileSync(path.join(dir, 'cases', 'sample-rewind.json'), 'utf8'));
const edit = (dir, fn) => {
  const j = caseOf(dir);
  fn(j);
  fs.writeFileSync(path.join(dir, 'cases', 'sample-rewind.json'), JSON.stringify(j, null, 2) + '\n');
};

test('주소 정리', () => {
  assert.strictEqual(scen.normalizeRemote('devsisters/cro-qa'), 'https://github.com/devsisters/cro-qa.git');
  assert.throws(() => scen.normalizeRemote('rm -rf /'), /올바르지 않다/);
});

test('빈 팀 저장소 받기 → 샘플로 시작 → 다른 사람 받기 → 주고받기 → 충돌은 되돌리고 알림', async () => {
  execFileSync('git', ['init', '--bare', '-b', 'main', bare]);
  const A = path.join(tmp, 'A', 'cro-qa');
  const B = path.join(tmp, 'B', 'cro-qa');

  let st = await scen.connect(A);
  assert.match(st.note, /빈 저장소/);
  assert.strictEqual(current, A);
  assert.strictEqual(kit.casesDir(), path.join(A, 'cases'));
  assert.ok(caseOf(A).cases.length > 0);
  assert.ok(st.ready && !st.upstream && st.branch === 'main');
  st = await scen.pull();                       // 원격이 비어 있어도 받기가 실패하지 않는다
  assert.match(st.note, /아직 올라간 것이 없다/);
  st = await scen.push(null);
  assert.ok(st.upstream && st.ahead === 0);

  // 이미 받은 폴더를 다시 고르면 그대로 쓴다
  st = await scen.connect(A);
  assert.match(st.note, /받았다/);

  current = '';
  st = await scen.connect(B);
  assert.strictEqual(current, B);
  assert.deepStrictEqual(caseOf(B), caseOf(A));

  // B 가 고쳐 올리고, A 는 다른 파일을 올리면서 B 것을 받는다
  edit(B, (j) => { j.cases[0].plays = 9; });
  await assert.rejects(scen.push(''), /한 줄/);
  await scen.push('B 판 수');
  current = A;
  fs.writeFileSync(path.join(A, 'docs', 'a.md'), '# A 문서\n');
  await scen.push('A 문서');
  assert.strictEqual(caseOf(A).cases[0].plays, 9);

  // 같은 줄을 둘이 고치면 충돌 — 받기 전 상태로 돌아가야 한다
  current = B;
  await scen.pull();
  edit(B, (j) => { j.note = 'B-변경'; });
  await scen.push('B note');
  current = A;
  edit(A, (j) => { j.note = 'A-변경'; });
  await assert.rejects(scen.push('A note'), /충돌/);
  assert.ok(!fs.existsSync(path.join(A, '.git', 'rebase-merge')), 'rebase 가 남아 있지 않다');
  assert.strictEqual(caseOf(A).note, 'A-변경');

  // 다른 저장소 폴더는 거부한다
  const other = path.join(tmp, 'other');
  fs.mkdirSync(other);
  execFileSync('git', ['init', '-q', other]);
  await assert.rejects(scen.connect(other), /다른 저장소/);
});

test('받은 것에 앱(키트) 파일이 있으면 다시 시작이 필요하다고 알리고, 의존성이 바뀌었으면 따로 알린다', async () => {
  // 앞 시험이 남긴 충돌 상태와 섞이지 않게 새로 받은 두 폴더로 한다 — A 는 앱을 고치는 사람, B 는 QA
  const A = path.join(tmp, 'C', 'cro-qa');
  const B = path.join(tmp, 'D', 'cro-qa');
  execFileSync('git', ['clone', '-q', bare, A]);
  execFileSync('git', ['clone', '-q', bare, B]);
  const realKit = kit.P.kit;
  const commitIn = (dir, file, text) => {
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    fs.writeFileSync(path.join(dir, file), text);
    execFileSync('git', ['-C', dir, 'add', '-A']);
    execFileSync('git', ['-C', dir, 'commit', '-q', '-m', file]);
    execFileSync('git', ['-C', dir, 'push', '-q']);
  };
  try {
    kit.P.kit = path.join(B, 'kit');
    assert.strictEqual(scen.kitPathIn(B), 'kit');
    commitIn(A, 'kit/app/renderer/new.js', '1\n');
    current = B;
    let st = await scen.pull();
    assert.strictEqual(st.appUpdated, true);
    assert.strictEqual(st.depsUpdated, false);
    commitIn(A, 'kit/app/package-lock.json', '{}\n');
    st = await scen.pull();
    assert.strictEqual(st.depsUpdated, true);
    commitIn(A, 'cases/other.json', '{}\n');
    st = await scen.pull();
    assert.ok(!st.appUpdated, '케이스만 받으면 다시 시작할 필요가 없다');
  } finally {
    kit.P.kit = realKit;
  }
});
