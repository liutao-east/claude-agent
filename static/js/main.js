// 入口模块:状态、启动、路由、会话视图、发送/SSE、历史渲染。
import { escHtml, relTime } from "./util.js";
import { fetchScenarios, fetchMessages, askStream } from "./api.js";
import * as sessions from "./sessions.js";
import { scnIcon } from "./scenarios.js";
import { addBubble, addThinking, showError, renderMd } from "./render.js";
import { toast, scrollBottom, autoGrow, onKey, setEnabled, showBadge, setSendHandler, initSidebarToggle, closeMobileSidebar } from "./ui.js";

/* ═══════════════════════
   状态
═══════════════════════ */
let SCENARIOS   = [];
let DEFAULT_SCN = null;
let current     = null;   // { id, scenario }
let busy        = false;

/* ═══════════════════════
   注入依赖回调(避免循环依赖)
═══════════════════════ */
// sessions 变更后刷新历史列表
sessions.setSessionHooks({
  onAfterChange: () => renderHist(),
  // 当前会话被删除时回到新对话(原 removeSession 行为)
  onRemovedCurrent: (id) => { if (current && current.id === id) newChat(); },
});
// ui.onKey 需要触发 send,但 ui 不 import main,故注入
setSendHandler(send);

/* ═══════════════════════
   启动
═══════════════════════ */
init();
async function init() {
  initSidebarToggle();
  renderHist();
  try {
    const data = await fetchScenarios();
    SCENARIOS   = (data && data.scenarios) || [];
    DEFAULT_SCN = (data && data.default_scenario) || (SCENARIOS[0] && SCENARIOS[0].name);
  } catch (e) {
    toast("场景加载失败：" + e.message);
  }
  restoreFromHash();
}

/* ═══════════════════════
   路由:让刷新 / 直达保持当前视图
   #s/<场景>  仅选了场景、尚未产生会话
   #c/<会话id> 已有会话
═══════════════════════ */
function setRoute(hash) {
  // replaceState 更新地址栏但不新增历史、不触发事件,避免重入
  history.replaceState(null, "", hash ? "#" + hash : location.pathname + location.search);
}

function restoreFromHash() {
  const h = location.hash.replace(/^#\/?/, "");
  if (h.startsWith("c/")) {
    const id = h.slice(2);
    if (sessions.loadSessions().some(x => x.id === id)) { openSession(id); return; }
  } else if (h.startsWith("s/")) {
    const name = decodeURIComponent(h.slice(2));
    if (SCENARIOS.some(s => s.name === name)) { pickScenario(name); return; }
  }
  newChat();
}

/* ═══════════════════════
   历史列表渲染(用模块状态 current 标记 active)
═══════════════════════ */
function renderHist() {
  const el   = document.getElementById("histList");
  const list = sessions.loadSessions();
  el.innerHTML = "";
  if (!list.length) {
    el.innerHTML = `<div class="hist-empty">暂无历史记录<br/>新建一个对话开始吧</div>`;
    return;
  }
  list.forEach(s => {
    const item = document.createElement("div");
    item.className = "hist-item" + (current && current.id === s.id ? " active" : "");
    item.setAttribute("role", "listitem");
    item.setAttribute("tabindex", "0");
    item.setAttribute("aria-label", s.title || "未命名会话");
    item.onclick = () => openSession(s.id);
    item.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openSession(s.id); } };
    item.innerHTML = `
      <div class="hi-title">${escHtml(s.title || "未命名会话")}</div>
      <div class="hi-meta">
        <span class="hi-badge">${escHtml(s.scenario || "")}</span>
        <span class="hi-time">${relTime(s.updatedAt)}</span>
      </div>
      <button class="hi-del" title="删除" aria-label="删除此会话">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>`;
    item.querySelector(".hi-del").onclick = e => { e.stopPropagation(); sessions.removeSession(s.id); };
    el.appendChild(item);
  });
}

/* ═══════════════════════
   会话视图
═══════════════════════ */
function newChat() {
  current = { id: null, scenario: null };
  setRoute("");
  document.getElementById("topScn").style.display  = "none";
  document.getElementById("topEmpty").style.display = "";
  setEnabled(false);
  renderHist();
  renderScenarioPicker();
  closeMobileSidebar();
}

function renderScenarioPicker() {
  const feed = document.getElementById("feed");
  if (!SCENARIOS.length) {
    feed.innerHTML = `
      <div class="welcome">
        <div class="welcome-ico" aria-hidden="true">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        </div>
        <h2>暂无可用场景</h2>
        <p>请检查后端 config.json 中的 scenarios 配置。</p>
      </div>`;
    return;
  }
  feed.innerHTML = `
    <div class="welcome">
      <div class="welcome-ico" aria-hidden="true">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
        </svg>
      </div>
      <h2>代码问答助手</h2>
      <p>选择一个场景，我来帮你读代码、查问题。</p>
      <div class="scn-grid">
        ${SCENARIOS.map(s => `
          <div class="scn-card" data-name="${escHtml(s.name)}" tabindex="0" role="button" aria-label="选择场景：${escHtml(s.name)}">
            <div class="scn-icon" aria-hidden="true">${scnIcon(s.name, s.description)}</div>
            <div class="scn-name">${escHtml(s.name)}</div>
            <div class="scn-desc">${escHtml(s.description || "")}</div>
<!--            ${s.cwd ? `<div class="scn-cwd">${escHtml(s.cwd)}</div>` : ""}-->
          </div>`).join("")}
      </div>
    </div>`;
  feed.querySelectorAll(".scn-card").forEach(el => {
    el.onclick   = () => pickScenario(el.dataset.name);
    el.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickScenario(el.dataset.name); } };
  });
}

function pickScenario(name) {
  current = { id: null, scenario: name };
  setRoute("s/" + encodeURIComponent(name));
  showBadge(name);
  document.getElementById("feed").innerHTML = "";
  // 选中场景后,先以一条 AI 气泡显示该场景的引导语(介绍用途+用法)。
  // 仅前端渲染,不发往后端、不入库,故重开历史会话时不会重复出现。
  const scn = SCENARIOS.find(s => s.name === name);
  if (scn && scn.guide) addBubble("bot", scn.guide, true);
  setEnabled(true);
  document.getElementById("input").focus();
  closeMobileSidebar();
}

async function openSession(id) {
  if (busy) { toast("请等当前回答完成再切换会话"); return; }
  setEnabled(false);
  try {
    const data = await fetchMessages(id);
    const scn  = (data.conversation && data.conversation.scenario) || DEFAULT_SCN;
    current = { id, scenario: scn };
    setRoute("c/" + id);
    showBadge(scn);
    renderHist();
    const feed = document.getElementById("feed");
    feed.innerHTML = "";
    (data.messages || []).forEach(m => addBubble(m.role === "user" ? "user" : "bot", m.content, true));
    setEnabled(true);
    closeMobileSidebar();
    scrollBottom();
  } catch (e) {
    if (e && e.status === 404) { toast("该会话在后端已不存在，已从列表移除"); sessions.removeSession(id); return; }
    toast("加载会话失败：" + e.message);
    setEnabled(true);
  }
}

/* ═══════════════════════
   发送 & SSE 流
═══════════════════════ */
async function send() {
  const input = document.getElementById("input");
  const q = input.value.trim();
  if (!q || busy || !current.scenario) return;

  addBubble("user", q, false);
  input.value = ""; autoGrow(input);
  busy = true; setEnabled(false);

  const thinkEl = addThinking();
  let secs = 0;
  const timer = setInterval(() => {
    secs++;
    const el = thinkEl.querySelector(".thinking-secs");
    if (el) el.textContent = secs + "s";
  }, 1000);

  let bubble = null, contentEl = null, answer = "", started = false;

  const startBubble = () => {
    clearInterval(timer);
    thinkEl.remove();
    const b = addBubble("bot", "", false);
    bubble = b.bubble; contentEl = b.contentEl;
    started = true;
  };

  try {
    await askStream(
      { question: q, scenario: current.scenario, conversation_id: current.id },
      {
        signal: undefined,
        onEvent: (event, data) => {
          if (event === "token") {
            if (!started) startBubble();
            answer += (data.text || "");
            renderMd(contentEl, answer, false);
            scrollBottom();
          } else if (event === "done") {
            if (!started) startBubble();
            answer = data.answer || answer;
            renderMd(contentEl, answer, true);
            const meta = document.createElement("div");
            meta.className = "msg-meta";
            meta.innerHTML = `<span>${data.num_turns ?? 0} 轮对话</span><span class="meta-dot"></span><span>$${(data.cost_usd ?? 0).toFixed(4)}</span>`;
            bubble.appendChild(meta);
            onAnswered(data.conversation_id, q);
          } else if (event === "error") {
            clearInterval(timer);
            if (!started) thinkEl.remove();
            showError(data.error || "未知错误");
          }
        },
      }
    );
  } catch (e) {
    clearInterval(timer); thinkEl.remove();
    showError("网络错误：" + e.message);
  } finally {
    clearInterval(timer);
    busy = false; setEnabled(true);
    document.getElementById("input").focus();
    scrollBottom();
  }
}

function onAnswered(convId, question) {
  if (!convId) return;
  if (!current.id) {
    current.id = convId;
    setRoute("c/" + convId);
    const now = new Date().toISOString();
    sessions.upsertSession({ id: convId, scenario: current.scenario, title: question.slice(0, 22), createdAt: now, updatedAt: now });
  } else {
    sessions.touchSession(current.id);
  }
}

/* ═══════════════════════
   事件绑定(替代原内联 onclick/oninput/onkeydown)
═══════════════════════ */
document.getElementById("newBtn").addEventListener("click", newChat);

const _input = document.getElementById("input");
_input.addEventListener("input", () => autoGrow(_input));
_input.addEventListener("keydown", onKey);

document.getElementById("sendBtn").addEventListener("click", send);
