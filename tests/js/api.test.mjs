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
  const { events } = parseSSEBuffer('event: done\ndata: {"answer":"a","num_turns":3,"elapsed_ms":1250}\n\n');
  assert.equal(events[0].event, "done");
  assert.equal(events[0].data.num_turns, 3);
  assert.equal(events[0].data.elapsed_ms, 1250);
});
