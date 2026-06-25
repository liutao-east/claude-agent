// localStorage 会话历史管理。
// 纯数据层:不直接 import DOM 渲染模块(避免循环依赖),
// 会话变更后通过注册的回调通知 UI 层刷新。

export const LS_KEY = "codeqa.sessions";

// UI 变更钩子(由 main.js 注入,避免 sessions↔main 循环依赖)
let _onAfterChange = null;   // 变更后刷新历史列表
let _onRemovedCurrent = null; // 当前会话被删除时回到新对话

export function setSessionHooks({ onAfterChange, onRemovedCurrent } = {}) {
  if (onAfterChange   !== undefined) _onAfterChange   = onAfterChange;
  if (onRemovedCurrent !== undefined) _onRemovedCurrent = onRemovedCurrent;
}

export function loadSessions() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || []; } catch { return []; }
}

export function saveSessions(list) {
  localStorage.setItem(LS_KEY, JSON.stringify(list));
}

export function upsertSession(s) {
  const list = loadSessions().filter(x => x.id !== s.id);
  list.unshift(s);
  saveSessions(list);
  if (_onAfterChange) _onAfterChange();
}

export function touchSession(id) {
  const list = loadSessions();
  const s = list.find(x => x.id === id);
  if (s) {
    s.updatedAt = new Date().toISOString();
    saveSessions([s, ...list.filter(x => x.id !== id)]);
    if (_onAfterChange) _onAfterChange();
  }
}

export function removeSession(id) {
  saveSessions(loadSessions().filter(x => x.id !== id));
  if (_onRemovedCurrent) _onRemovedCurrent(id);
  if (_onAfterChange) _onAfterChange();
}
