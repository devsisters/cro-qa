'use strict';
const test = require('node:test');
const assert = require('node:assert');
const kit = require('../lib/kit');

test('케이스·실행 폴더 이름으로 키트 밖 경로를 열 수 없다', () => {
  for (const bad of ['../x.json', '/etc/passwd', 'a/b.json', 'x.txt', '']) assert.throws(() => kit.readCase(bad), /올바르지 않다/, bad);
  for (const bad of ['..', '../runs', 'a/b', '']) assert.throws(() => kit.runDir(bad), /올바르지 않다/, bad);
});

test('케이스 목록은 되감기와 아웃게임을 구분한다', () => {
  // 팀 저장소의 묶음은 바뀌므로 임시 시나리오 폴더로 본다
  const fs = require('fs');
  const os = require('os');
  const path = require('path');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qa-cases-'));
  fs.mkdirSync(path.join(dir, 'cases'));
  fs.writeFileSync(path.join(dir, 'cases', 'rw.json'), JSON.stringify({ kind: 'rewind', cases: [{}] }));
  fs.writeFileSync(path.join(dir, 'cases', 'og.json'), JSON.stringify({ suite: 'og', cases: [{}, {}] }));
  const real = kit.readSettings;
  kit.readSettings = () => Object.assign(real(), { scenarioDir: dir });
  try {
    const list = kit.listCases();
    assert.ok(list.some((x) => x.file === 'rw.json' && x.kind === 'rewind'));
    assert.ok(list.some((x) => x.file === 'og.json' && x.kind === 'outgame' && x.count === 2));
  } finally {
    kit.readSettings = real;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('설정은 정해진 키만 받는다', () => {
  const s = kit.readSettings();
  assert.ok(s.python && s.claude && s.developerDir);
});

test('iOS 기기 목록은 실기기 iOS 만, 터널 연결된 것을 연결로 본다', () => {
  const json = { result: { devices: [
    { identifier: 'A', deviceProperties: { name: '아이폰', osVersionNumber: '18.1' }, hardwareProperties: { reality: 'physical', platform: 'iOS', deviceType: 'iPhone' }, connectionProperties: { tunnelState: 'unavailable' } },
    { identifier: 'B', deviceProperties: { name: 'iPad (6)' }, hardwareProperties: { reality: 'physical', platform: 'iOS', deviceType: 'iPad' }, connectionProperties: { tunnelState: 'connected' } },
    { identifier: 'C', deviceProperties: { name: '시계' }, hardwareProperties: { reality: 'physical', platform: 'watchOS' }, connectionProperties: { tunnelState: 'connected' } },
    { identifier: 'D', deviceProperties: { name: '시뮬' }, hardwareProperties: { reality: 'virtual', platform: 'iOS' }, connectionProperties: {} },
  ] } };
  const list = kit.parseIosDevices(json);
  assert.deepStrictEqual(list.map((d) => [d.id, d.connected]), [['A', false], ['B', true]]);
  assert.deepStrictEqual(kit.parseIosDevices(null), []);
});

test('adb 목록은 state 가 device 인 것만 연결로 본다', () => {
  const text = 'List of devices attached\nR3CW909TLSM            device usb:1 product:e1s model:SM_S921B device:e1s transport_id:20\nZX1 unauthorized usb:2 transport_id:3\n\n';
  const list = kit.parseAdbDevices(text);
  assert.deepStrictEqual(list.map((d) => [d.id, d.name, d.connected]), [['R3CW909TLSM', 'SM S921B', true], ['ZX1', 'ZX1', false]]);
});
