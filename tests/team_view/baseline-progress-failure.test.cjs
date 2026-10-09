const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("historical baseline progress failure explains platform repair without changing audit facts", () => {
  const element = () => ({addEventListener() {}});
  const context = vm.createContext({
    document: {getElementById: element, querySelectorAll: () => []},
    fetch: () => new Promise(() => {}), AbortController,
    setInterval() {}, setTimeout() {}, clearTimeout() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,
    "../../src/ai_software_engineer/team_view/app.js"), "utf8"), context);
  const run = expression => vm.runInContext(expression, context);
  const original = "new progress does not match the bound execution source";
  run(`operations = [{operation_id: "operation_resume_failed", status: "FAILED",
    error_code: "COMMAND_REJECTED", error_summary: ${JSON.stringify(original)},
    intent: {action: "RESUME_EXECUTION_BASELINE", project_id: "p", delivery_id: "r"}}];`);
  const message = run("humanizeBlockingText(operations[0].error_summary)");
  assert.match(message, /平台.*选取开发进度失败/);
  assert.match(message, /本次未能继续原需求/);
  assert.match(message, /进度和现场仍保留/);
  assert.match(message, /修复版本.*刷新原需求.*继续原需求/);
  assert.match(message, /无需新建需求/);
  assert.equal(run("operations[0].error_summary"), original);
  assert.equal(run("humanizeBlockingText('用户说明：' + operations[0].error_summary)"),
    "用户说明：" + original);
});
