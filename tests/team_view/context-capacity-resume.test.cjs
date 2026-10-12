const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {supportedActions} = require("./console-capabilities-fixture.cjs");

class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.events = {}; this.dataset = {}; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); for (const node of nodes) if (typeof node !== "string") node.parentNode = this; }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(key, callback) { this.events[key] = callback; }
  get classList() { return {add: () => {}}; }
}
const descendants = node => [node, ...node.children.filter(child => typeof child !== "string").flatMap(descendants)];
const visible = node => [node, ...node.children.filter(child => typeof child !== "string" && !child.hidden &&
  (node.tagName !== "DETAILS" || node.open === true || child.tagName === "SUMMARY")).flatMap(visible)];
const text = node => visible(node).map(child => child.textContent).join(" ");
const button = (node, name) => descendants(node).find(child => child.tagName === "BUTTON" && child.textContent === name);

function fixture({ready = false, version = 8} = {}) {
  const facts = {task_id: "task_current", work_item_id: "work_current", role: "coder", classification: "CONTEXT_CAPACITY",
    task_intent_sha256: "b".repeat(64), source_revision: "c".repeat(40), checkpoint_sequence: 4,
    evidence_ids: ["context-capacity://" + "e".repeat(64)]};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_DEPENDENCY", lease_liveness: "UNKNOWN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering", reason: "输入超过模型容量。"}};
  const request = {id: "request_current", title: "原需求", project_id: "project_current", checkpoint_sha256: "a".repeat(64),
    stage: "DELIVERING", scopes: [{delivery_id: "delivery_current"}]};
  const task = {id: "delivery_current", task_id: facts.task_id, request_id: request.id, project_id: request.project_id,
    status: "IMPLEMENTING", terminal: false, task_revision: 4, task_intent_sha256: facts.task_intent_sha256, role_queue: [step]};
  const plan = {purpose: "context_capacity_resume", plan_sha256: "f".repeat(64), input_mode: "preserve_draft", conflicted: false,
    target_base_ref: "9".repeat(40), prepared_source_revision: facts.source_revision,
    dirty_capture: {source_revision: facts.source_revision, worktree_path: "/fixture/coder"},
    facts: {task: {id: task.task_id, base_ref: "9".repeat(40), branch_name: "ai/feature/original"}, task_revision: 4,
      work_item_id: step.work_item_id, context_capacity_receipt_sha256: "e".repeat(64)}};
  const data = {request, task, step, plan, version};
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data, supportedActions});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  const run = code => vm.runInContext(code, context);
  run(`snapshot = {team_id: "team_current", selected_project_id: "project_current", projects: [], agents: [], tasks: [data.task], requests: [data.request]};
    consoleTeamId = "team_current"; consoleAvailable = true; consoleDeliveryReady = true; operationsAvailable = true;
    consoleOperationContractVersion = data.version; consoleSupportedActions = [...supportedActions]; operations = [];
    globalThis.submitted = []; submitOperation = async intent => {submitted.push(intent); return {};};
    renderDetail = () => {}; renderNotification = () => {};`);
  if (ready) run(`operations.push({operation_id: "prepare", status: "SUCCEEDED", updated_at: "2026-10-12T00:01:00Z",
    intent: {...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE", purpose: "context_capacity_resume", input_mode: "preserve_draft"},
    result: {project_id: data.request.project_id, delivery_id: data.request.id,
      checkpoint_sha256: data.request.checkpoint_sha256, execution_baseline_plan: data.plan}});`);
  return {run, ...data, panel: () => run("engineeringWaitBox(data.request, data.task, data.step)")};
}

test("capacity wait offers one visible target-free preparation for the original requirement", async () => {
  const h = fixture(); const panel = h.panel();
  assert.match(text(panel), /输入超过模型容量/);
  assert.match(text(panel), /完整现场|完整进度/);
  assert.match(text(panel), /主开发调用尚未开始/);
  assert.equal(visible(panel).filter(node => node.tagName === "INPUT").length, 0);
  const prepare = button(panel, "准备保留进度的恢复方案"); assert.ok(visible(panel).includes(prepare));
  await prepare.events.click();
  assert.deepEqual(JSON.parse(h.run("JSON.stringify(submitted[0])")), {
    ...JSON.parse(h.run("JSON.stringify(engineeringBaselineFacts(data.request, data.task, data.step))")),
    action: "PROPOSE_EXECUTION_BASELINE", purpose: "context_capacity_resume", input_mode: "preserve_draft",
  });
  assert.equal(h.run('Object.hasOwn(submitted[0], "target_base_ref")'), false);
});

test("exact ready capacity plan has explicit PAUSE approval without a process or provider attestation", async () => {
  const h = fixture({ready: true}); const panel = h.panel();
  assert.match(text(panel), /完整合法开发进度已封存/);
  assert.match(text(panel), /代码版本保持/);
  assert.doesNotMatch(text(panel), /更新执行基线|已启动|已经完成需求/);
  assert.equal(visible(panel).filter(node => node.tagName === "INPUT").length, 0);
  await button(panel, "批准保留进度，保持暂停").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[0])"));
  assert.deepEqual(intent, {action: "EXECUTE_EXECUTION_BASELINE", project_id: h.request.project_id, delivery_id: h.request.id,
    expected_checkpoint_sha256: h.request.checkpoint_sha256, task_id: h.task.task_id,
    expected_plan_sha256: h.plan.plan_sha256, continuation_mode: "pause", reference: intent.reference});
  assert.match(intent.reference, /代码版本保持/);
  assert.equal(button(panel, "继续原需求"), undefined);
});

test("old server and withdrawn capabilities do not advertise or submit the new purpose", async () => {
  for (const version of [1, 7]) {
    const h = fixture({version}); const panel = h.panel();
    assert.equal(button(panel, "准备保留进度的恢复方案"), undefined);
    assert.match(text(panel), /当前服务.*不支持/);
    assert.match(text(panel), /服务空闲.*更新.*刷新原需求/);
    assert.equal(h.run("submitted.length"), 0);
  }
  for (const change of ['consoleOperationContractVersion = 7', 'consoleSupportedActions = []', 'operationsAvailable = false']) {
    const h = fixture(); const prepare = button(h.panel(), "准备保留进度的恢复方案");
    h.run(change); await prepare.events.click(); assert.equal(h.run("submitted.length"), 0, change);
  }
});

test("stale Task, source, checkpoint, receipt, disposition, project and detached controls cannot approve", async () => {
  for (const change of [
    'data.task.task_revision = 5', 'data.step.wait_disposition.facts.source_revision = "8".repeat(40)',
    'data.request.checkpoint_sha256 = "8".repeat(64)', 'data.step.wait_disposition.facts.evidence_ids = ["context-capacity://" + "8".repeat(64)]',
    'data.step.wait_disposition_sha256 = "8".repeat(64)', 'snapshot.selected_project_id = "project_other"',
    'operations[0].result.execution_baseline_plan.plan_sha256 = "8".repeat(64)',
    'data.task.status = "QA"', 'data.step.lease_liveness = "LEASE_VALID"',
    'data.step.wait_disposition.facts.role = "qa"', 'data.step.status = "READY"',
    'data.task.project_id = "project_other"', 'data.task.request_id = "request_other"',
    'data.request.stage = "DONE"',
  ]) {
    const h = fixture({ready: true}); const approve = button(h.panel(), "批准保留进度，保持暂停");
    h.run(change); await approve.events.click(); assert.equal(h.run("submitted.length"), 0, change);
  }
  const h = fixture({ready: true}); const approve = button(h.panel(), "批准保留进度，保持暂停");
  approve.isConnected = false; await approve.events.click(); assert.equal(h.run("submitted.length"), 0);
});

test("altered execute project or attestation fields cannot escape the exact capacity approval", async () => {
  for (const extra of [
    {project_id: "project_other"}, {target_base_ref: "8".repeat(40)},
    {confirm_provider_prerequisites_repaired: true}, {confirm_local_execution_stopped: true},
    {approved_native_rule_change_sha256: "8".repeat(64)}, {confirm_legacy_containment: true},
    {continuation_mode: "continue"},
  ]) {
    const h = fixture({ready: true});
    h.run(`globalThis.altered = ${JSON.stringify(extra)}`);
    await h.run(`submitEngineeringContextCapacityOperation({action: "EXECUTE_EXECUTION_BASELINE",
      project_id: data.request.project_id, delivery_id: data.request.id, task_id: data.task.task_id,
      expected_checkpoint_sha256: data.request.checkpoint_sha256, expected_plan_sha256: data.plan.plan_sha256,
      continuation_mode: "pause", reference: "精确批准", ...altered},
      engineeringContextCapacityFacts(data.request, data.task, data.step))`);
    assert.equal(h.run("submitted.length"), 0, JSON.stringify(extra));
  }
  for (const extra of [{target_base_ref: "9".repeat(40)}, {confirm_local_execution_stopped: true},
    {confirm_provider_prerequisites_repaired: true}]) {
    const h = fixture(); h.run(`globalThis.altered = ${JSON.stringify(extra)}`);
    await h.run(`submitEngineeringContextCapacityOperation({
      ...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE",
      purpose: "context_capacity_resume", input_mode: "preserve_draft", ...altered},
      engineeringContextCapacityFacts(data.request, data.task, data.step))`);
    assert.equal(h.run("submitted.length"), 0, JSON.stringify(extra));
  }
});

test("incomplete capacity facts retain progress without claiming a verified no-start or approval", () => {
  for (const change of [
    'data.step.wait_disposition.facts.role = "qa"', 'data.step.wait_disposition.facts.evidence_ids = []',
    'data.step.wait_disposition_sha256 = "invalid"', 'data.task.project_id = "project_other"',
    'data.request.checkpoint_sha256 = "invalid"',
  ]) {
    const h = fixture(); h.run(change); const panel = h.panel();
    assert.match(text(panel), /容量等待记录不完整/);
    assert.match(text(panel), /原需求和进度保留/);
    assert.doesNotMatch(text(panel), /主开发调用尚未开始|已封存/);
    assert.equal(button(panel, "准备保留进度的恢复方案"), undefined);
    assert.equal(button(panel, "批准保留进度，保持暂停"), undefined);
  }
});

test("malformed or mixed-proof plans never become capacity approvals", () => {
  for (const change of [
    'data.plan.purpose = "source_rebind"', 'data.plan.target_base_ref = "8".repeat(40)',
    'data.plan.prepared_source_revision = "8".repeat(40)', 'data.plan.input_mode = "coder_reapply"',
    'data.plan.facts.context_capacity_receipt_sha256 = "8".repeat(64)',
    'data.plan.facts.native_rule_change = {}', 'data.plan.facts.stopped_provider_failure = {}',
    'data.plan.facts.completed_output = {}', 'data.plan.facts.legacy_containment = {}',
    'data.plan.conflicted = true', 'operations[0].intent.target_base_ref = data.plan.target_base_ref',
  ]) {
    const h = fixture({ready: true}); h.run(change);
    assert.equal(button(h.panel(), "批准保留进度，保持暂停"), undefined, change);
  }
});

test("preparation failure and running operation retain readable next steps without approval", () => {
  const failed = fixture({ready: true}); failed.run('operations[0].status = "FAILED"; operations[0].error_summary = "完整现场核验未通过。"');
  assert.match(text(failed.panel()), /完整现场核验未通过/);
  assert.ok(button(failed.panel(), "重新准备保留进度的恢复方案"));
  assert.equal(button(failed.panel(), "批准保留进度，保持暂停"), undefined);
  const running = fixture({ready: true}); running.run('operations[0].status = "RUNNING"; operations[0].action = "PROPOSE_EXECUTION_BASELINE"; operations[0].project_id = data.request.project_id; operations[0].delivery_id = data.request.id');
  const panel = running.panel(); assert.match(text(panel), /操作执行中/);
  assert.equal(button(panel, "批准保留进度，保持暂停"), undefined);
  assert.equal(button(panel, "准备保留进度的恢复方案"), undefined);
});

test("paused capacity binding resumes separately and operation history does not claim a source update", async () => {
  const h = fixture({ready: true});
  h.run(`data.step.status = "WAITING_HUMAN"; data.step.wait_disposition.facts.classification = "EXECUTION_BASELINE_PAUSED";
    data.step.wait_disposition.facts.execution_baseline_sha256 = "6".repeat(64); data.step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
    operations.push({operation_id: "approved", action: "EXECUTE_EXECUTION_BASELINE", status: "SUCCEEDED", updated_at: "2026-10-12T00:02:00Z",
      intent: {action: "EXECUTE_EXECUTION_BASELINE", project_id: data.request.project_id, delivery_id: data.request.id, task_id: data.task.task_id,
        expected_plan_sha256: data.plan.plan_sha256, continuation_mode: "pause"},
      result: {project_id: data.request.project_id, delivery_id: data.request.id,
        execution_baseline_binding: {purpose: "context_capacity_resume"}}});`);
  const panel = h.panel(); await button(panel, "继续原需求").events.click();
  assert.equal(h.run("submitted[0].action"), "RESUME_EXECUTION_BASELINE");
  assert.equal(h.run("submitted[0].expected_execution_baseline_sha256"), "6".repeat(64));
  assert.equal(h.run("operationActionLabel(operations[1])"), "批准保留进度，保持暂停");
  assert.doesNotMatch(h.run("operationPurpose(operations[1])"), /更新/);
  assert.match(h.run("operationPurpose(operations[1])"), /代码版本保持/);
  h.run(`operations.push({intent: {action: "RESUME_EXECUTION_BASELINE", project_id: data.request.project_id, delivery_id: data.request.id},
    result: {project_id: data.request.project_id, delivery_id: data.request.id,
      execution_baseline_binding: {purpose: "context_capacity_resume"}}});`);
  assert.equal(h.run("operationActionLabel(operations[2])"), "继续保留进度的原需求");
  assert.match(h.run("operationPurpose(operations[2])"), /接续原需求/);
  assert.equal(h.run(`operationActionLabel({action: "EXECUTE_EXECUTION_BASELINE", baseline_purpose: "context_capacity_resume"})`),
    "批准保留进度，保持暂停");
  h.run("delete operations[1].result");
  assert.equal(h.run("operationActionLabel(operations[1])"), "批准保留进度，保持暂停", "pending exact execute uses its original proposal purpose");
});
