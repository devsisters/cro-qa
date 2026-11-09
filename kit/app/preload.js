'use strict';

const { contextBridge, ipcRenderer } = require('electron');

const call = (channel) => async (...args) => {
  const r = await ipcRenderer.invoke(channel, ...args);
  if (!r.ok) throw new Error(r.error);
  return r.value;
};

const channels = [
  'kit:info', 'cases:list', 'cases:read', 'cases:write', 'cases:check', 'runs:list', 'runs:read', 'runs:open', 'runs:openFile', 'runs:reveal', 'runs:menu', 'cases:delete', 'cases:authors', 'gh:login', 'presets:server',
  'presets:read', 'presets:write', 'devices:read', 'devices:write', 'devices:discover', 'settings:write',
  'device:launch', 'device:ping', 'setup:check', 'setup:action', 'scenario:status', 'scenario:connect', 'scenario:pull', 'scenario:fetch', 'app:restart', 'scenario:push', 'scenario:open', 'device:scene', 'device:maps', 'device:cards', 'run:start', 'run:stop', 'run:active',
  'claude:summary', 'claude:diagnose', 'claude:caseDraft', 'claude:chat', 'claude:stop',
];

const api = {};
for (const ch of channels) api[ch.replace(/:(\w)/, (_, c) => c.toUpperCase())] = call(ch);
api.on = (channel, fn) => {
  if (!['run:line', 'run:exit', 'claude:chunk', 'claude:done', 'setup:line', 'setup:exit', 'runs:deleted'].includes(channel)) throw new Error('unknown channel');
  ipcRenderer.on(channel, (_event, payload) => fn(payload));
};

contextBridge.exposeInMainWorld('qa', api);
