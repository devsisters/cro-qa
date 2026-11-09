'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const m = require('../lib/caseModel');

const KIT = path.resolve(__dirname, '..', '..');

test('기본 케이스는 검사를 통과한다', () => {
  assert.deepStrictEqual(m.validateCase(m.defaultCase('RW-01')), []);
});

test('범위 밖 수치와 잘못된 트리거를 잡는다', () => {
  const c = m.defaultCase('RW-01');
  c.input.slideRatio = 2;
  c.triggers = [{ type: 'sometimes', count: 0 }];
  c.cards.treasures = ['random'];
  const errs = m.validateCase(c);
  assert.ok(errs.some((e) => e.includes('slideRatio')));
  assert.ok(errs.some((e) => e.includes('trigger type')));
  assert.ok(errs.some((e) => e.includes('count')));
  assert.ok(errs.some((e) => e.includes('treasures')));
});

test('옛 케이스는 빈 칸만 기본값으로 채우고 원래 값은 유지한다', () => {
  const c = m.normalizeCase({ id: 'OLD', map: 'champions0001', plays: 3, triggers: [{ type: 'afterRevive', delaySec: 3, count: 1 }] });
  assert.strictEqual(c.map, 'champions0001');
  assert.strictEqual(c.plays, 3);
  assert.strictEqual(c.triggers[0].type, 'afterRevive');
  assert.deepStrictEqual(c.input, { mode: 'none' });
  assert.strictEqual(c.cards.treasures.length, 3);
});

test('프리셋은 수치만 덮어쓰고 맵·카드·트리거는 그대로 둔다', () => {
  const c = m.defaultCase('RW-01');
  c.map = 'champions0001';
  c.cards.cookie1 = 100100;
  const out = m.applyPreset(c, { plays: 5, input: { mode: 'random', actionsPerSec: 2 } });
  assert.strictEqual(out.plays, 5);
  assert.strictEqual(out.input.actionsPerSec, 2);
  assert.strictEqual(out.map, 'champions0001');
  assert.strictEqual(out.cards.cookie1, 100100);
  assert.strictEqual(c.plays, 2, '원본을 바꾸지 않는다');
  const back = m.presetFromCase(out);
  assert.strictEqual(back.plays, 5);
});

test('Claude 응답에서 JSON 객체를 꺼낸다', () => {
  assert.deepStrictEqual(m.extractJsonObject('초안입니다\n```json\n{"id":"RW-02","title":"a } b"}\n```'), { id: 'RW-02', title: 'a } b' });
  assert.deepStrictEqual(m.extractJsonObject('앞말 {"a":{"b":1}} 뒷말'), { a: { b: 1 } });
  assert.throws(() => m.extractJsonObject('없음'));
});

test('키트 프리셋과 샘플 되감기 묶음은 검사를 통과한다', () => {
  const presets = JSON.parse(fs.readFileSync(path.join(KIT, 'presets', 'rewind-input.json'), 'utf8'));
  for (const [name, p] of Object.entries(presets)) {
    assert.deepStrictEqual(m.validateCase(m.applyPreset(m.defaultCase('RW-01'), p)), [], name);
  }
  const suite = JSON.parse(fs.readFileSync(path.join(KIT, 'cases', 'sample-rewind.json'), 'utf8'));
  assert.deepStrictEqual(m.validateSuite(suite), []);
});

test('되감기 다 하면 그만두기(stopAfterSec)는 비우거나 0 이상이고 프리셋에 실린다', () => {
  const c = m.defaultCase('RW-01');
  assert.deepStrictEqual(m.validateCase(Object.assign({}, c, { stopAfterSec: 5 })), []);
  assert.deepStrictEqual(m.validateCase(Object.assign({}, c, { stopAfterSec: undefined })), []);
  assert.ok(m.validateCase(Object.assign({}, c, { stopAfterSec: -1 })).length);
  assert.strictEqual(m.applyPreset(c, m.presetFromCase(Object.assign({}, c, { stopAfterSec: 7 }))).stopAfterSec, 7);
});
