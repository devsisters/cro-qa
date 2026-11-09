'use strict';
const test = require('node:test');
const assert = require('node:assert');
const claude = require('../lib/claude');

test('거절된 명령은 「이번만」이면 그 명령 그대로, 「항상」이면 같은 도구의 모든 인자를 허용한다', () => {
  const bash = { tool_name: 'Bash', tool_input: { command: 'python3 tools/scenario_capture.py "../scenarios/a.json" --platform aos' } };
  assert.strictEqual(claude.ruleFor(bash, false), 'Bash(python3 tools/scenario_capture.py "../scenarios/a.json" --platform aos)');
  assert.strictEqual(claude.ruleFor(bash, true), 'Bash(python3 tools/scenario_capture.py:*)');
  assert.strictEqual(claude.ruleFor({ tool_name: 'Bash', tool_input: { command: 'adb shell ls' } }, true), 'Bash(adb:*)');
  assert.strictEqual(claude.ruleFor({ tool_name: 'Write', tool_input: { file_path: '/x/y.json' } }, false), 'Write(/x/y.json)');
  assert.strictEqual(claude.ruleFor({ tool_name: 'WebFetch', tool_input: {} }, true), 'WebFetch');
});

test('키트 도구는 상대 경로·전체 경로 모두 기본 허용이다', () => {
  assert.ok(claude.CHAT_TOOLS.includes('Bash(python3 tools/*)'));
  assert.ok(claude.CHAT_TOOLS.some((r) => /^Bash\(python3 \/.+\/tools\/\*\)$/.test(r)));
});
