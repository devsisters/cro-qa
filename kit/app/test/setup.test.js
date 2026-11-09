'use strict';
const test = require('node:test');
const assert = require('node:assert');
const kit = require('../lib/kit');
const setup = require('../lib/setup');

test('도구가 없으면 FAIL·WARN 과 고치는 동작을 준다', async (t) => {
  const realSettings = kit.readSettings;
  const realEnv = kit.toolEnv;
  const realDevices = kit.readDevices;
  kit.readSettings = () => ({ python: '/nope/python3', claude: '/nope/claude', developerDir: '/nope/Xcode.app/Contents/Developer' });
  kit.toolEnv = () => Object.assign({}, process.env, { PATH: '/usr/bin:/bin', DEVELOPER_DIR: '/nope' });
  kit.readDevices = () => ({ ios: { device: '' }, aos: { device: '' } });
  t.after(() => { kit.readSettings = realSettings; kit.toolEnv = realEnv; kit.readDevices = realDevices; });
  const rows = await setup.runChecks();
  const by = Object.fromEntries(rows.map((r) => [r.id, r]));
  assert.strictEqual(by.python.status, 'FAIL');
  assert.deepStrictEqual(by.python.actions.map((a) => a.id), ['clt']);
  assert.strictEqual(by.xcode.status, 'FAIL');
  assert.ok(by.xcode.actions.length >= 1);
  assert.strictEqual(by.adb.status, 'FAIL');
  assert.strictEqual(by.claude.status, 'WARN');
  assert.strictEqual(by.claude.actions[0].kind, 'terminal');
  assert.strictEqual(by.gameNone.status, 'WARN');
  for (const r of rows) for (const a of r.actions) assert.strictEqual(a.argv, undefined, '화면에 실행 인자를 넘기지 않는다');
});

test('동작 표에 없는 id 는 거부한다', () => {
  assert.throws(() => setup.findAction('rm -rf'), /모르는 동작/);
  assert.strictEqual(setup.findAction('adb').kind, 'run');
  assert.strictEqual(setup.findAction('brew').kind, 'terminal');
});
