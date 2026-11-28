const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function setup() {
  const element = (tag) => ({tag, children: [], textContent: "", dataset: {},
    attributes: {}, append(...nodes) { this.children.push(...nodes.filter(Boolean)); },
    addEventListener() {}, setAttribute(name, value) {this.attributes[name] = value;},
    classList: {toggle() {}}});
  const context = vm.createContext({
    document: {getElementById: element, createElement: element,
      createTextNode: text => ({textContent: text, children: []}), querySelectorAll: () => []},
    fetch: () => new Promise(() => {}), AbortController,
    setInterval() {}, setTimeout() {}, clearTimeout() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,
    "../../src/ai_software_engineer/team_view/app.js"), "utf8"), context);
  return expression => vm.runInContext(expression, context);
}

const routes = `[{role: "qa", provider: "claude", model: "claude-opus-5-5", route_kind: "claude_cli"},
  {role: "qa", provider: "codex", model: "codex/gpt-6.2-sol", route_kind: "responses"}]`;
const call = fields => `{role: "qa", provider: "claude", model: "claude-opus-5-5", route_index: 1,
  outcome: "SUCCEEDED", error_code: null, completed_at: "2026-11-28T05:00:00Z", task_id: "t", ${fields}}`;

test("agent model state shows primary then backup and a healthy latest call", () => {
  const run = setup();
  const state = run(`agentModelState({model_routes: ${routes}, last_model_call: ${call("")}})`);
  assert.equal(state.routeText, "模型 claude-opus-5-5 → gpt-6.2-sol");
  assert.equal(state.status, "正常 · claude-opus-5-5");
  assert.equal(state.tone, "ok");
});

test("quota exhaustion and rate limits are visible as warnings", () => {
  const run = setup();
  const quota = run(`agentModelState({model_routes: ${routes},
    last_model_call: ${call('outcome: "FAILED", error_code: "QUOTA_EXHAUSTED"')}})`);
  assert.equal(quota.status, "额度已用完 · claude-opus-5-5");
  assert.equal(quota.tone, "warning");
  assert.match(quota.detail, /QUOTA_EXHAUSTED/);
  const limited = run(`agentModelState({model_routes: ${routes},
    last_model_call: ${call('outcome: "FAILED", error_code: "RATE_LIMITED"')}})`);
  assert.equal(limited.status, "被限流 · claude-opus-5-5");
});

test("a backup route serving the call and an agent without history", () => {
  const run = setup();
  const backup = run(`agentModelState({model_routes: ${routes},
    last_model_call: ${call('route_index: 2, provider: "codex", model: "codex/gpt-6.2-sol"')}})`);
  assert.equal(backup.status, "使用备用模型 · gpt-6.2-sol");
  const none = run(`agentModelState({model_routes: [], last_model_call: null})`);
  assert.equal(none.routeText, "");
  assert.equal(none.status, "");
});

test("a model quota wait asks the human to pick the backup or the original model", () => {
  const run = setup();
  const step = `{role: "qa", work_item_id: "w1", wait_disposition_sha256: "${"a".repeat(64)}",
    wait_disposition: {responsibility: "engineering", facts: {classification: "ENGINEERING_AUTHORIZATION",
    evidence_ids: ["model-quota://run_qa_7"], work_item_id: "w1"}}}`;
  assert.equal(run(`modelQuotaWaitRun(${step})`), "run_qa_7");
  assert.equal(run(`modelQuotaWaitRun({wait_disposition: {facts: {classification: "ENGINEERING_AUTHORIZATION",
    evidence_ids: ["other://x"]}}})`), null);
  run(`snapshot = {agents: [{model_routes: ${routes}}, {model_routes: ${routes}}]}`);
  assert.deepEqual(JSON.parse(run(`JSON.stringify(roleModelRoutes("qa").map(route => route.model))`)),
    ["claude-opus-5-5", "codex/gpt-6.2-sol"]);
  const intent = JSON.parse(run(`JSON.stringify(modelQuotaIntent({project_id: "p", id: "d",
    checkpoint_sha256: "${"b".repeat(64)}"}, ${step}, true))`));
  assert.deepEqual(intent, {action: "RESUME_MODEL_QUOTA_WAIT", project_id: "p", delivery_id: "d",
    expected_checkpoint_sha256: "b".repeat(64), work_item_id: "w1",
    expected_disposition_sha256: "a".repeat(64), use_backup: true});
});
