// 되감기 케이스의 기본값·검사·프리셋 적용. 범위는 tools/rewind_runner.py 의 validate 와 같다(정본은 그쪽).
'use strict';

const TRIGGERS = ['interval', 'afterRevive', 'afterBonusReturn'];
const INPUT_RANGES = {
  actionsPerSec: [0, 10],
  slideRatio: [0, 1],
  doubleJumpRatio: [0, 1],
  abilityEverySec: [0, 600],
  mistakeRatio: [0, 1],
  timingOffset: [-0.3, 0.3],
};

function defaultCase(id) {
  return {
    id: id || 'RW-01',
    title: '',
    map: 'aaaa0001',
    plays: 2,
    cards: { cookie1: 'random', cookie2: 'random', pet: 'random', treasures: ['random', 'random', 'random'] },
    target: 'latest',
    triggers: [{ type: 'interval', delaySec: 10, count: 2 }],
    input: { mode: 'random', actionsPerSec: 0.8, slideRatio: 0.3, doubleJumpRatio: 0.4, abilityEverySec: 8, rescue: true, relay: true },
    timeoutSec: 300,
  };
}

/** 옛 케이스(필드 없음)를 열 때 빈 칸을 기본값으로 채운다. 원래 있던 값은 그대로 둔다. */
function normalizeCase(c) {
  const d = defaultCase(c && c.id);
  const out = Object.assign({}, d, c || {});
  out.cards = Object.assign({}, d.cards, (c && c.cards) || {});
  if (!Array.isArray(out.cards.treasures) || out.cards.treasures.length !== 3) out.cards.treasures = d.cards.treasures.slice();
  if (!Array.isArray(out.triggers)) out.triggers = d.triggers.slice();
  if (c && c.input === undefined) out.input = { mode: 'none' };
  return out;
}

function isCard(v) {
  return v === 'random' || Number.isInteger(v);
}

/** 오류 목록을 돌려준다. 비면 통과. */
function validateCase(c) {
  const errs = [];
  const where = `case ${c.id || '?'}`;
  if (!c.id) errs.push(`${where}: id 가 없다`);
  if (typeof c.map !== 'string' || !c.map) errs.push(`${where}: map(테스트 맵 이름)이 없다`);
  if (!Number.isInteger(c.plays) || c.plays < 1) errs.push(`${where}: plays 는 1 이상 정수`);
  const cards = c.cards || {};
  for (const key of ['cookie1', 'cookie2', 'pet']) {
    const v = cards[key] === undefined ? 'random' : cards[key];
    if (!isCard(v)) errs.push(`${where}: cards.${key} 는 카드 id 또는 "random"${typeof v === 'string' ? `(「${v}」 이름을 찾지 못했다 — 기기에서 카드 목록을 받거나 목록에서 고른다)` : ''}`);
    else if (v === 0 && key !== 'cookie2') errs.push(`${where}: cards.${key} 는 비울 수 없다(「없음」은 쿠키2·보물만)`);
  }
  const tr = cards.treasures === undefined ? ['random', 'random', 'random'] : cards.treasures;
  if (!Array.isArray(tr) || tr.length !== 3 || tr.some((v) => !isCard(v))) {
    errs.push(`${where}: cards.treasures 는 3칸(카드 id · 0(빈칸) · "random")`);
  }
  if (!Array.isArray(c.triggers)) errs.push(`${where}: triggers 는 목록(되감기 없이 달리기만 하려면 비워 둔다)`);
  else {
    for (const t of c.triggers) {
      if (!TRIGGERS.includes(t.type)) errs.push(`${where}: trigger type 은 ${TRIGGERS.join(' · ')} 중 하나`);
      if (!Number.isInteger(t.count) || t.count < 1) errs.push(`${where}: trigger count 는 1 이상 정수`);
      if (typeof (t.delaySec ?? 0) !== 'number' || (t.delaySec ?? 0) < 0) errs.push(`${where}: trigger delaySec 는 0 이상`);
      if (t.point !== undefined && t.point !== null && (!Number.isInteger(t.point) || t.point < -1)) errs.push(`${where}: trigger point 는 0(기본값)·1(5초 전)·2(10초 전)·3(15초 전)`);
    }
  }
  if (!['latest', 'oldest'].includes(c.target || 'latest')) errs.push(`${where}: target 은 latest 또는 oldest`);
  if (c.timeoutSec !== undefined && (!Number.isInteger(c.timeoutSec) || c.timeoutSec < 30)) errs.push(`${where}: timeoutSec 는 30 이상 정수`);
  const inp = c.input;
  if (inp !== undefined && inp !== null) {
    if (typeof inp !== 'object' || !['random', 'smart', 'none', 'record', 'replay'].includes(inp.mode || 'random')) errs.push(`${where}: input.mode 는 random · smart · none · record · replay 중 하나`);
    else {
      for (const [key, [low, high]] of Object.entries(INPUT_RANGES)) {
        const v = inp[key];
        if (v !== undefined && (typeof v !== 'number' || v < low || v > high)) errs.push(`${where}: input.${key} 는 ${low}~${high}`);
      }
      for (const flag of ['rescue', 'relay']) if (flag in inp && typeof inp[flag] !== 'boolean') errs.push(`${where}: input.${flag} 는 true/false`);
      if (inp.seed !== undefined && inp.seed !== null && (!Number.isInteger(inp.seed) || inp.seed < 0)) errs.push(`${where}: input.seed 는 0 이상 정수(비우면 매번 새 시드)`);
    }
  }
  if (c.seed !== undefined && c.seed !== null && (!Number.isInteger(c.seed) || c.seed < 0)) errs.push(`${where}: seed 는 0 이상 정수(비우면 매번 새 시드)`);
  return errs;
}

function validateSuite(suite) {
  const errs = [];
  if (!suite || suite.kind !== 'rewind') errs.push('kind 가 "rewind" 가 아니다');
  const cases = (suite && suite.cases) || [];
  if (!cases.length) errs.push('cases 가 비었다');
  const seen = new Set();
  for (const c of cases) {
    if (seen.has(c.id)) errs.push(`case ${c.id}: id 중복`);
    seen.add(c.id);
    errs.push(...validateCase(c));
  }
  return errs;
}

/** 프리셋(input·plays·timeoutSec·target)을 케이스에 덮어쓴다. 맵·카드·트리거는 건드리지 않는다. */
function applyPreset(c, preset) {
  const out = JSON.parse(JSON.stringify(c));
  for (const key of ['plays', 'timeoutSec', 'target']) if (preset[key] !== undefined) out[key] = preset[key];
  if (preset.input) out.input = JSON.parse(JSON.stringify(preset.input));
  return out;
}

function presetFromCase(c) {
  // 시드는 케이스마다 정하는 값이라 프리셋에 넣지 않는다
  const input = JSON.parse(JSON.stringify(c.input || { mode: 'none' }));
  delete input.seed;
  return { input, plays: c.plays, timeoutSec: c.timeoutSec, target: c.target || 'latest' };
}

/** Claude 응답에서 첫 JSON 객체를 꺼낸다(코드 블록·앞뒤 설명 허용). */
function extractJsonObject(text) {
  const fenced = /```(?:json)?\s*([\s\S]*?)```/.exec(text);
  const body = fenced ? fenced[1] : text;
  const start = body.indexOf('{');
  if (start < 0) throw new Error('JSON 객체가 없다');
  let depth = 0;
  let inString = false;
  for (let i = start; i < body.length; i++) {
    const ch = body[i];
    if (inString) {
      if (ch === '\\') i++;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === '{') depth++;
    else if (ch === '}' && --depth === 0) return JSON.parse(body.slice(start, i + 1));
  }
  throw new Error('JSON 객체가 닫히지 않았다');
}

const caseModel = { TRIGGERS, INPUT_RANGES, defaultCase, normalizeCase, validateCase, validateSuite, applyPreset, presetFromCase, extractJsonObject };
// 메인 프로세스(require)와 화면(<script>) 양쪽에서 쓴다
if (typeof module !== 'undefined' && module.exports) module.exports = caseModel;
else globalThis.caseModel = caseModel;
