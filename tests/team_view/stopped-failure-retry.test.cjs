const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {supportedActions} = require("./console-capabilities-fixture.cjs");

class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.events = {}; this.dataset = {}; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); for (const node of nodes) if (typeof node !== "string") node.parentNode = this; }
  get childNodes() { return this.children; }
  get lastChild() { return this.children.at(-1); }
  insertBefore(node, reference) {
    node.remove(); const index = reference === null ? this.children.length : this.children.indexOf(reference);
    this.children.splice(index, 0, node); node.parentNode = this;
  }
  moveBefore(node, reference) { this.insertBefore(node, reference); }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null;
  }
  setAttribute() {}
  addEventListener(key, callback) { this.events[key] = callback; }
  get classList() { return {add: () => {}}; }
}
const descendants = node => [node, ...node.children.filter(child => typeof child !== "string").flatMap(descendants)];
const text = node => descendants(node).map(child => child.textContent).join(" ");
const button = (node, name) => descendants(node).find(child => child.tagName === "BUTTON" && child.textContent === name);
const checkbox = node => descendants(node).find(child => child.tagName === "INPUT");

function fixture(planReady = false) {
  const facts = {task_id: "task_current", work_item_id: "work_current", role: "coder", task_intent_sha256: "b".repeat(64),
    source_revision: "c".repeat(40), checkpoint_sequence: 4, classification: "NONTRANSIENT_INFRA"};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_DEPENDENCY", lease_liveness: "UNKNOWN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering"}};
  const request = {id: "request_current", project_id: "project_current", checkpoint_sha256: "a".repeat(64), stage: "DELIVERING",
    scopes: [{delivery_id: "delivery_current"}]};
  const task = {id: "delivery_current", task_id: facts.task_id, request_id: request.id, project_id: request.project_id,
    status: "IMPLEMENTING", terminal: false, task_revision: 4, task_intent_sha256: facts.task_intent_sha256, role_queue: [step]};
  const proof = {...facts, disposition_sha256: step.wait_disposition_sha256, proof_sha256: "e".repeat(64),
    original_run_id: "run_original", invocation_outcome_sha256: "1".repeat(64),
    missing: ["CHECKPOINT_UNAVAILABLE", "OUTCOME_REJECTED"], permitted_resolutions: []};
  const original = {task_id: task.task_id, run_id: "run_original", role: "coder", source_revision: facts.source_revision};
  const stopped = {kind: "stopped_failure", proof_sha256: "2".repeat(64),
    outcome: {start: {request: original, work_item_id: step.work_item_id, checkpoint_sequence: 4},
      result: {status: "FAILED", error: {code: "PROVIDER_UNAVAILABLE", transient: false}}},
    capture_start: {request: original, task_revision: 4, start_sha256: "3".repeat(64), worktree_path: "/fixture/coder"},
    capture_stop: {task_id: task.task_id, run_id: original.run_id, capture_start_sha256: "3".repeat(64),
      process_stop: {kind: "failed", returncode: 1, session_proof: {proof_scope: "owned_session_empty", proof_sha256: "5".repeat(64)}},
      output_present: false, original_error_code: "PROVIDER_UNAVAILABLE"}};
  const plan = {purpose: "stopped_failure_retry", plan_sha256: "4".repeat(64), input_mode: "preserve_draft", conflicted: false,
    target_base_ref: "c".repeat(40), prepared_source_revision: "c".repeat(40),
    dirty_capture: {source_revision: facts.source_revision, worktree_path: "/fixture/coder"},
    facts: {task: {id: task.task_id, base_ref: "c".repeat(40), branch_name: "ai/feature/original"}, task_revision: 4,
      work_item_id: step.work_item_id, stopped_failure: stopped,
      continuation: {retry_cause: "stopped_failure_retry", stopped_failure_sha256: stopped.proof_sha256}}};
  const data = {request, task, step, proof, plan};
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data, supportedActions});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  const run = code => vm.runInContext(code, context);
  run(`snapshot = {team_id: "team_current", selected_project_id: "project_current", projects: [], agents: [], tasks: [data.task], requests: [data.request]};
    consoleTeamId = "team_current"; consoleAvailable = true; consoleDeliveryReady = true; operationsAvailable = true;
    consoleOperationContractVersion = 10; consoleSupportedActions = [...supportedActions];
    operations = [{operation_id: "inspect", status: "SUCCEEDED", updated_at: "2026-10-16T00:00:00Z",
      intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
      result: {project_id: data.request.project_id, delivery_id: data.request.id,
        checkpoint_sha256: data.request.checkpoint_sha256, engineering_wait_investigation: data.proof}}];
    globalThis.submitted = []; submitOperation = async intent => {submitted.push(intent); return {};};
    renderDetail = () => {}; renderNotification = () => {};`);
  if (planReady) run(`operations.push({operation_id: "prepare", status: "SUCCEEDED", updated_at: "2026-10-16T00:01:00Z",
    intent: {...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE", purpose: "stopped_failure_retry", input_mode: "preserve_draft"},
    result: {project_id: data.request.project_id, delivery_id: data.request.id,
      checkpoint_sha256: data.request.checkpoint_sha256, execution_baseline_plan: data.plan}});`);
  return {run, ...data};
}
const render = h => h.run('globalThis.panel = document.createElement("section"); appendEngineeringStoppedFailureRetry(panel, data.request, data.task, data.step); panel');

test("nontransient Coder wait offers a target-free platform check without an AUTH hint or repaired claim", async () => {
  const h = fixture();
  const panel = render(h);
  assert.match(text(panel), /原因仍未知/);
  assert.doesNotMatch(text(panel), /认证失败|前提已修复|平台已核验原执行已停止/);
  await button(panel, "检查失败后的保留进度").events.click();
  assert.equal(h.run("submitted[0].purpose"), "stopped_failure_retry");
  assert.equal(h.run('Object.hasOwn(submitted[0], "target_base_ref")'), false);
  assert.equal(h.run("submitted[0].input_mode"), "preserve_draft");
});

test("exact failed plan requires explicit ordinary-work decision then PAUSE with original failure retained", async () => {
  const h = fixture(true);
  const panel = render(h);
  assert.match(text(panel), /原失败记录保留/);
  assert.match(text(panel), /消耗 1 次剩余开发额度/);
  assert.match(text(panel), /独立 QA 和 Review/);
  assert.doesNotMatch(text(panel), /前提已修复|认证失败/);
  const approve = button(panel, "批准保留进度，保持暂停");
  assert.equal(approve.disabled, true); await approve.events.click();
  assert.equal(h.run("submitted.length"), 0);
  const confirm = checkbox(panel); confirm.checked = true; confirm.events.change();
  assert.equal(approve.disabled, false); await approve.events.click();
  assert.equal(h.run("submitted[0].confirm_stopped_failure_retry"), true);
  assert.equal(h.run("submitted[0].expected_plan_sha256"), h.plan.plan_sha256);
  assert.equal(h.run("submitted[0].continuation_mode"), "pause");
  assert.equal(h.run('Object.hasOwn(submitted[0], "confirm_provider_prerequisites_repaired")'), false);
});

test("stale plan, source, stop, classification, project, capability and detached controls reject old approval", async () => {
  for (const mutation of [
    'data.plan.facts.stopped_failure.outcome.result.error.code = "AUTHENTICATION_ERROR"',
    'data.plan.facts.stopped_failure.outcome.result.error.transient = true',
    'data.plan.facts.stopped_failure.outcome.result.artifact = {}',
    'data.plan.facts.stopped_failure.capture_stop.output_present = true',
    'data.plan.facts.stopped_failure.capture_stop.process_stop.kind = "completed"',
    'data.plan.facts.stopped_failure.capture_stop.process_stop.returncode = 0',
    'data.plan.facts.stopped_failure.capture_stop.process_stop.session_proof.proof_scope = "leader_only"',
    'delete data.plan.facts.stopped_failure.capture_stop.process_stop.session_proof',
    'data.plan.facts.stopped_failure.capture_stop.cause = "provider_transient"',
    'data.plan.facts.stopped_failure.capture_stop.original_error_code = "AUTHENTICATION_ERROR"',
    'data.plan.facts.stopped_failure.capture_stop.run_id = "run_other"',
    'data.plan.facts.stopped_failure.outcome.start.request.run_id = "run_other"',
    'data.plan.facts.continuation.stopped_failure_sha256 = "f".repeat(64)',
    'data.plan.facts.stopped_provider_failure = {}',
    'data.plan.facts.stopped_execution = {}',
    'data.plan.facts.completed_output = {}',
    'data.plan.facts.native_rule_change = {}',
    'data.plan.facts.implementation_artifact_id = "artifact_other"',
    'data.plan.target_base_ref = "f".repeat(40)',
    'data.plan.plan_sha256 = "f".repeat(64)',
    'data.request.checkpoint_sha256 = "f".repeat(64)',
    'data.step.wait_disposition.facts.classification = "TRANSIENT_INFRA"',
    'data.step.lease_liveness = "LEASE_VALID"',
    'snapshot.selected_project_id = "project_other"',
    'consoleOperationContractVersion = 9',
    'operationsAvailable = false',
  ]) {
    const h = fixture(true); const panel = render(h); const confirm = checkbox(panel);
    confirm.checked = true; confirm.events.change(); h.run(mutation);
    await button(panel, "批准保留进度，保持暂停").events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
  const h = fixture(true); const panel = render(h); const confirm = checkbox(panel);
  confirm.checked = true; confirm.events.change(); button(panel, "批准保留进度，保持暂停").isConnected = false;
  await button(panel, "批准保留进度，保持暂停").events.click(); assert.equal(h.run("submitted.length"), 0);
});

test("copied report uses current unknown-failure plan and retains historical handling", async () => {
  const h = fixture(true);
  h.run(`globalThis.copied = ""; globalThis.navigator = {clipboard: {writeText: async value => {copied = value;}}};
    data.handling = {task_id: data.task.task_id, work_item_id: data.step.work_item_id, investigation: data.proof,
      collection_failed: true, summary: "旧调查未形成继续方案。", handling_sha256: "6".repeat(64)};`);
  const facts = h.run('engineeringWaitCurrentFacts(data.request, data.step, data.proof, data.handling, null, null)');
  assert.match(facts.happened, /原因仍未知/); assert.match(facts.platform, /普通工作额度/);
  await h.run('copyEngineeringWaitReport(data.request, data.handling)');
  assert.match(h.run("copied"), /当前恢复方案 · 4444/); assert.match(h.run("copied"), /原处理结果 · 旧调查/);
  assert.doesNotMatch(h.run("copied"), /前提已修复|认证失败/);
});

test("foreign or exhausted waits do not expose failed-retry controls", () => {
  for (const mutation of ['data.proof.provider_failure_code = "AUTHENTICATION_ERROR"',
    'data.proof.permitted_resolutions = ["RETRY_FROM_CHECKPOINT"]', 'data.proof.missing.push("BUDGET_EXHAUSTED")',
    'data.proof.knowledge_preparation = {}', 'data.step.role = "qa"', 'data.task.project_id = "project_other"']) {
    const h = fixture(); h.run(mutation); assert.equal(render(h).children.length, 0, mutation);
  }
});

test("generic source update submission cannot authorize the new failure proof", async () => {
  const h = fixture(true);
  h.run(`data.plan.purpose = "source_rebind"; operations[1].intent.purpose = "source_rebind";
    operations[1].intent.target_base_ref = data.plan.target_base_ref;`);
  assert.equal(h.run('engineeringBaselinePlan(data.request, data.task, data.step)'), null);
  await h.run(`submitEngineeringBaselineOperation({action: "EXECUTE_EXECUTION_BASELINE", project_id: data.request.project_id,
    delivery_id: data.request.id, expected_checkpoint_sha256: data.request.checkpoint_sha256,
    task_id: data.task.task_id, expected_plan_sha256: data.plan.plan_sha256, continuation_mode: "pause"},
    engineeringBaselineFacts(data.request, data.task, data.step))`);
  assert.equal(h.run("submitted.length"), 0);
});

test("same-plan polling preserves explicit confirmation while a new plan replaces controls and resets consent", async () => {
  const h = fixture(true); const panel = render(h); const confirm = checkbox(panel);
  confirm.checked = true; confirm.events.change();
  const oldApprove = button(panel, "批准保留进度，保持暂停");
  h.run('globalThis.currentPanel = panel; globalThis.nextPanel = document.createElement("section"); appendEngineeringStoppedFailureRetry(nextPanel, data.request, data.task, data.step); reconcileViewChildren(currentPanel, nextPanel)');
  assert.equal(checkbox(panel), confirm); assert.equal(confirm.checked, true);
  assert.equal(button(panel, "批准保留进度，保持暂停"), oldApprove);
  h.run('data.plan.plan_sha256 = "6".repeat(64); nextPanel = document.createElement("section"); appendEngineeringStoppedFailureRetry(nextPanel, data.request, data.task, data.step); reconcileViewChildren(currentPanel, nextPanel)');
  assert.notEqual(checkbox(panel), confirm); assert.equal(checkbox(panel).checked, false);
  assert.equal(button(panel, "批准保留进度，保持暂停").disabled, true);
  await oldApprove.events.click(); assert.equal(h.run("submitted.length"), 0);
});

test("retained check rejects older capability, navigation and target override before POST", async () => {
  for (const mutation of ['consoleOperationContractVersion = 9', 'snapshot.selected_project_id = "project_other"',
    'data.request.checkpoint_sha256 = "f".repeat(64)', 'data.step.lease_liveness = "LEASE_VALID"']) {
    const h = fixture(); const panel = render(h); h.run(mutation);
    await button(panel, "检查失败后的保留进度").events.click(); assert.equal(h.run("submitted.length"), 0, mutation);
  }
  const h = fixture();
  await h.run(`submitEngineeringStoppedFailureRetry({...engineeringBaselineFacts(data.request, data.task, data.step),
    action: "PROPOSE_EXECUTION_BASELINE", purpose: "stopped_failure_retry", input_mode: "preserve_draft", target_base_ref: "c".repeat(40)},
    engineeringBaselineFacts(data.request, data.task, data.step))`);
  assert.equal(h.run("submitted.length"), 0);
});
