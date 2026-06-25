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
