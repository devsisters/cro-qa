// Claude Code CLI 를 키트 폴더에서 띄운다. 키트의 CLAUDE.md(안전 규칙 포함)가 그대로 적용된다.
// 실행 판정에는 쓰지 않는다 — 요약·케이스 초안·진단·대화만.
'use strict';

const { spawn } = require('child_process');
const kit = require('./kit');

const READ_ONLY = ['Read', 'Glob', 'Grep'];
// 대화에서는 케이스 편집과 키트 도구 실행까지 허용한다. 키트 폴더 밖 명령은 허용 목록에 없다
const CHAT_TOOLS = ['Read', 'Glob', 'Grep', 'Edit', 'Write', 'Bash(python3 tools/*)', 'Bash(git *)', 'Bash(python3 -m unittest:*)',
  `Bash(python3 ${kit.P.kit}/tools/*)`, // 키트 도구를 전체 경로로 불러도 같은 허용으로 본다
  // 기본 기능 결과 쓰기 — 각자의 Claude 계정에 연결된 Google Sheets 로 시트를 읽고 쓴다(basic/README.md 「결과 쓰기」)
  'mcp__claude_ai_Google_Sheets__get_spreadsheet', 'mcp__claude_ai_Google_Sheets__get_values',
  'mcp__claude_ai_Google_Sheets__update_values', 'mcp__claude_ai_Google_Sheets__update_spreadsheet'];

/** 거절된 도구 호출 → 허용 규칙. 「이번만」은 그 명령 그대로, 「항상」은 같은 도구(예: python3 tools/x.py)의 모든 인자 */
function ruleFor(denial, always) {
  const name = denial.tool_name || '';
  const input = denial.tool_input || {};
  if (name === 'Bash' && input.command) {
    const cmd = String(input.command).trim();
    if (!always) return `Bash(${cmd})`;
    const words = cmd.split(/\s+/);
    const head = /^(python3?|node|npm|bash|sh)$/.test(words[0]) && words[1] ? `${words[0]} ${words[1]}` : words[0];
    return `Bash(${head}:*)`;
  }
  if ((name === 'Edit' || name === 'Write') && input.file_path) return `${name}(${input.file_path})`;
  return name;
}

/** 시나리오 폴더를 정했으면 Claude 가 그 폴더도 보고 고칠 수 있게 한다. */
function scenarioArgs() {
  const dir = kit.scenarioRoot();
  if (!dir) return [];
  return ['--add-dir', dir, '--append-system-prompt', `이 QA 앱의 케이스는 키트 cases/ 가 아니라 시나리오 저장소 ${dir} 에 있다 — 케이스 ${dir}/cases, 아웃게임 시나리오 ${dir}/scenarios(형식은 ${dir}/scenarios/README.md, 돌리기는 키트의 tools/scenario_run.py), 문서(md) ${dir}/docs, 프리셋 ${dir}/presets, 기본 기능 시트 사본·시나리오·결과 쓰기 절차 ${dir}/basic(README.md — 시나리오는 ${dir}/basic/scenarios, 돌리기는 tools/basic_run.py). 케이스·시나리오를 만들거나 고치면 그 폴더에 쓴다. 시나리오를 고칠 때 사람이 말한 교정·유의사항은 그 파일의 notes 에 남긴다. 게임 화면 정보는 트리 전체를 읽지 말고 키트의 tools/ui_find.py(화면 요약·걸러 보기)로 필요한 부분만 본다 — 트리 전체가 토큰을 가장 많이 쓴다. 이 폴더는 팀이 공유하는 git 저장소다. 충돌 해결을 부탁받으면 양쪽 변경을 모두 살려 합치고, 합친 결과를 사용자에게 보여 준 뒤 확인을 받고 커밋·올린다. 강제 push·히스토리 재작성은 하지 않는다.`];
}

function claudeCommand() {
  return kit.readSettings().claude || 'claude';
}

/** 한 번 묻고 결과 텍스트를 받는다(--output-format json). */
function ask(prompt, { tools = READ_ONLY, timeoutMs = 300000 } = {}) {
  return new Promise((resolve) => {
    const args = ['-p', prompt, '--output-format', 'json', '--allowedTools', tools.join(','), ...scenarioArgs()];
    const child = spawn(claudeCommand(), args, { cwd: kit.P.kit, env: kit.toolEnv() });
    let out = '';
    let err = '';
    const timer = setTimeout(() => child.kill('SIGTERM'), timeoutMs);
    child.stdout.on('data', (c) => { out += c; });
    child.stderr.on('data', (c) => { err += c; });
    child.on('error', (e) => {
      clearTimeout(timer);
      resolve({ ok: false, error: `Claude CLI 를 실행하지 못했다(${e.message}). 설정에서 Claude 경로를 확인한다` });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      try {
        const data = JSON.parse(out);
        if (data.is_error) resolve({ ok: false, error: String(data.result || 'Claude 오류') });
        else resolve({ ok: true, text: String(data.result || ''), sessionId: data.session_id, cost: data.total_cost_usd });
      } catch {
        resolve({ ok: false, error: (err || out || `exit ${code}`).slice(-500) });
      }
    });
  });
}

/** 대화 한 턴. stream-json 을 읽어 글자 조각을 onText 로 넘긴다. sessionId 가 있으면 이어간다. */
function chat(message, sessionId, onText, onDone, extraAllow = []) {
  // 허용: 기본 + 사람이 「항상 허용」한 것(앱 설정) + 이번 대화에서 허용한 것
  const allow = [...new Set([...CHAT_TOOLS, ...(kit.readSettings().chatAllow || []), ...extraAllow])];
  const args = ['-p', message, '--output-format', 'stream-json', '--verbose', '--allowedTools', allow.join(','), ...scenarioArgs()];
  if (sessionId) args.push('--resume', sessionId);
  const child = spawn(claudeCommand(), args, { cwd: kit.P.kit, env: kit.toolEnv() });
  let buffer = '';
  let newSession = sessionId;
  let finished = false;
  const finish = (result) => {
    if (finished) return;
    finished = true;
    onDone(result);
  };
  child.stdout.on('data', (chunk) => {
    buffer += chunk.toString();
    let idx;
    while ((idx = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (!line) continue;
      let ev;
      try { ev = JSON.parse(line); } catch { continue; }
      if (ev.session_id) newSession = ev.session_id;
      if (ev.type === 'assistant' && ev.message && Array.isArray(ev.message.content)) {
        for (const part of ev.message.content) {
          if (part.type === 'text') onText(part.text);
          else if (part.type === 'tool_use') onText(`\n\`[도구] ${part.name}\`\n`);
        }
      } else if (ev.type === 'result') {
        // 허용 목록에 없어 거절된 도구 호출 — 앱이 사람에게 보여 주고 허용하면 이어서 다시 하게 한다
        const seen = new Set();
        const denials = (ev.permission_denials || []).filter((d) => {
          const k = JSON.stringify([d.tool_name, d.tool_input]);
          if (seen.has(k)) return false;
          seen.add(k);
          return true;
        }).map((d) => ({ tool: d.tool_name, input: d.tool_input, once: ruleFor(d, false), always: ruleFor(d, true) }));
        finish({ ok: !ev.is_error, sessionId: newSession, cost: ev.total_cost_usd, error: ev.is_error ? String(ev.result) : '', denials });
      }
    }
  });
  let err = '';
  child.stderr.on('data', (c) => { err += c; });
  child.on('error', (e) => finish({ ok: false, sessionId, error: `Claude CLI 를 실행하지 못했다(${e.message})` }));
  child.on('close', (code) => finish({ ok: code === 0, sessionId: newSession, error: code === 0 ? '' : err.slice(-500) }));
  return child;
}

function summaryPrompt(runName) {
  return [
    `runs/${runName}/ 의 report.md 와 results.json 을 읽고, QA 팀이 볼 요약을 한국어 마크다운으로 써라.`,
    '- 맨 위 한 줄: 전체 판정(통과·실패·진행 실패·확인 필요 수).',
    '- 실패·진행 실패·확인 필요마다: 무엇이 일어났는지, 근거(이벤트·사유), 결함 의심인지 환경 문제인지 추정과 그 근거. 추정이면 추정이라고 쓴다.',
    '- 다시 돌려 볼 것이 있으면 구체적으로(케이스 id · 입력 시드).',
    '- 파일을 고치지 말고 요약 본문만 출력한다. 앞뒤 인사말 없이.',
  ].join('\n');
}

function diagnosePrompt(runName, caseId, play) {
  return [
    `runs/${runName}/ 의 ${caseId} 판 ${play} 이 ERROR 또는 FAIL 이다. 원인을 진단하라.`,
    `읽을 것: runs/${runName}/results.json, runs/${runName}/${caseId}/play${play}/events.json(있으면), runs/${runName}/device-log-*.txt(앱 로그·크래시), report.md.`,
    '- 앱 종료면 로그에서 마지막 assert·signal·스택을 찾아 인용한다. 로컬 빌드 assert 는 SIGINT(signal 2) 종료다.',
    '- 원인 추정, 그 근거, 다음 조치(케이스 수정 · 재실행 · 개발자 전달)를 짧게 쓴다. 확인 못 한 것은 Unknown.',
    '- 파일을 고치지 않는다. 한국어 마크다운 본문만 출력한다.',
  ].join('\n');
}

function caseDraftPrompt(request, current) {
  return [
    '자동 되감기 케이스 하나를 JSON 객체로 만들어라. 형식은 cases/README.md 의 「rewind」 절과 cases/sample-rewind.json 을 따른다.',
    '맵 이름은 테스트 맵 목록 이름(예: aaaa0001, champions0001)이다. 카드 id 를 모르면 "random" 으로 둔다.',
    '트리거 type 은 interval · afterRevive · afterBonusReturn. input 은 mode·seed·actionsPerSec·slideRatio·doubleJumpRatio·abilityEverySec·rescue.',
    '지금 폼의 값(바꾸라는 말이 없는 필드는 유지):',
    JSON.stringify(current),
    '요청:',
    request,
    'JSON 객체 하나만 출력한다. 설명을 붙이지 않는다.',
  ].join('\n');
}

module.exports = { ask, chat, summaryPrompt, diagnosePrompt, caseDraftPrompt, READ_ONLY, CHAT_TOOLS, ruleFor };
