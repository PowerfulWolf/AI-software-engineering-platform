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

function fixture(planReady = false, classification = "TRANSIENT_INFRA") {
  const facts = {task_id: "task_current", work_item_id: "work_current", role: "coder", task_intent_sha256: "b".repeat(64),
    source_revision: "c".repeat(40), checkpoint_sequence: 4, classification};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_DEPENDENCY", lease_liveness: "UNKNOWN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering"}};
  const request = {id: "request_current", project_id: "project_current", checkpoint_sha256: "a".repeat(64), stage: "DELIVERING",
    scopes: [{delivery_id: "delivery_current"}]};
  const task = {id: "delivery_current", task_id: facts.task_id, request_id: request.id, project_id: request.project_id,
    status: "IMPLEMENTING", terminal: false, task_revision: 4, task_intent_sha256: facts.task_intent_sha256, role_queue: [step]};
  const proof = {...facts, disposition_sha256: step.wait_disposition_sha256, proof_sha256: "e".repeat(64),
    provider_failure_code: "AUTHENTICATION_ERROR", original_run_id: "run_original", invocation_outcome_sha256: "1".repeat(64),
    missing: ["CHECKPOINT_UNAVAILABLE", "OUTCOME_REJECTED"], permitted_resolutions: []};
  const original = {task_id: task.task_id, run_id: "run_original", role: "coder", source_revision: facts.source_revision};
  const stopped = {kind: "stopped_provider_failure", proof_sha256: "2".repeat(64),
    outcome: {start: {request: original, work_item_id: step.work_item_id, checkpoint_sequence: 4},
      result: {status: "FAILED", error: {code: "AUTHENTICATION_ERROR", transient: false}}},
    capture_start: {request: original, task_revision: 4, start_sha256: "3".repeat(64), worktree_path: "/fixture/coder"},
    capture_stop: {task_id: task.task_id, run_id: original.run_id, capture_start_sha256: "3".repeat(64),
      process_stop: {kind: "failed", returncode: 1}, output_present: false, original_error_code: "AUTHENTICATION_ERROR"}};
  const plan = {purpose: "stopped_provider_retry", plan_sha256: "4".repeat(64), input_mode: "preserve_draft", conflicted: false,
    target_base_ref: "c".repeat(40), prepared_source_revision: "c".repeat(40),
    dirty_capture: {source_revision: facts.source_revision, worktree_path: "/fixture/coder"},
    facts: {task: {id: task.task_id, base_ref: "c".repeat(40), branch_name: "ai/feature/original"}, task_revision: 4,
      work_item_id: step.work_item_id, stopped_provider_failure: stopped,
      continuation: {retry_cause: "provider_prerequisite_repaired", stopped_provider_failure_sha256: stopped.proof_sha256}}};
  const data = {request, task, step, proof, plan};
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data, supportedActions});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  const run = code => vm.runInContext(code, context);
  run(`snapshot = {team_id: "team_current", selected_project_id: "project_current", projects: [], agents: [], tasks: [data.task], requests: [data.request]};
    consoleTeamId = "team_current"; consoleAvailable = true; consoleDeliveryReady = true; operationsAvailable = true;
    consoleOperationContractVersion = 6; consoleSupportedActions = [...supportedActions];
    operations = [{operation_id: "inspect", status: "SUCCEEDED", updated_at: "2026-10-12T00:00:00Z",
      intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
      result: {project_id: data.request.project_id, delivery_id: data.request.id,
        checkpoint_sha256: data.request.checkpoint_sha256, engineering_wait_investigation: data.proof}}];
    globalThis.submitted = []; submitOperation = async intent => {submitted.push(intent); return {};};
    renderDetail = () => {}; renderNotification = () => {};`);
  if (planReady) run(`operations.push({operation_id: "prepare", status: "SUCCEEDED", updated_at: "2026-10-12T00:01:00Z",
    intent: {...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE", purpose: "stopped_provider_retry", input_mode: "preserve_draft"},
    result: {project_id: data.request.project_id, delivery_id: data.request.id,
      checkpoint_sha256: data.request.checkpoint_sha256, execution_baseline_plan: data.plan}});`);
  return {run, ...data};
}

test("nontransient classification retains exact provider proof and explicit approval gates", async () => {
  const h = fixture(true, "NONTRANSIENT_INFRA");
  const panel = h.run('const panel = document.createElement("section"); appendEngineeringStoppedProviderRetry(panel, data.request, data.task, data.step); panel');
  const approve = button(panel, "确认前提已修复，保留进度");
  assert.ok(approve.disabled);
  await approve.events.click(); assert.equal(h.run("submitted.length"), 0);
  const confirmation = descendants(panel).find(child => child.tagName === "INPUT");
  confirmation.checked = true; confirmation.events.change();
  h.run('data.plan.facts.stopped_provider_failure.capture_stop.process_stop.kind = "unknown"');
  await approve.events.click(); assert.equal(h.run("submitted.length"), 0);
  h.run('data.plan.facts.stopped_provider_failure.capture_stop.process_stop.kind = "failed"');
  await approve.events.click(); assert.equal(h.run("submitted[0].confirm_provider_prerequisites_repaired"), true);
});

test("new failure prefix is localized without treating unknown exits as authentication failures", () => {
  const h = fixture();
  assert.match(h.run('humanizeBlockingText("NONTRANSIENT_INFRA: Coder failed at attempt 1: coder run run_original failed: Codex CLI provider execution failed")'), /Coder 第 1 次执行失败.*原始诊断|Coder 第 1 次执行失败.*模型服务执行失败/);
  assert.equal(h.run('humanizeBlockingText("NONTRANSIENT_INFRA: coder knowledge preparation failed: PROVIDER_UNAVAILABLE")'), "Coder 知识准备失败（原因代码：PROVIDER_UNAVAILABLE），请检查模型服务后再继续。");
});
function sourceRebindFixture(h, rules = false) {
  h.run(`data.plan.purpose = "source_rebind"; data.plan.target_base_ref = data.plan.prepared_source_revision = "f".repeat(40);
    operations[1].intent.purpose = "source_rebind"; operations[1].intent.target_base_ref = data.plan.target_base_ref;`);
  if (rules) h.plan.facts.native_rule_change = {change_sha256: "7".repeat(64), changes: [
    {path: "AGENTS.md", change: "modified"},
  ]};
  return h;
}

test("provider preparation uses one target-free check without claiming the prerequisites fixed", async () => {
  const h = fixture();
  const panel = h.run('const panel = document.createElement("section"); appendEngineeringStoppedProviderRetry(panel, data.request, data.task, data.step); panel');
  assert.match(text(panel), /平台将核验/);
  assert.doesNotMatch(text(panel), /平台已核验原执行已停止/);
  await button(panel, "准备保留进度的续跑方案").events.click();
  assert.equal(h.run("submitted[0].purpose"), "stopped_provider_retry");
  assert.equal(h.run('Object.hasOwn(submitted[0], "target_base_ref")'), false);
});

test("approval needs current explicit prerequisite confirmation and preserves failure and budget", async () => {
  const h = fixture(true);
  const panel = h.run('const panel = document.createElement("section"); appendEngineeringStoppedProviderRetry(panel, data.request, data.task, data.step); panel');
  assert.match(text(panel), /认证失败/); assert.match(text(panel), /消耗 1 次剩余开发额度/);
  assert.match(text(panel), /原失败记录/); assert.match(text(panel), /独立 QA 和 Review/);
  const approve = button(panel, "确认前提已修复，保留进度");
  assert.ok(approve.disabled);
  await approve.events.click(); assert.equal(h.run("submitted.length"), 0);
  const confirmation = descendants(panel).find(child => child.tagName === "INPUT");
  confirmation.checked = true; confirmation.events.change();
  assert.equal(approve.disabled, false);
  await approve.events.click();
  assert.equal(h.run("submitted[0].confirm_provider_prerequisites_repaired"), true);
  assert.equal(h.run("submitted[0].continuation_mode"), "pause");
  assert.equal(h.run("submitted[0].expected_plan_sha256"), h.plan.plan_sha256);
});

test("stale failure, scope, plan, capability and unchecked callbacks cannot approve", async () => {
  for (const mutation of ['data.plan.facts.stopped_provider_failure.outcome.result.error.code = "POLICY_VIOLATION"',
    'data.plan.facts.stopped_provider_failure.capture_stop.run_id = "run_other"',
    'data.plan.facts.stopped_provider_failure.capture_stop.process_stop.kind = "completed"',
    'data.plan.facts.stopped_provider_failure.capture_stop.process_stop.returncode = 0',
    'data.plan.facts.stopped_provider_failure.capture_stop.output_present = true',
    'data.plan.facts.stopped_provider_failure.capture_stop.original_error_code = "POLICY_VIOLATION"',
    'data.plan.facts.stopped_provider_failure.outcome.result.artifact = {}',
    'data.plan.target_base_ref = "f".repeat(40)', 'data.step.wait_disposition.facts.source_revision = "f".repeat(40)',
    'data.request.checkpoint_sha256 = "f".repeat(64)', 'snapshot.selected_project_id = "project_other"',
    'consoleOperationContractVersion = 5', 'operationsAvailable = false']) {
    const h = fixture(true);
    const panel = h.run('const panel = document.createElement("section"); appendEngineeringStoppedProviderRetry(panel, data.request, data.task, data.step); panel');
    const confirmation = descendants(panel).find(child => child.tagName === "INPUT");
    confirmation.checked = true; confirmation.events.change();
    h.run(mutation);
    await button(panel, "确认前提已修复，保留进度").events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});

test("source updates carrying the original provider failure also require explicit prerequisite confirmation", async () => {
  const h = fixture(true);
  h.run(`data.plan.purpose = "source_rebind"; data.plan.target_base_ref = data.plan.prepared_source_revision = "f".repeat(40);
    operations[1].intent.purpose = "source_rebind"; operations[1].intent.target_base_ref = data.plan.target_base_ref;`);
  const panel = h.run('const panel = document.createElement("section"); appendEngineeringBaseline(panel, data.request, data.task, data.step); panel');
  const approve = button(panel, "批准更新基线，保持暂停"); assert.ok(approve.disabled);
  await approve.events.click(); assert.equal(h.run("submitted.length"), 0);
  const confirmation = descendants(panel).find(node => node.tagName === "INPUT" && node.type === "checkbox");
  confirmation.checked = true; confirmation.events.change(); assert.equal(approve.disabled, false);
  await approve.events.click();
  assert.equal(h.run("submitted[0].confirm_provider_prerequisites_repaired"), true);
  assert.equal(h.run("submitted[0].continuation_mode"), "pause");
  assert.equal(h.run("submitted[0].expected_plan_sha256"), h.plan.plan_sha256);
});

test("copied report prioritizes the current provider plan and keeps the failed investigation as history", async () => {
  const h = fixture(true);
  h.run(`globalThis.copied = ""; globalThis.navigator = {clipboard: {writeText: async value => {copied = value;}}};
    data.handling = {task_id: data.task.task_id, work_item_id: data.step.work_item_id, investigation: data.proof,
      collection_failed: true, collection_failure: "WORKSPACE_CAPTURE_REJECTED",
      summary: "旧调查未形成继续方案。", user_action: "旧维护处理建议。", handling_sha256: "6".repeat(64)};`);
  await h.run('copyEngineeringWaitReport(data.request, data.handling)');
  const report = h.run("copied");
  assert.match(report, /当前原因 · 原模型调用记录为认证失败/);
  assert.match(report, /当前续跑方案/); assert.match(report, /原调查记录事项/);
  assert.match(report, /原处理结果 · /); assert.doesNotMatch(report, /当前结果 · /);
  assert.match(report, /用户操作 · 先修复或核验原认证/);
  assert.doesNotMatch(report, /用户操作 · 旧维护处理建议/);
});

// DomainModel.to_wire() excludes absent optional fields at every nested level.
test("canonical omitted artifact and explicit null both preserve an exact failed plan", () => {
  for (const explicitNull of [false, true]) {
    const h = fixture(true);
    if (explicitNull) h.run("data.plan.facts.stopped_provider_failure.outcome.result.artifact = null");
    const plan = h.run('engineeringBaselinePlan(data.request, data.task, data.step, "stopped_provider_retry")');
    assert.equal(plan?.plan_sha256, h.plan.plan_sha256);
  }
});

test("a current source-rebind provider plan supplies the displayed decision and copied next action", async () => {
  const h = sourceRebindFixture(fixture(true), true);
  const panel = h.run('const panel = document.createElement("section"); appendEngineeringBaseline(panel, data.request, data.task, data.step); appendEngineeringStoppedProviderRetry(panel, data.request, data.task, data.step); panel');
  assert.ok(button(panel, "批准更新基线，保持暂停"));
  assert.equal(button(panel, "准备保留进度的续跑方案"), undefined);
  const current = h.run('engineeringWaitCurrentFacts(data.request, data.step, data.proof, null, null, null)');
  assert.match(current.preservation, /完整封存/);
  assert.match(current.user, /批准更新基线，保持暂停/);
  assert.doesNotMatch(current.user, /准备保留进度的续跑方案/);
  h.run(`globalThis.copied = ""; globalThis.navigator = {clipboard: {writeText: async value => {copied = value;}}};
    data.handling = {task_id: data.task.task_id, work_item_id: data.step.work_item_id, investigation: data.proof,
      collection_failed: true, collection_failure: "WORKSPACE_CAPTURE_REJECTED", summary: "旧封存失败。", handling_sha256: "6".repeat(64)};`);
  await h.run('copyEngineeringWaitReport(data.request, data.handling)');
  const report = h.run("copied");
  assert.match(report, /当前续跑方案 · 4444/);
  assert.match(report, /目标代码版本 · f{40}/);
  assert.match(report, /原处理结果 · /);
  assert.match(report, /完整项目规范变更/);
  assert.match(report, /批准更新基线，保持暂停/);
  assert.doesNotMatch(report, /当前结果 · |用户操作 · .*准备保留进度的续跑方案/);
});

test("source-rebind provider approval requires independent prerequisite and reviewed native-rule consent", async () => {
  const h = sourceRebindFixture(fixture(true), true);
  let panel = h.run('const panel = document.createElement("section"); appendEngineeringBaseline(panel, data.request, data.task, data.step); panel');
  let checks = descendants(panel).filter(node => node.tagName === "INPUT" && node.type === "checkbox");
  assert.equal(checks.length, 2);
  checks.forEach(check => {check.checked = true; check.events.change();});
  await button(panel, "批准更新基线，保持暂停").events.click();
  assert.equal(h.run("submitted.length"), 0, "unread full rules cannot be approved through forged checkbox events");
  h.run('saveNativeRuleReview(data.plan, "AGENTS.md", {status: "READY", inspection: {unified_diff: "full exact native rule change"}})');
  panel = h.run('const fresh = document.createElement("section"); appendEngineeringBaseline(fresh, data.request, data.task, data.step); fresh');
  checks = descendants(panel).filter(node => node.tagName === "INPUT" && node.type === "checkbox");
  assert.equal(checks.every(check => check.checked === false), true);
  const approve = button(panel, "批准更新基线，保持暂停");
  for (const [provider, rules] of [[true, false], [false, true]]) {
    checks[0].checked = provider; checks[1].checked = rules; checks.forEach(check => check.events.change());
    assert.equal(approve.disabled, true);
    await approve.events.click(); assert.equal(h.run("submitted.length"), 0);
  }
  checks.forEach(check => {check.checked = true; check.events.change();});
  assert.equal(approve.disabled, false); await approve.events.click();
  assert.equal(h.run("submitted.length"), 1);
  assert.equal(h.run("submitted[0].expected_plan_sha256"), h.plan.plan_sha256);
  assert.equal(h.run("submitted[0].approved_native_rule_change_sha256"), "7".repeat(64));
  assert.equal(h.run("submitted[0].confirm_provider_prerequisites_repaired"), true);
  assert.equal(h.run("submitted[0].continuation_mode"), "pause");
  assert.equal(h.run('Object.hasOwn(submitted[0], "purpose")'), false, "execute retains its original plan contract");
});

test("only the newest exact provider plan controls guidance across source and same-source purposes", () => {
  const h = sourceRebindFixture(fixture(true));
  h.run(`const earlier = JSON.parse(JSON.stringify(operations[1])); earlier.operation_id = "earlier";
    earlier.updated_at = "2026-10-12T00:00:30Z"; earlier.intent.purpose = "stopped_provider_retry";
    delete earlier.intent.target_base_ref; earlier.result.execution_baseline_plan.purpose = "stopped_provider_retry";
    earlier.result.execution_baseline_plan.plan_sha256 = "8".repeat(64);
    earlier.result.execution_baseline_plan.target_base_ref = earlier.result.execution_baseline_plan.prepared_source_revision = "c".repeat(40);
    operations.push(earlier);`);
  let facts = h.run('engineeringWaitCurrentFacts(data.request, data.step, data.proof, null, null, null)');
  assert.match(facts.user, /批准更新基线，保持暂停/);
  h.run('earlier.updated_at = "2026-10-12T00:02:00Z"');
  facts = h.run('engineeringWaitCurrentFacts(data.request, data.step, data.proof, null, null, null)');
  assert.doesNotMatch(facts.user, /批准更新基线/);
  h.run('earlier.intent.project_id = "project_other"');
  facts = h.run('engineeringWaitCurrentFacts(data.request, data.step, data.proof, null, null, null)');
  assert.match(facts.user, /批准更新基线，保持暂停/);
});

test("foreign, invalid and unrelated source plans cannot replace provider preparation", () => {
  for (const mutation of ['operations[1].intent.project_id = "project_other"',
    'data.plan.facts.stopped_provider_failure.capture_stop.run_id = "run_other"',
    'delete data.plan.facts.stopped_provider_failure']) {
    const h = sourceRebindFixture(fixture(true)); h.run(mutation);
    const panel = h.run('const panel = document.createElement("section"); appendEngineeringStoppedProviderRetry(panel, data.request, data.task, data.step); panel');
    assert.ok(button(panel, "准备保留进度的续跑方案"), mutation);
    assert.doesNotMatch(text(panel), /平台已核验原执行已停止/);
  }
});

test("an old same-source callback cannot submit after a newer exact source-rebind plan", async () => {
  const h = fixture(true);
  const panel = h.run('const panel = document.createElement("section"); appendEngineeringStoppedProviderRetry(panel, data.request, data.task, data.step); panel');
  const confirmation = descendants(panel).find(node => node.tagName === "INPUT");
  confirmation.checked = true; confirmation.events.change();
  h.run(`const next = JSON.parse(JSON.stringify(operations[1])); next.operation_id = "source_next";
    next.updated_at = "2026-10-12T00:02:00Z"; next.intent.purpose = "source_rebind";
    next.intent.target_base_ref = "f".repeat(40); next.result.execution_baseline_plan.purpose = "source_rebind";
    next.result.execution_baseline_plan.plan_sha256 = "9".repeat(64);
    next.result.execution_baseline_plan.target_base_ref = next.result.execution_baseline_plan.prepared_source_revision = "f".repeat(40);
    operations.push(next);`);
  await button(panel, "确认前提已修复，保留进度").events.click();
  assert.equal(h.run("submitted.length"), 0);
});
