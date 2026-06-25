// API 层:与后端通信 + SSE 解析。
// 纯逻辑/网络,顶层禁止任何 DOM 访问,便于 Node 测试。

// 解析 SSE 文本缓冲,返回完整事件与剩余未完成片段(纯函数,供测试)。
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

// 获取场景列表
export async function fetchScenarios() {
  const r = await fetch("/scenarios");
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

// 获取指定会话的消息历史
export async function fetchMessages(id) {
  const r = await fetch(`/conversations/${id}/messages`);
  if (!r.ok) { const e = new Error("HTTP " + r.status); e.status = r.status; throw e; }
  return r.json();
}

// 发送问题并流式接收 SSE。onEvent(event, data) 对每个事件回调。
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
