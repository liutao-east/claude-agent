// DOM 渲染辅助:气泡、思考态、错误、Markdown 渲染。
import { escHtml } from "./util.js";
import { BOT_AVATAR, userAvatar } from "./scenarios.js";
import { toast, scrollBottom } from "./ui.js";

// marked / hljs 通过 CDN <script> 注入到全局,这里按原行为用 window.* 访问。

const COPY_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
const CHECK_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

export function addBubble(role, text, withMd) {
  const feed = document.getElementById("feed");
  const msg  = document.createElement("div");
  msg.className = "msg " + (role === "user" ? "user" : "bot");
  msg.innerHTML = `<div class="av" aria-hidden="true">${role === "user" ? userAvatar() : BOT_AVATAR}</div><div class="bubble"><div class="content"></div></div>`;
  const contentEl = msg.querySelector(".content");
  if (role === "user")    contentEl.textContent = text;
  else if (withMd)        renderMd(contentEl, text, true);
  feed.appendChild(msg);
  scrollBottom();
  return { bubble: msg.querySelector(".bubble"), contentEl };
}

export function addThinking() {
  const feed = document.getElementById("feed");
  const msg  = document.createElement("div");
  msg.className = "msg bot";
  msg.setAttribute("aria-live", "polite");
  msg.innerHTML = `
    <div class="av" aria-hidden="true">${BOT_AVATAR}</div>
    <div class="bubble thinking-bubble">
      <div class="dots" aria-hidden="true"><i></i><i></i><i></i></div>
      <span class="thinking-text">正在思考</span>
      <span class="thinking-secs">0s</span>
    </div>`;
  feed.appendChild(msg);
  scrollBottom();
  return msg;
}

export function showError(msg, onRetry) {
  const { bubble } = addBubble("bot", "", false);
  bubble.parentElement.classList.add("err");
  const c = bubble.querySelector(".content");
  c.innerHTML = `出了点状况，请稍后再试。<div class="msg-meta">${escHtml(msg)}</div>`;
  if (onRetry) {
    const b = document.createElement("button");
    b.className = "retry-btn";
    b.textContent = "↻ 重试";
    b.addEventListener("click", () => { bubble.parentElement.remove(); onRetry(); });
    c.appendChild(b);
  }
  scrollBottom();
}

function addCopyButtons(el) {
  el.querySelectorAll("pre").forEach(pre => {
    if (pre.querySelector(".copy-btn")) return;
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.setAttribute("aria-label", "复制代码");
    btn.innerHTML = COPY_ICON;
    btn.addEventListener("click", () => {
      const code = pre.querySelector("code");
      const text = code ? code.innerText : pre.innerText;
      navigator.clipboard.writeText(text).then(() => {
        btn.classList.add("copied");
        btn.innerHTML = CHECK_ICON;
        setTimeout(() => { btn.classList.remove("copied"); btn.innerHTML = COPY_ICON; }, 2000);
      }).catch(() => {
        const range = document.createRange();
        range.selectNodeContents(code || pre);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
      });
    });
    pre.appendChild(btn);
  });
}

export function renderMd(el, text, hl) {
  if (window.marked) {
    el.innerHTML = marked.parse(text);
    if (hl && window.hljs) el.querySelectorAll("pre code").forEach(b => hljs.highlightElement(b));
    if (hl) addCopyButtons(el);
  } else {
    el.textContent = text;
  }
}

export function waitingText(secs) {
  if (secs < 10) return "正在思考";
  if (secs < 30) return "正在查阅相关代码 / 日志";
  return "仍在分析，复杂排查可能需要 1–2 分钟";
}

export function attachBotActions(bubbleEl, getMarkdown, { onRegen }) {
  const bar = document.createElement("div");
  bar.className = "msg-actions";
  bar.innerHTML = `
    <button class="ma-btn" data-act="copy" title="复制整条" aria-label="复制整条回答">⧉</button>
    <button class="ma-btn" data-act="regen" title="重新生成" aria-label="重新生成回答">↻</button>`;
  bar.querySelector('[data-act="copy"]').addEventListener("click", () => {
    navigator.clipboard.writeText(getMarkdown()).then(() => toast("已复制整条回答", "success"));
  });
  bar.querySelector('[data-act="regen"]').addEventListener("click", onRegen);
  bubbleEl.appendChild(bar);
}
