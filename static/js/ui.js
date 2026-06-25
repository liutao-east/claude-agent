// UI 交互辅助:Toast、滚动、输入框、按钮状态、顶栏徽标。
// send() 由 main.js 的 onKey 调用,这里不直接 import main(避免循环),
// 而是接受一个注入的 send 回调。

let _send = null;
export function setSendHandler(fn) { _send = fn; }

export function toast(msg, type = "info") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast show " + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3500);
}
let toastTimer = null;

export function initScrollBottom() {
  const feed = document.getElementById("feed");
  const btn = document.getElementById("scrollBottomBtn");
  feed.addEventListener("scroll", () => {
    const atBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 16;
    btn.classList.toggle("show", !atBottom);
  });
  btn.addEventListener("click", () => { feed.scrollTop = feed.scrollHeight; });
}

export function scrollBottom() {
  const f = document.getElementById("feed"); f.scrollTop = f.scrollHeight;
}

export function autoGrow(t) {
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 140) + "px";
}

export function onKey(e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (_send) _send(); }
}

export function setEnabled(on) {
  const inp = document.getElementById("input");
  const btn = document.getElementById("sendBtn");
  inp.disabled = !on;
  btn.disabled = !on;
  inp.setAttribute("aria-disabled", String(!on));
}

export function showBadge(name) {
  document.getElementById("topEmpty").style.display = "none";
  document.getElementById("topScn").style.display   = "";
  document.getElementById("topBadge").textContent   = name;
}

const SIDEBAR_KEY = "codeqa.sidebarCollapsed";

function isNarrow() {
  return window.matchMedia("(max-width: 760px)").matches;
}

export function closeMobileSidebar() {
  document.body.classList.remove("sidebar-open");
}

export function initSidebarToggle() {
  const collapsed = localStorage.getItem(SIDEBAR_KEY) === "1";
  if (!isNarrow()) {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
  }

  document.getElementById("collapseBtn").addEventListener("click", () => {
    if (isNarrow()) {
      document.body.classList.toggle("sidebar-open");
    } else {
      const now = document.body.classList.toggle("sidebar-collapsed");
      localStorage.setItem(SIDEBAR_KEY, now ? "1" : "0");
    }
  });

  document.getElementById("sidebarBackdrop").addEventListener("click", closeMobileSidebar);

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#topScn")) toggleScnMenu(false);
  });
}

export function toggleScnMenu(show) {
  const menu = document.getElementById("scnMenu");
  const btn  = document.getElementById("scnSwitch");
  if (!menu || !btn) return;
  if (show === undefined) show = menu.hidden;
  menu.hidden = !show;
  btn.setAttribute("aria-expanded", String(show));
}

export function renderStats({ turns, cost }) {
  const el = document.getElementById("topStats");
  if (!el) return;
  el.textContent = turns ? `${turns} 轮 · $${cost.toFixed(4)}` : "";
}

export function clearStats() {
  renderStats({ turns: 0, cost: 0 });
}

// 把发送按钮在「发送态」和「停止态」之间切换
// on=true -> 停止态(红■)；on=false -> 发送态(纸飞机)
// 停止态时 onStop 作为按钮的 click 回调
export function setSending(on, onStop) {
  const btn = document.getElementById("sendBtn");
  if (!btn) return;
  btn.classList.toggle("is-stop", on);
  btn.setAttribute("aria-label", on ? "停止" : "发送消息");
  btn.innerHTML = on
    ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>`
    : `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`;
  // 停止态：绑定 onStop；发送态：解绑
  // send() 在 busy=true 时会提前返回，所以 addEventListener("click", send) 不会误触发
  btn.onclick = on ? onStop : null;
}
