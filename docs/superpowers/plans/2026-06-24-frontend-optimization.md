# 前端优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把单文件 `static/index.html` 拆成 ES 模块，并加上场景切换、可折叠/响应式侧栏、流式停止、分级等待文案、消息级操作，最后整体换皮为 `proto.html` 的马卡龙视觉风（文案保持专业中性）。

**Architecture:** 纯前端，0 后端改动、0 构建链。原生 JS 拆成 `<script type="module">` 加载的 ES 模块，CSS 抽到 `styles/app.css`。纯逻辑函数（图标哈希、SSE 解析、时间格式化、转义）用 Node 内置 `node --test`（零依赖）做单测；DOM/视觉改动用「启动 FastAPI + 浏览器观察」做行为验证。

**Tech Stack:** 原生 HTML/CSS/ES Modules、marked + highlight.js（CDN，沿用）、FastAPI 同源托管、`node --test`（Node v22 内置，仅测试用）。

**设计依据：** `docs/superpowers/specs/2026-06-24-frontend-optimization-design.md`，视觉蓝本 `proto.html`。

---

## 验证约定（每个任务通用）

- **启动服务**：`uv run python server.py`（默认 `http://localhost:8000`）。改前端无需重启，浏览器硬刷新（Ctrl+F5）即可。
- **跑单测**：`node --test tests/js/`（Node v22 内置，无需 `npm install`）。
- **浏览器验证**：打开 `http://localhost:8000/`，按任务里的「Expected」逐条核对。
- 前端纯静态资源由 `server.py` 的 `/` 与 `StaticFiles` 托管；本计划不动任何后端路由。

---

## 文件结构（决定拆分边界）

```
static/
├── index.html              # 仅结构骨架 + <link app.css> + <script type="module" src=js/main.js>
├── styles/
│   └── app.css             # 全部样式；含马卡龙令牌(:root 变量)
└── js/
    ├── util.js             # 纯工具：escHtml(s)、relTime(iso,now)
    ├── api.js              # 后端对接：fetchScenarios/fetchMessages/askStream + 纯函数 parseSSEBuffer
    ├── sessions.js         # localStorage 历史 CRUD
    ├── scenarios.js        # 场景元数据：ICON_EMOJIS、pickIcon(name)、botAvatar/userAvatar
    ├── render.js           # Markdown 渲染、代码高亮、代码块复制、气泡 DOM、消息操作条
    ├── ui.js               # 顶栏/侧栏/输入区/云朵 toast/回到底部按钮 等界面状态
    └── main.js             # 入口：init、hash 路由、send() 编排、串起各模块

tests/js/
├── util.test.mjs           # relTime / escHtml
├── api.test.mjs            # parseSSEBuffer
└── scenarios.test.mjs      # pickIcon 稳定性与取值域
```

**关键导出签名（跨任务一致）：**

```js
// util.js
export function escHtml(s)                 // 纯字符串转义，不依赖 document
export function relTime(iso, now = new Date())

// api.js
export function parseSSEBuffer(buffer)     // 纯函数: -> { events:[{event,data}], rest:string }
export async function fetchScenarios()     // -> { scenarios:[], default_scenario }
export async function fetchMessages(id)    // -> { conversation, messages } | 抛错(含 status)
export async function askStream(body, { signal, onEvent })  // onEvent(event, data)

// scenarios.js
export const ICON_EMOJIS                   // 字符串数组
export function pickIcon(name)             // 纯函数: 按名稳定取一个 emoji
```

---

## 阶段一 · 模块拆分（纯搬迁，行为不变）

### Task 1: 抽取 CSS 到 styles/app.css

**Files:**
- Create: `static/styles/app.css`
- Modify: `static/index.html`（删除 `<style>…</style>`，改为 `<link>`）

- [ ] **Step 1: 移动样式**

把 `static/index.html` 当前 `<style>` 与 `</style>` 之间的**全部内容**原样剪切到新文件 `static/styles/app.css`（不改任何一行）。

- [ ] **Step 2: 在 index.html 引用**

在 `<head>` 内、原 `<style>` 位置替换为：

```html
<link rel="stylesheet" href="/styles/app.css" />
```

- [ ] **Step 3: 浏览器验证一致**

启动服务后打开 `http://localhost:8000/`，硬刷新。
Expected: 页面外观与改动前**完全一致**（配色、布局、字体无变化）；DevTools Network 里 `app.css` 200。

- [ ] **Step 4: Commit**

```bash
git add static/styles/app.css static/index.html
git commit -m "重构:抽取内联样式到 styles/app.css"
```

---

### Task 2: 抽取纯工具到 js/util.js（带单测）

**Files:**
- Create: `static/js/util.js`, `tests/js/util.test.mjs`
- Modify: `static/index.html`（暂不改，函数仍在内联脚本；本任务只新增可被复用与测试的纯实现）

> 说明：先把 `escHtml`/`relTime` 实现为**不依赖 document** 的纯函数并加测试，Task 3 的模块化会 import 它们。

- [ ] **Step 1: 写失败测试**

`tests/js/util.test.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { escHtml, relTime } from "../../static/js/util.js";

test("escHtml 转义尖括号与引号", () => {
  assert.equal(escHtml(`<b>"x"&</b>`), `&lt;b&gt;&quot;x&quot;&amp;&lt;/b&gt;`);
  assert.equal(escHtml(null), "");
});

test("relTime 相对时间", () => {
  const now = new Date("2026-06-24T12:00:00");
  assert.equal(relTime(new Date("2026-06-24T11:59:30").toISOString(), now), "刚刚");
  assert.equal(relTime(new Date("2026-06-24T11:30:00").toISOString(), now), "30 分钟前");
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/js/util.test.mjs`
Expected: FAIL（`Cannot find module .../util.js`）。

- [ ] **Step 3: 实现 util.js**

`static/js/util.js`:

```js
// 纯字符串 HTML 转义（不依赖 DOM，便于 Node 测试）
export function escHtml(s) {
  if (s == null) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// 相对时间；now 可注入便于测试
export function relTime(iso, now = new Date()) {
  if (!iso) return "";
  const d = new Date(iso);
  const diff = (now - d) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
  if (diff < 86400 && d.getDate() === now.getDate()) return d.toTimeString().slice(0, 5);
  if (diff < 172800) return "昨天";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
```

> 注意：原内联 `escHtml` 用 `document.createElement` 且不转义引号；新实现转义更完整且纯净，行为对渲染无负面影响。

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test tests/js/util.test.mjs`
Expected: PASS（2 tests）。

- [ ] **Step 5: Commit**

```bash
git add static/js/util.js tests/js/util.test.mjs
git commit -m "重构:新增纯工具 util.js(escHtml/relTime)并加单测"
```

---

### Task 3: 把内联脚本拆成 ES 模块

**Files:**
- Create: `static/js/api.js`, `static/js/sessions.js`, `static/js/scenarios.js`, `static/js/render.js`, `static/js/ui.js`, `static/js/main.js`
- Modify: `static/index.html`（删内联 `<script>`，改 `<script type="module" src="/js/main.js">`；给需要的元素留 `id`/去掉内联 `onclick`）

> 这是一次**机械搬迁**：把现有内联脚本的函数按下表归位，不改逻辑。所有跨模块调用改成 `import/export`。源代码就在当前 `index.html`，逐函数搬。

**函数归位表（来自现 index.html 内联脚本）：**

| 模块 | 放入的函数/常量 |
| --- | --- |
| `util.js` | （已建）`escHtml`、`relTime` |
| `api.js` | `parseSSE`→改造为 `askStream` + 纯 `parseSSEBuffer`；新增 `fetchScenarios`、`fetchMessages` 封装现有 `fetch("/scenarios")`、`fetch("/conversations/{id}/messages")` |
| `sessions.js` | `LS_KEY`、`loadSessions`、`saveSessions`、`upsertSession`、`touchSession`、`removeSession` |
| `scenarios.js` | `SCN_ICONS`、`scnIcon`（暂原样保留，Task 12 再替换为 emoji 版）、`USER_AV`、`BOT_AV` |
| `render.js` | `addBubble`、`addThinking`、`showError`、`COPY_ICON`、`CHECK_ICON`、`addCopyButtons`、`renderMd` |
| `ui.js` | `toast`、`scrollBottom`、`autoGrow`、`onKey`、`setEnabled`、`showBadge`、顶栏/侧栏 DOM 取值 |
| `main.js` | 模块级状态(`SCENARIOS`/`DEFAULT_SCN`/`current`/`busy`)、`init`、路由(`setRoute`/`restoreFromHash`)、`newChat`、`renderScenarioPicker`、`pickScenario`、`openSession`、`send`、`onAnswered` |

- [ ] **Step 1: 写各模块（导出/导入）**

为每个模块加 `export`；在使用方加 `import`。例如 `api.js` 顶部不引用任何 DOM；`render.js` import `escHtml`/`renderMd` 依赖的 marked/hljs 仍用全局 `window.marked`/`window.hljs`（CDN 注入）。`main.js` 顶部：

```js
import { escHtml, relTime } from "./util.js";
import { fetchScenarios, fetchMessages, askStream } from "./api.js";
import * as sessions from "./sessions.js";
import { scnIcon, USER_AV, BOT_AV } from "./scenarios.js";
import { addBubble, addThinking, showError, renderMd } from "./render.js";
import { toast, scrollBottom, autoGrow, onKey, setEnabled, showBadge } from "./ui.js";
```

- [ ] **Step 2: 把 api.js 的 SSE 解析抽成纯函数**

`api.js` 中加纯函数（供 Task 5 测试）：

```js
// 解析 SSE 文本缓冲，返回完整事件与剩余未完成片段
export function parseSSEBuffer(buffer) {
  const events = [];
  let rest = buffer, idx;
  while ((idx = rest.indexOf("\n\n")) !== -1) {
    const chunk = rest.slice(0, idx); rest = rest.slice(idx + 2);
    let ev = "message", dataStr = "";
    chunk.split("\n").forEach(line => {
      if (line.startsWith("event:")) ev = line.slice(6).trim();
      else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
    });
    if (!dataStr) continue;
    let d; try { d = JSON.parse(dataStr); } catch { d = { text: dataStr }; }
    events.push({ event: ev, data: d });
  }
  return { events, rest };
}

export async function askStream(body, { signal, onEvent }) {
  const resp = await fetch("/ask_stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    let msg = "HTTP " + resp.status;
    try { const j = await resp.json(); if (j.error) msg = j.error; } catch {}
    const e = new Error(msg); e.httpStatus = resp.status; throw e;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const { events, rest } = parseSSEBuffer(buf);
    buf = rest;
    for (const { event, data } of events) onEvent(event, data);
  }
}
```

`main.js` 的 `send()` 改为调用 `askStream({question, scenario, conversation_id}, { signal, onEvent })`，把原 `parseSSE` 回调逻辑搬进 `onEvent`。

- [ ] **Step 3: index.html 去内联、改模块加载**

- 删除整段内联 `<script>…</script>`，替换为：`<script type="module" src="/js/main.js"></script>`（放在 `</body>` 前）。
- 现有 `onclick="newChat()"` 等内联事件改为在 `main.js`/`ui.js` 里用 `addEventListener` 绑定（给元素加 `id`：新对话按钮 `id="newBtn"`、发送按钮已有 `id="sendBtn"`、输入框已有 `id="input"`）。`main.js` 末尾 `init()`。

- [ ] **Step 4: 浏览器验证行为一致**

打开 `http://localhost:8000/`，逐项核对（与改动前一致）：
Expected:
- 进入显示场景卡片；点卡片进入场景、出现引导语气泡、顶栏徽章显示场景名。
- 输入问题→出现「正在思考 Ns」→逐字流式→底部显示「N 轮 · $X」。
- 新对话、历史点开、删除历史、刷新后 `#c/<id>` 仍恢复会话，均正常。
- DevTools Console 无报错；Network 里各 `js/*.js` 200。

- [ ] **Step 5: Commit**

```bash
git add static/js static/index.html
git commit -m "重构:内联脚本拆分为 ES 模块(api/sessions/scenarios/render/ui/main)"
```

---

### Task 4: 为 parseSSEBuffer 补单测

**Files:**
- Create: `tests/js/api.test.mjs`

- [ ] **Step 1: 写测试**

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseSSEBuffer } from "../../static/js/api.js";

test("解析完整 token 事件并保留残片", () => {
  const buf =
    'event: token\ndata: {"text":"你好"}\n\n' +
    'event: token\ndata: {"text":"世界"}\n\n' +
    'event: token\ndata: {"text":"残';
  const { events, rest } = parseSSEBuffer(buf);
  assert.equal(events.length, 2);
  assert.deepEqual(events[0], { event: "token", data: { text: "你好" } });
  assert.equal(rest, 'event: token\ndata: {"text":"残');
});

test("done 事件携带结构化数据", () => {
  const { events } = parseSSEBuffer('event: done\ndata: {"answer":"a","num_turns":3}\n\n');
  assert.equal(events[0].event, "done");
  assert.equal(events[0].data.num_turns, 3);
});
```

> `api.js` 顶层不得有 DOM 访问，否则 Node import 失败——若 Task 3 不慎在顶层碰了 `document`，移进函数内。

- [ ] **Step 2: 跑测试**

Run: `node --test tests/js/api.test.mjs`
Expected: PASS（2 tests）。

- [ ] **Step 3: Commit**

```bash
git add tests/js/api.test.mjs
git commit -m "测试:parseSSEBuffer 单测"
```

---

## 阶段二 · 布局改造（A + D）

### Task 5: 侧栏可折叠 + 记忆

**Files:**
- Modify: `static/index.html`（顶栏加折叠按钮）、`static/js/ui.js`、`static/styles/app.css`

- [ ] **Step 1: 顶栏加折叠按钮**

在 `.topbar` 最左侧（场景图标前）加：

```html
<button class="collapse-btn" id="collapseBtn" aria-label="折叠侧栏" title="折叠/展开侧栏">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
</button>
```

- [ ] **Step 2: ui.js 实现折叠逻辑**

`ui.js` 增加并在 `main.js` 的 `init()` 调用 `initSidebarToggle()`：

```js
const SIDEBAR_KEY = "codeqa.sidebarCollapsed";
export function initSidebarToggle() {
  const collapsed = localStorage.getItem(SIDEBAR_KEY) === "1";
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  document.getElementById("collapseBtn").addEventListener("click", () => {
    const now = document.body.classList.toggle("sidebar-collapsed");
    localStorage.setItem(SIDEBAR_KEY, now ? "1" : "0");
  });
}
```

- [ ] **Step 3: CSS**

`app.css` 末尾：

```css
.collapse-btn { display:flex; align-items:center; justify-content:center; width:30px; height:30px; border:none; background:transparent; color:var(--text-2,#64748B); border-radius:8px; cursor:pointer; }
.collapse-btn:hover { background:var(--surface-2,#F8FAFC); }
body.sidebar-collapsed .sidebar { display:none; }
```

- [ ] **Step 4: 浏览器验证**

Expected: 点顶栏 ☰ → 侧栏隐藏、主区变宽；再点恢复；**刷新后保持**折叠状态。

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/js/ui.js static/styles/app.css
git commit -m "feat:侧栏可折叠并记忆状态"
```

---

### Task 6: 窄屏响应式（侧栏转浮层）

**Files:**
- Modify: `static/styles/app.css`、`static/js/ui.js`

- [ ] **Step 1: CSS 媒体查询**

```css
@media (max-width: 760px) {
  .sidebar { position: fixed; left: 0; top: 0; height: 100vh; z-index: 50;
    transform: translateX(-100%); transition: transform .25s var(--ease, ease); box-shadow: var(--sh-md); }
  body.sidebar-open .sidebar { transform: translateX(0); }
  body.sidebar-collapsed .sidebar { display: flex; }      /* 窄屏忽略折叠态，统一用浮层 */
  .sidebar-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.25); z-index: 40; display: none; }
  body.sidebar-open .sidebar-backdrop { display: block; }
}
@media (min-width: 761px) { .sidebar-backdrop { display: none !important; } }
```

- [ ] **Step 2: 浮层开合逻辑**

`index.html` 在 `<body>` 内加 `<div class="sidebar-backdrop" id="sidebarBackdrop"></div>`。`ui.js` 的折叠按钮点击改为「宽屏切折叠 / 窄屏切浮层」：

```js
function isNarrow() { return window.matchMedia("(max-width: 760px)").matches; }
// 在 initSidebarToggle 的 click 里：
//   if (isNarrow()) document.body.classList.toggle("sidebar-open");
//   else { ...原折叠逻辑... }
// backdrop 点击关闭浮层：
document.getElementById("sidebarBackdrop").addEventListener("click",
  () => document.body.classList.remove("sidebar-open"));
```

并在 `main.js` 选中会话/新建对话后调用 `document.body.classList.remove("sidebar-open")`（窄屏选完自动收起）。导出一个 `closeMobileSidebar()` 供 main 调用。

- [ ] **Step 3: 浏览器验证**

把窗口拉窄到 < 760px（或 DevTools 设备模拟）。
Expected: 侧栏默认隐藏；点 ☰ 从左滑出 + 半透明遮罩；点遮罩或选中某会话后自动收起；主区与输入框占满宽度不溢出。宽屏(>760)行为不受影响。

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/js/ui.js static/styles/app.css
git commit -m "feat:窄屏侧栏转浮层(响应式降级)"
```

---

### Task 7: 顶栏场景切换器

**Files:**
- Modify: `static/index.html`（顶栏徽章改为可点下拉）、`static/js/ui.js`、`static/js/main.js`、`static/styles/app.css`

- [ ] **Step 1: 顶栏结构**

把 `#topScn` 区域改为可点的切换器：

```html
<span id="topScn" style="display:none">
  <button class="scn-switch" id="scnSwitch" aria-haspopup="listbox" aria-expanded="false">
    <span class="topbar-badge" id="topBadge"></span>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="scn-menu" id="scnMenu" role="listbox" hidden></div>
</span>
```

顶栏右侧加统计位（Task 8 用）：`<span class="topbar-stats" id="topStats" style="margin-left:auto"></span>`

- [ ] **Step 2: 菜单渲染与切换语义**

`main.js`：新增 `openScenarioMenu()`，用模块级 `SCENARIOS` 渲染选项；点选某场景：

```js
function switchScenario(name) {
  if (name === current.scenario && !current.id) return;      // 同场景且未开始,忽略
  const hasMsgs = !!current.id;                              // 当前会话已产生消息
  if (hasMsgs && name !== current.scenario) {
    // 轻确认:开新对话(后端会话锁定场景,无法中途切换)
    if (!confirm(`切换到「${name}」将开启一条新对话，当前对话会保留在历史中。继续？`)) return;
  }
  // 等价于"在该场景下新对话"
  current = { id: null, scenario: name };
  setRoute("s/" + encodeURIComponent(name));
  showBadge(name);
  // 复用 pickScenario 的渲染(引导语 + 启用输入)
  pickScenario(name);
}
```

`ui.js` 提供菜单开合：`toggleScnMenu(show)`，点菜单外区域关闭。

- [ ] **Step 3: CSS**

```css
.scn-switch { display:inline-flex; align-items:center; gap:5px; border:none; background:transparent; cursor:pointer; padding:2px 6px; border-radius:8px; }
.scn-switch:hover { background:var(--surface-2,#F8FAFC); }
.scn-menu { position:absolute; margin-top:6px; background:var(--surface,#fff); border:1px solid var(--border,#E4E9F0); border-radius:10px; box-shadow:var(--sh-md); padding:6px; z-index:60; min-width:200px; }
.scn-menu[hidden] { display:none; }
.scn-menu-item { display:flex; align-items:center; gap:8px; padding:8px 10px; border-radius:8px; cursor:pointer; font-size:13px; }
.scn-menu-item:hover { background:var(--surface-2,#F8FAFC); }
.scn-menu-item.current { background:var(--primary-l,#EEF3FF); }
```

- [ ] **Step 4: 浏览器验证**

Expected:
- 进入某会话后，点顶栏场景徽章 → 弹出场景列表（当前场景高亮）。
- 选**同**场景：无变化、菜单关闭。
- 在已有消息的会话里选**别的**场景：弹确认 → 确认后变成该场景的新对话（地址栏 `#s/<name>`、引导语出现、输入可用、顶栏徽章更新）。
- 取消则维持原状。

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/js static/styles/app.css
git commit -m "feat:顶栏场景切换器(切异场景=开新对话)"
```

---

### Task 8: 顶栏显示累计轮数与花费

**Files:**
- Modify: `static/js/main.js`、`static/js/ui.js`

- [ ] **Step 1: 累计状态**

`main.js` 模块级状态加 `let stats = { turns: 0, cost: 0 }`。`newChat`/`pickScenario`/`switchScenario`/`openSession` 重置为 `{turns:0,cost:0}`。`openSession` 加载历史时无成本数据，保持 0（仅展示本次会话内新增）。

- [ ] **Step 2: done 事件累加并渲染**

在 `send()` 的 `done` 分支里，原本写每条 meta，同时累加并刷新顶栏：

```js
stats.turns += data.num_turns ?? 0;
stats.cost  += data.cost_usd ?? 0;
renderStats(stats);          // 来自 ui.js
```

`ui.js`:

```js
export function renderStats({ turns, cost }) {
  const el = document.getElementById("topStats");
  if (!el) return;
  el.textContent = turns ? `${turns} 轮 · $${cost.toFixed(4)}` : "";
}
export function clearStats() { renderStats({ turns: 0, cost: 0 }); }
```

`newChat`/切场景时调用 `clearStats()`。

- [ ] **Step 3: 浏览器验证**

Expected: 提问得到回答后，顶栏右侧出现「N 轮 · $0.00xx」；多轮追问数字累加；新对话/切场景后清空。

- [ ] **Step 4: Commit**

```bash
git add static/js/main.js static/js/ui.js
git commit -m "feat:顶栏常驻显示本会话累计轮数与花费"
```

---

## 阶段三 · 对话体验（B + C）

### Task 9: 流式停止按钮

**Files:**
- Modify: `static/index.html`（发送按钮区）、`static/js/main.js`、`static/js/ui.js`、`static/styles/app.css`

- [ ] **Step 1: send() 接入 AbortController**

`main.js` 模块级 `let aborter = null;`。`send()` 开头：`aborter = new AbortController();`，把 `aborter.signal` 传给 `askStream(..., { signal: aborter.signal, onEvent })`。`finally` 里 `aborter = null;`。捕获处对 `AbortError` 静默（不弹错误）：

```js
} catch (e) {
  clearInterval(timer); thinkEl.remove?.();
  if (e.name === "AbortError") {
    // 用户主动停止:保留已出文字,不显示错误
  } else {
    showError(e.httpStatus ? ("HTTP " + e.httpStatus + " · " + e.message) : ("网络错误：" + e.message));
  }
}
```

- [ ] **Step 2: 按钮在「发送/停止」间切换**

`ui.js` 增加 `setSending(on)`：流式期间把 `#sendBtn` 切到停止态（红色 ■、`aria-label="停止"`），点击时调用回调中断：

```js
export function setSending(on, onStop) {
  const btn = document.getElementById("sendBtn");
  btn.classList.toggle("is-stop", on);
  btn.setAttribute("aria-label", on ? "停止" : "发送消息");
  btn.innerHTML = on
    ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>`
    : SEND_ICON;     // SEND_ICON = 现有纸飞机 svg 字符串,从 index 移到 ui.js
  btn.onclick = on ? onStop : null;   // 发送态点击仍由原 send 绑定
}
```

`send()` 里：开始流式后 `setSending(true, () => aborter?.abort())`；`finally` 里 `setSending(false)` 并恢复发送绑定。注意发送态时 `#sendBtn` 原 click→`send`，停止态时改成 abort，结束后还原。

- [ ] **Step 3: CSS**

```css
.send-btn.is-stop { background: var(--danger,#EF4444); }
.send-btn.is-stop:hover { background:#dc2626; transform:none; }
```

- [ ] **Step 4: 浏览器验证**

Expected: 发送后按钮变红 ■；流式中途点击 → 立即停止，已出文字**保留**在气泡里，输入框恢复可用，无错误提示；之后可正常再次提问。

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/js static/styles/app.css
git commit -m "feat:流式回答可一键停止(保留已出文字)"
```

---

### Task 10: 分级等待文案

**Files:**
- Modify: `static/js/render.js`（thinking 文案）、`static/js/main.js`（计时回调）

- [ ] **Step 1: 文案分级函数**

`render.js`：

```js
export function waitingText(secs) {
  if (secs < 10) return "正在思考";
  if (secs < 30) return "正在查阅相关代码 / 日志";
  return "仍在分析，复杂排查可能需要 1–2 分钟";
}
```

- [ ] **Step 2: 计时器里更新文案**

`main.js` 的 `send()` 中现有 `setInterval` 每秒更新秒数处，同时更新文案：

```js
const timer = setInterval(() => {
  secs++;
  const sEl = thinkEl.querySelector(".thinking-secs");
  const tEl = thinkEl.querySelector(".thinking-text");
  if (sEl) sEl.textContent = secs + "s";
  if (tEl) tEl.textContent = waitingText(secs);
}, 1000);
```

- [ ] **Step 3: 浏览器验证**

Expected: 提一个会读较多文件的问题（如 troubleshoot 场景），观察等待文案随时间从「正在思考」→「正在查阅相关代码 / 日志」→「仍在分析…」推进；秒数同步增长。

- [ ] **Step 4: Commit**

```bash
git add static/js/render.js static/js/main.js
git commit -m "feat:等待文案按时长分级,缓解卡死错觉"
```

---

### Task 11: 消息级操作 + 出错重试

**Files:**
- Modify: `static/js/render.js`（气泡操作条、错误气泡重试）、`static/js/main.js`（重新生成/重试回调）、`static/styles/app.css`

- [ ] **Step 1: 助手气泡操作条**

`render.js` 的 `addBubble`：当 `role==="bot"` 时，在 `.bubble` 内加一个操作条容器（默认隐藏，悬停浮出）。提供：

```js
// 在 bot 气泡渲染完成处调用,actions: { onCopy, onRegen }
export function attachBotActions(bubbleEl, getMarkdown, { onRegen }) {
  const bar = document.createElement("div");
  bar.className = "msg-actions";
  bar.innerHTML = `<button class="ma-btn" data-act="copy" title="复制整条">⧉</button>
                   <button class="ma-btn" data-act="regen" title="重新生成">↻</button>`;
  bar.querySelector('[data-act="copy"]').onclick = () => {
    navigator.clipboard.writeText(getMarkdown()).then(() => toast("已复制整条回答"));
  };
  bar.querySelector('[data-act="regen"]').onclick = onRegen;
  bubbleEl.appendChild(bar);
}
```

`main.js` 在 `done` 分支拿到完整 `answer` 后调用 `attachBotActions(bubble, () => answer, { onRegen: () => regenerate(q) })`。`regenerate(q)` = 把上一问 `q` 重新走一遍 `send` 流程（设置输入值并调用 send，或抽出 `ask(q)` 复用）。

> 建议把 `send()` 主体抽成 `ask(question)`，`send()` 读取输入框后调用 `ask`；`regenerate`/`retry` 直接调 `ask(原问题)`。

- [ ] **Step 2: 错误气泡加重试**

`render.js` 的 `showError` 增加可选重试回调，渲染「↻ 重试」按钮：

```js
export function showError(msg, onRetry) {
  const { bubble } = addBubble("bot", "", false);
  bubble.parentElement.classList.add("err");
  const c = bubble.querySelector(".content");
  c.innerHTML = `出了点状况，请稍后再试。<div class="msg-meta">${escHtml(msg)}</div>`;
  if (onRetry) {
    const b = document.createElement("button");
    b.className = "retry-btn"; b.textContent = "↻ 重试";
    b.onclick = () => { bubble.parentElement.remove(); onRetry(); };
    c.appendChild(b);
  }
  scrollBottom();
}
```

`main.js` 调用 `showError(msg, () => ask(q))`。

- [ ] **Step 3: CSS**

```css
.msg-actions { position:absolute; top:-12px; right:8px; display:flex; gap:4px; background:var(--surface,#fff); border:1px solid var(--border,#E4E9F0); border-radius:8px; padding:2px; box-shadow:var(--sh,0 2px 8px rgba(0,0,0,.08)); opacity:0; transition:opacity .15s; }
.msg.bot .bubble { position: relative; }
.msg.bot .bubble:hover .msg-actions { opacity:1; }
.ma-btn { border:none; background:transparent; cursor:pointer; padding:3px 7px; border-radius:5px; color:var(--text-2,#64748B); font-size:13px; }
.ma-btn:hover { background:var(--surface-2,#F8FAFC); color:var(--text,#1A202C); }
.retry-btn { margin-top:8px; border:none; background:var(--danger,#EF4444); color:#fff; border-radius:6px; padding:4px 12px; cursor:pointer; font-size:12px; }
```

- [ ] **Step 4: 浏览器验证**

Expected:
- 悬停某条助手回答 → 右上浮出「⧉ 复制 / ↻ 重新生成」；点复制 → toast 提示、剪贴板得到该条 Markdown 原文；点重新生成 → 用同一问题再答一遍。
- 代码块自带的一键复制按钮仍在、不受影响。
- 制造一次错误（如临时停服务后发送）→ 错误气泡出现「↻ 重试」，点击用刚才的问题重发。

- [ ] **Step 5: Commit**

```bash
git add static/js static/styles/app.css
git commit -m "feat:消息级复制/重新生成与出错一键重试"
```

---

## 阶段四 · 视觉换皮（马卡龙风，文案保持专业）

### Task 12: 场景图标/头像改为 emoji + 稳定随机（含单测）

**Files:**
- Modify: `static/js/scenarios.js`、`static/js/render.js`（头像引用）、`static/js/main.js`（场景卡渲染）
- Create: `tests/js/scenarios.test.mjs`

- [ ] **Step 1: 写失败测试**

`tests/js/scenarios.test.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { pickIcon, ICON_EMOJIS } from "../../static/js/scenarios.js";

test("pickIcon 稳定:同名恒定", () => {
  assert.equal(pickIcon("code-qa"), pickIcon("code-qa"));
  assert.equal(pickIcon("troubleshoot"), pickIcon("troubleshoot"));
});
test("pickIcon 取值落在 emoji 集内", () => {
  assert.ok(ICON_EMOJIS.includes(pickIcon("any-scenario-x")));
});
test("空名也安全", () => {
  assert.ok(ICON_EMOJIS.includes(pickIcon("")));
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/js/scenarios.test.mjs`
Expected: FAIL（`pickIcon`/`ICON_EMOJIS` 未导出）。

- [ ] **Step 3: 实现 emoji 稳定随机**

`scenarios.js` 替换原 `SCN_ICONS`/`scnIcon`：

```js
export const ICON_EMOJIS = ["💻","🔧","🐛","📄","🗄️","⚡","🔍","🧩","🛠️","📦"];

// 按场景名做稳定哈希 -> 取一个 emoji(同名恒定、不闪烁)
export function pickIcon(name) {
  const s = String(name || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return ICON_EMOJIS[h % ICON_EMOJIS.length];
}

export const BOT_AVATAR = "🤖";
export function userAvatar() { return "你"; }
```

- [ ] **Step 4: 接入渲染**

- `main.js` 的 `renderScenarioPicker` 里 `.scn-icon` 内容由 `scnIcon(...)` 改为 `pickIcon(s.name)`（直接放 emoji 文本）。
- `render.js` 的头像：bot 用 `BOT_AVATAR`、user 用 `userAvatar()`（替换原 `BOT_AV`/`USER_AV` 的 SVG）。删除对旧 `USER_AV`/`BOT_AV` 的 import。

- [ ] **Step 5: 跑测试 + 浏览器验证**

Run: `node --test tests/js/scenarios.test.mjs` → PASS。
浏览器 Expected: 场景卡图标、消息头像都变成 emoji；同一场景多次刷新图标不变。

- [ ] **Step 6: Commit**

```bash
git add static/js tests/js/scenarios.test.mjs
git commit -m "feat:场景图标/头像改用 emoji 稳定随机分配(替代正则猜测)"
```

---

### Task 13: 马卡龙令牌 + 全局换皮

**Files:**
- Modify: `static/styles/app.css`

> 视觉值以 `proto.html` 为准（仓库内已有）。本任务替换 `:root` 令牌并把全局壳层(body/sidebar/topbar/输入区/按钮)套用玻璃拟态与马卡龙色。

- [ ] **Step 1: 替换 :root 令牌**

把 `app.css` 顶部 `:root` 增补/替换为马卡龙令牌（保留旧变量名做别名，减少改动面）：

```css
:root {
  --pink:#FF9BB3; --pink-light:#FFE6EC;
  --blue:#86C1FF; --blue-light:#E6F2FF;
  --mint:#86E3CE; --mint-light:#E6FBF6;
  --yellow:#FFE599; --lavender:#D4C2FC;
  --text:#333344; --text-2:#777788; --text-3:#aaaabb;
  --surface:#ffffff; --surface-2:#F7F8FC; --border:#E8EBF5; --border-2:#dfe4f2;
  --bg:#f5f7ff;
  --r:16px; --r-xl:22px; --r-sm:12px; --r-xs:10px;
  --sh-sm:0 3px 10px rgba(134,193,255,.15);
  --sh:0 3px 10px rgba(134,193,255,.15);
  --sh-md:0 6px 18px rgba(134,193,255,.25);
  --ease:cubic-bezier(.34,1.56,.64,1); --t:220ms;
  /* 旧别名,保证沿用旧变量名的规则不报错 */
  --primary:var(--blue); --primary-d:#5aa6ff; --primary-l:var(--blue-light);
  --ai:#029272; --ai-l:var(--mint-light); --danger:#ff4d6d; --danger-l:var(--pink-light);
  --sidebar-w:270px; --topbar-h:56px;
}
body { background: linear-gradient(145deg,#fef7fb,#f0f7ff); color: var(--text); }
```

- [ ] **Step 2: 玻璃拟态壳层**

```css
.sidebar { background: rgba(255,255,255,.75); backdrop-filter: blur(10px); }
.topbar  { background: rgba(255,255,255,.70); backdrop-filter: blur(12px); }
.composer{ background: rgba(255,255,255,.65); backdrop-filter: blur(12px); }
.new-btn { background: linear-gradient(135deg, var(--pink), #ff88aa); box-shadow:0 4px 14px rgba(255,155,179,.2); }
.new-btn:hover { background: linear-gradient(135deg,#ff8aa6,#ff7799); }
.send-btn { background: linear-gradient(135deg, var(--blue), var(--lavender)); border-radius:999px; }
.composer-box { border-radius: var(--r-xl); }
.composer-box:focus-within { border-color: var(--blue); box-shadow:0 0 0 4px rgba(134,193,255,.2); }
::-webkit-scrollbar-thumb { background: var(--lavender); }
::-webkit-scrollbar-thumb:hover { background: var(--pink); }
```

- [ ] **Step 3: 浏览器验证**

Expected: 整体变为马卡龙渐变背景 + 毛玻璃侧栏/顶栏/输入区；新对话按钮粉色渐变、发送按钮蓝紫渐变圆形；滚动条变薰衣草色。功能不受影响、Console 无报错。

- [ ] **Step 4: Commit**

```bash
git add static/styles/app.css
git commit -m "feat:换皮(一)马卡龙令牌+玻璃拟态壳层"
```

---

### Task 14: 气泡 / 卡片 / 头像 / 动画换皮

**Files:**
- Modify: `static/styles/app.css`

- [ ] **Step 1: 气泡与头像**

```css
.av { border-radius:999px; font-size:16px; }
.msg.bot .av  { background: linear-gradient(135deg, var(--mint), #4cd1b3); color:#fff; }
.msg.user .av { background: linear-gradient(135deg, var(--pink), #ff7799); color:#fff; border:none; }
.bubble { border-radius: var(--r-xl); line-height:1.7; }
.msg.bot .bubble  { background: rgba(255,255,255,.85); border:1px solid var(--border); border-bottom-left-radius:6px; box-shadow:var(--sh-sm); }
.msg.user .bubble { background: linear-gradient(135deg, var(--pink), #ff82a0); color:#fff; border-bottom-right-radius:6px; box-shadow:0 4px 14px rgba(255,155,179,.2); }
.scn-card { border-radius: var(--r); box-shadow: var(--sh-sm); }
.scn-card:hover { transform: translateY(-4px); box-shadow: var(--sh-md); border-color: var(--blue); }
.scn-icon { background: var(--blue-light); font-size:20px; }
```

- [ ] **Step 2: 回弹动画**

```css
.msg { animation: popIn .3s var(--ease) both; }
@keyframes popIn { from{opacity:0; transform:translateY(10px) scale(.96);} to{opacity:1; transform:none;} }
.welcome-ico { animation: float 3s ease-in-out infinite; }
@keyframes float { 0%,100%{transform:translateY(0);} 50%{transform:translateY(-8px);} }
.dots i { animation: cuteBlink 1.2s infinite ease-in-out; box-shadow:0 0 6px rgba(134,193,255,.4); }
@keyframes cuteBlink { 0%,100%{opacity:.3; transform:scale(.7);} 50%{opacity:1; transform:scale(1.15);} }
.new-btn:hover, .scn-card:hover { transition: all var(--t) var(--ease); }
```

- [ ] **Step 3: 浏览器验证**

Expected: 用户气泡粉色渐变、助手气泡玻璃白；头像为渐变圆形 emoji；新消息弹入动画、欢迎头像上下浮动、思考圆点可爱跳动。

- [ ] **Step 4: Commit**

```bash
git add static/styles/app.css
git commit -m "feat:换皮(二)气泡/头像/卡片/回弹动画"
```

---

### Task 15: 云朵 toast + 回到底部悬浮按钮

**Files:**
- Modify: `static/index.html`、`static/js/ui.js`、`static/styles/app.css`

- [ ] **Step 1: 云朵 toast 样式 + 三态**

`app.css`（替换原 `.toast`）:

```css
.toast { position:fixed; bottom:40px; left:50%; transform:translateX(-50%) translateY(20px);
  padding:10px 22px; border-radius:999px; color:#fff; font-size:13px; opacity:0; z-index:9999;
  transition:opacity var(--t) var(--ease), transform var(--t) var(--ease); box-shadow:0 6px 20px rgba(0,0,0,.12); white-space:nowrap; }
.toast.show { opacity:1; transform:translateX(-50%) translateY(0); }
.toast.success { background:linear-gradient(135deg,var(--mint),#3fc8aa); }
.toast.error   { background:linear-gradient(135deg,#ff788c,#ff4d6d); }
.toast.info    { background:linear-gradient(135deg,#7799ff,#8672e8); }
```

`ui.js` 的 `toast(msg, type="info")` 设置 `t.className = "toast show " + type`。原调用点（如复制成功）传 `"success"`，加载失败传 `"error"`。

- [ ] **Step 2: 回到底部按钮**

`index.html` 在 `.feed` 同级或主区内加 `<button class="scroll-bottom" id="scrollBottomBtn" aria-label="回到最新">↓</button>`。`ui.js`：

```js
export function initScrollBottom() {
  const feed = document.getElementById("feed");
  const btn = document.getElementById("scrollBottomBtn");
  feed.addEventListener("scroll", () => {
    const atBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 16;
    btn.classList.toggle("show", !atBottom);
  });
  btn.addEventListener("click", () => { feed.scrollTop = feed.scrollHeight; });
}
```

`main.js` 的 `init()` 调 `initScrollBottom()`。CSS：

```css
.scroll-bottom { position:absolute; bottom:90px; right:24px; width:40px; height:40px; border-radius:50%;
  border:none; background:#fff; color:var(--blue); font-size:18px; box-shadow:var(--sh-md); cursor:pointer; display:none; }
.scroll-bottom.show { display:flex; align-items:center; justify-content:center; }
.scroll-bottom:hover { background:var(--blue-light); transform:translateY(-3px); transition:all var(--t) var(--ease); }
```

> `.main` 需 `position: relative;`（若尚无）以定位悬浮按钮。

- [ ] **Step 3: 浏览器验证**

Expected: toast 从底部居中云朵滑入，复制成功为薄荷绿、错误为粉红、信息为蓝紫；长对话向上滚动时右下出现 ↓ 按钮，点击回到最新、按钮消失。

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/js/ui.js static/styles/app.css
git commit -m "feat:换皮(三)云朵 toast + 回到底部悬浮按钮"
```

---

## 自检与收尾

### Task 16: 全量回归 + 文案红线核对

**Files:** 无（验证任务）

- [ ] **Step 1: 跑全部单测**

Run: `node --test tests/js/`
Expected: 全部 PASS（util / api / scenarios）。

- [ ] **Step 2: 浏览器全流程回归**

逐项 Expected（对照 spec 验收要点）：
- 模块化后行为正常、Console 无报错。
- 顶栏可切场景（异场景=新对话）、显示累计轮数与花费。
- 侧栏可折叠并记忆；窗口 < 760px 转浮层、主区占满。
- 流式可停止并保留已出文字；等待文案随时长分级；计时正常。
- 助手气泡可复制整条 / 重新生成；出错气泡可一键重试；代码块复制仍在。
- 场景图标/头像为 emoji 且同场景稳定；马卡龙配色/玻璃/圆角/回弹动画/云朵 toast/回到底部按钮齐全。

- [ ] **Step 3: 文案红线核对（专业中性）**

确认**未**出现 proto 的可爱措辞：标题仍「后端问答AI助手」、按钮仍「新对话」（非「新建可爱对话」）、等待文案为分级专业文案（非「正在认真思考」）、占位符/提示无「软萌」「超温柔」等。

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "chore:前端优化全量回归通过"
```

---

## 自检记录（写计划时）

- **Spec 覆盖**：A→Task7/8；B→Task9/10；C→Task11；D→Task5/6；F→Task3(拆模块)+Task12(图标)；视觉换皮→Task13/14/15；模块化地基→Task1-4。全部有对应任务。
- **占位符**：无 TBD/TODO；代码步骤均给出完整代码或精确搬迁指令（源在现有 index.html）。
- **类型一致**：`parseSSEBuffer`/`askStream`/`pickIcon`/`ICON_EMOJIS`/`renderStats`/`waitingText`/`attachBotActions`/`showError(msg,onRetry)` 在定义与调用处签名一致。
- **测试边界**：纯函数(util/api/scenarios)用 `node --test`；DOM/视觉用浏览器行为验证——因 0 构建链约束不引入前端测试框架。
