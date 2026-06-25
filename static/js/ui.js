// UI 交互辅助:Toast、滚动、输入框、按钮状态、顶栏徽标。
// send() 由 main.js 的 onKey 调用,这里不直接 import main(避免循环),
// 而是接受一个注入的 send 回调。

let _send = null;
export function setSendHandler(fn) { _send = fn; }

export function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3500);
}
let toastTimer = null;

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
