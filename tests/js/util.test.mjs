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
