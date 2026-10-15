const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {supportedActions} = require("./console-capabilities-fixture.cjs");

class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.events = {}; this.dataset = {}; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); for (const node of nodes) if (typeof node !== "string") node.parentNode = this; }
  setAttribute() {}
  addEventListener(key, callback) { this.events[key] = callback; }
  get classList() { return {add: () => {}}; }
}
const descendants = node => [node, ...node.children.filter(child => typeof child !== "string").flatMap(descendants)];
const text = node => descendants(node).map(child => child.textContent).join(" ");
const button = (node, name) => descendants(node).find(child => child.tagName === "BUTTON" && child.textContent === name);

function fixture(planReady = false) {
  const facts = {task_id: "task_current", work_item_id: "work_current", role: "coder", task_intent_sha256: "b".repeat(64),
    source_revision: "c".repeat(40), checkpoint_sequence: 4, classification: "EXECUTION_UNCERTAIN"};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_DEPENDENCY", lease_liveness: "UNKNOWN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering"}};
  const request = {id: "request_current", project_id: "project_current", checkpoint_sha256: "a".repeat(64), stage: "DELIVERING",
    scopes: [{delivery_id: "delivery_current"}]};
  const task = {id: "delivery_current", task_id: facts.task_id, request_id: request.id, project_id: request.project_id,
    status: "IMPLEMENTING", terminal: false, task_revision: 4, task_intent_sha256: facts.task_intent_sha256, role_queue: [step]};
  const proof = {...facts, disposition_sha256: step.wait_disposition_sha256, proof_sha256: "e".repeat(64),
    original_run_id: "run_original", process_stop_sha256: "1".repeat(64),
    missing: ["OUTCOME_UNKNOWN", "CHECKPOINT_UNAVAILABLE"], permitted_resolutions: []};
  const original = {task_id: task.task_id, run_id: "run_original", role: "coder", source_revision: facts.source_revision};
  const stopped = {kind: "stopped_coder_execution_without_outcome", proof_sha256: "2".repeat(64),
    invocation_start: {request: original, work_item_id: step.work_item_id, checkpoint_sequence: 4},
    capture_start: {request: original, task_revision: 4, start_sha256: "3".repeat(64), worktree_path: "/fixture/coder"},
    capture_stop: {task_id: task.task_id, run_id: original.run_id, capture_start_sha256: "3".repeat(64),
      process_stop: {kind: "failed", returncode: -15, session_proof: {proof_scope: "owned_session_empty", proof_sha256: "5".repeat(64)}},
      output_present: false, original_error_code: "PROVIDER_ERROR", cause: null}};
  const plan = {purpose: "stopped_execution_rescue", plan_sha256: "4".repeat(64), input_mode: "preserve_draft", conflicted: false,
    target_base_ref: "c".repeat(40), prepared_source_revision: "c".repeat(40),
    dirty_capture: {source_revision: facts.source_revision, worktree_path: "/fixture/coder"},
    facts: {task: {id: task.task_id, base_ref: "c".repeat(40), branch_name: "ai/feature/original"}, task_revision: 4,
      work_item_id: step.work_item_id, stopped_execution: stopped,
      continuation: {retry_cause: "stopped_execution_unknown", stopped_execution_sha256: stopped.proof_sha256}}};
  const data = {request, task, step, proof, plan};
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data, supportedActions});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  const run = code => vm.runInContext(code, context);
  run(`snapshot = {team_id: "team_current", selected_project_id: "project_current", projects: [], agents: [], tasks: [data.task], requests: [data.request]};
    consoleTeamId = "team_current"; consoleAvailable = true; consoleDeliveryReady = true; operationsAvailable = true;
    consoleOperationContractVersion = 9; consoleSupportedActions = [...supportedActions];
    operations = [{operation_id: "inspect", status: "SUCCEEDED", updated_at: "2026-10-15T00:00:00Z",
      intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
      result: {project_id: data.request.project_id, delivery_id: data.request.id,
        checkpoint_sha256: data.request.checkpoint_sha256, engineering_wait_investigation: data.proof}}];
    globalThis.submitted = []; submitOperation = async intent => {submitted.push(intent); return {};};
    renderDetail = () => {}; renderNotification = () => {};`);
  if (planReady) run(`operations.push({operation_id: "prepare", status: "SUCCEEDED", updated_at: "2026-10-15T00:01:00Z",
    intent: {...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE", purpose: "stopped_execution_rescue", input_mode: "preserve_draft"},
    result: {project_id: data.request.project_id, delivery_id: data.request.id,
      checkpoint_sha256: data.request.checkpoint_sha256, execution_baseline_plan: data.plan}});`);
  return {run, ...data};
}
const render = h => h.run('const panel = document.createElement("section"); appendEngineeringStoppedExecutionRescue(panel, data.request, data.task, data.step); panel');

test("known stop and absent outcome offers a target-free check, not a provider retry", async () => {
  const h = fixture();
  const panel = render(h);
  assert.match(text(panel), /真实停止/);
  assert.doesNotMatch(text(panel), /认证失败|提供方临时故障/);
  await button(panel, "检查停止后的保留进度").events.click();
  assert.equal(h.run("submitted[0].purpose"), "stopped_execution_rescue");
  assert.equal(h.run('Object.hasOwn(submitted[0], "target_base_ref")'), false);
  assert.equal(h.run("submitted[0].input_mode"), "preserve_draft");
});

test("exact stopped plan requires PAUSE and keeps missing historical result and work debit", async () => {
  const h = fixture(true);
  const panel = render(h);
  assert.match(text(panel), /原调用结果仍未封存/);
  assert.match(text(panel), /消耗 1 次剩余开发额度/);
  assert.match(text(panel), /独立 QA 和 Review/);
  await button(panel, "批准保留进度，保持暂停").events.click();
  assert.equal(h.run("submitted[0].expected_plan_sha256"), h.plan.plan_sha256);
  assert.equal(h.run("submitted[0].continuation_mode"), "pause");
  assert.equal(h.run('Object.hasOwn(submitted[0], "confirm_local_execution_stopped")'), false);
});

test("stale scope, stop, outcome, source, proof, capability and live claim refuse old approval", async () => {
  for (const mutation of [
    'data.plan.facts.stopped_execution.capture_stop.output_present = true',
    'data.plan.facts.stopped_execution.capture_stop.process_stop.kind = "completed"',
    'data.plan.facts.stopped_execution.capture_stop.process_stop.returncode = 0',
    'data.plan.facts.stopped_execution.capture_stop.process_stop.session_proof.proof_scope = "leader_only"',
    'delete data.plan.facts.stopped_execution.capture_stop.process_stop.session_proof',
    'data.plan.facts.stopped_execution.capture_stop.cause = "provider_transient"',
    'data.plan.facts.stopped_execution.capture_stop.run_id = "run_other"',
    'data.plan.facts.stopped_execution.invocation_start.work_item_id = "work_other"',
    'data.plan.facts.continuation.stopped_execution_sha256 = "f".repeat(64)',
    'data.plan.facts.implementation_artifact_id = "artifact_other"',
    'data.plan.target_base_ref = "f".repeat(40)',
    'data.plan.facts.native_rule_change = {}',
    'data.request.checkpoint_sha256 = "f".repeat(64)',
    'data.proof.missing = ["CHECKPOINT_UNAVAILABLE"]',
    'data.step.lease_liveness = "LEASE_VALID"',
    'snapshot.selected_project_id = "project_other"',
    'consoleOperationContractVersion = 8',
    'operationsAvailable = false',
  ]) {
    const h = fixture(true);
    const panel = render(h);
    h.run(mutation);
    await button(panel, "批准保留进度，保持暂停").events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});

test("current guidance and copied report use the stopped plan while preserving original handling history", async () => {
  const h = fixture(true);
  h.run(`globalThis.copied = ""; globalThis.navigator = {clipboard: {writeText: async value => {copied = value;}}};
    data.handling = {task_id: data.task.task_id, work_item_id: data.step.work_item_id, investigation: data.proof,
      collection_failed: true, summary: "旧调查未形成可继续的记录。", handling_sha256: "6".repeat(64)};`);
  const facts = h.run('engineeringWaitCurrentFacts(data.request, data.step, data.proof, data.handling, null, null)');
  assert.match(facts.happened, /原调用结果仍未封存/);
  assert.match(facts.platform, /精确工程恢复方案/);
  await h.run('copyEngineeringWaitReport(data.request, data.handling)');
  assert.match(h.run("copied"), /当前恢复方案 · 4444/);
  assert.match(h.run("copied"), /原处理结果 · 旧调查/);
  assert.doesNotMatch(h.run("copied"), /提供方临时故障|认证失败/);
});

test("missing stop and existing retry resolution never expose stopped rescue", () => {
  for (const mutation of [
    'data.proof.missing.push("STOP_UNRECORDED")',
    'delete data.proof.process_stop_sha256',
    'data.proof.permitted_resolutions = ["RETRY_FROM_CHECKPOINT"]',
    'data.proof.interruption_receipt_sha256 = "f".repeat(64)',
    'data.proof.missing.push("BUDGET_EXHAUSTED")',
  ]) {
    const h = fixture(); h.run(mutation);
    assert.equal(render(h).children.length, 0, mutation);
  }
});
