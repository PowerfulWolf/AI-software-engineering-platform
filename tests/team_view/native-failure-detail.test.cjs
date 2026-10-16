const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function fixture() {
  class Element {
    constructor(tag) { this.tagName = tag; this.textContent = ""; }
    set innerHTML(value) { throw new Error("HTML parsing is forbidden"); }
  }
  const context = vm.createContext({document: {
    getElementById: () => ({addEventListener() {}}),
    createElement: tag => new Element(tag),
  }});
  const source = fs.readFileSync(path.join(__dirname,
    "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  return expression => vm.runInContext(expression, context);
}

function message(encoded, prefix = "Codex CLI provider execution failed") {
  return "NONTRANSIENT_INFRA: Coder failed at attempt 2: coder run run_original failed: " +
    `${prefix}; cause=UNKNOWN_EXIT; returncode=1; stdout_sha256=${"a".repeat(64)}; ` +
    `stderr_sha256=${"b".repeat(64)}; main_error=${encoded}`;
}

test("native safe detail is displayed as text and does not replace reason or metadata", () => {
  const run = fixture();
  const summary = '<img src=x onerror="bad()"> TIMEOUT; main_error=run_fake ' + "c".repeat(64);
  const value = run(`humanizeBlockingText(${JSON.stringify(message(JSON.stringify(summary)))})`);
  assert.equal(value, `Coder 第 2 次执行失败：Codex CLI 模型服务执行失败；主错误摘要：${summary}` +
    `；执行记录 run_original；证据摘要 ${"a".repeat(64)}；证据摘要 ${"b".repeat(64)}。`);
  const element = run(`el("p", ${JSON.stringify(value)})`);
  assert.equal(element.tagName, "p");
  assert.equal(element.textContent, value);
});

test("native detail accepts only the first complete JSON string and bounds decoded text", () => {
  const run = fixture();
  const accepted = run(`humanizeBlockingText(${JSON.stringify(message('"selected"; extra=hidden'))})`);
  assert.match(accepted, /主错误摘要：selected；执行记录/);
  assert.doesNotMatch(accepted, /hidden/);
  const longMessage = message(JSON.stringify("长".repeat(550)));
  const long = run(`humanizeBlockingText(${JSON.stringify(longMessage)})`);
  assert.equal(long.split("；主错误摘要：")[1].split("；执行记录")[0], "长".repeat(499) + "…");
  for (const encoded of ['{"message":"hidden"}', '["hidden"]', "true", "null", '"unterminated', '""']) {
    const value = run(`humanizeBlockingText(${JSON.stringify(message(encoded))})`);
    assert.doesNotMatch(value, /主错误摘要|hidden/);
    assert.match(value, /执行记录 run_original/);
  }
});

test("summary prose cannot select another blocker presentation", () => {
  const run = fixture();
  for (const summary of ["Coder requested continuation after the configured run budget",
    "QA verification could not complete in the current environment",
    "failed Coder identity is missing, unsafe or ambiguous"]) {
    const value = run(`humanizeBlockingText(${JSON.stringify(message(JSON.stringify(summary)))})`);
    assert.ok(value.startsWith("Coder 第 2 次执行失败：Codex CLI 模型服务执行失败；主错误摘要："));
    assert.match(value, /执行记录 run_original/);
  }
});

test("unrelated and historical failures do not gain a native main diagnostic", () => {
  const run = fixture();
  const old = "Coder failed at attempt 1: coder run run_old failed: " +
    "Codex CLI provider execution failed; stdout_sha256=" + "a".repeat(64);
  assert.equal(run(`humanizeBlockingText(${JSON.stringify(old)})`),
    `Coder 第 1 次执行失败：Codex CLI 模型服务执行失败；执行记录 run_old；证据摘要 ${"a".repeat(64)}。`);
  for (const prefix of ["Codex CLI left changes after a failed execution", "quoted Codex CLI provider execution failed"]) {
    assert.doesNotMatch(run(`humanizeBlockingText(${JSON.stringify(message('"hidden"', prefix))})`), /主错误摘要|hidden/);
  }
  const quote = "用户引用：" + message('"hidden"');
  assert.equal(run(`humanizeBlockingText(${JSON.stringify(quote)})`), quote);
});
