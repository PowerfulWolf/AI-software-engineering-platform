const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.events = {};
    this.dataset = {};
    this.attributes = {};
    this.textContent = "";
  }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, fn) { this.events[key] = fn; }
  set innerHTML(value) { throw new Error("Unsafe HTML: " + value); }
}
const descend = node => [node, ...node.children.filter(item => typeof item !== "string").flatMap(descend)];
const text = node => node.textContent + node.children.map(item => typeof item === "string" ? item : text(item)).join(" ");
const control = (node, name) => descend(node).find(item => item.tagName === "BUTTON" && item.textContent === name);
const digest = value => value.repeat(64);

function fixture() {
  const facts = {task_id: "task_current", work_item_id: "work_current", role: "coder",
    task_intent_sha256: digest("b"), source_revision: digest("c"), checkpoint_sequence: 4};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_HUMAN",
    wait_disposition_sha256: digest("d"), wait_disposition: {facts, responsibility: "engineering",
      reason: "执行结果待核验，现场保留。", next_action: "工程授权者调查原执行。"}};
  const request = {id: "requirement_current", project_id: "project_current", title: "交付需求",
    checkpoint_sha256: digest("a"), stage: "DELIVERING", scopes: [{delivery_id: "delivery_current"}], documents: [],
    execution: {state: "WAITING", responsibility: "engineering", reason_code: "EXECUTION_UNCERTAIN",
      reason: step.wait_disposition.reason, next_action: step.wait_disposition.next_action}};
  const task = {id: "delivery_current", task_id: facts.task_id, request_id: request.id,
    status: "IMPLEMENTING", terminal: false, last_activity: "2026-10-05T00:00:00Z", role_queue: [step]};
  return {request, task, step};
}

function harness() {
  const data = fixture();
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  // Load the actual UI functions without starting navigation, polling or network work.
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  vm.runInContext(`snapshot = {team_id: "team_current", selected_project_id: "project_current",
    projects: [], agents: [], tasks: [data.task], requests: [data.request]};
    consoleTeamId = "team_current"; consoleAvailable = true; consoleDeliveryReady = true;
    operationsAvailable = true; globalThis.submitted = [];
    submitOperation = async intent => { submitted.push(intent); return {operation_id: "accepted"}; };
    renderDetail = () => {}; renderNotification = () => {};`, context);
  return {context, ...data, run: code => vm.runInContext(code, context)};
}

function investigation(h, missing = []) {
  const proof = {task_id: h.task.task_id, work_item_id: h.step.work_item_id,
    disposition_sha256: h.step.wait_disposition_sha256, task_intent_sha256: digest("b"),
    source_revision: digest("c"), checkpoint_sequence: 4, proof_sha256: digest("e"),
    missing, permitted_resolutions: missing.length ? [] : ["RETRY_FROM_CHECKPOINT"],
    inspected_at: "2026-10-05T01:00:00Z", next_action: "按已封存现场继续原交付。"};
  h.context.proof = proof;
  h.run(`operations = [{operation_id: "inspect_current", status: "SUCCEEDED",
    updated_at: "2026-10-05T01:00:00Z",
    intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
    result: {engineering_wait_investigation: proof, checkpoint_sha256: data.request.checkpoint_sha256}}];`);
  return proof;
}

test("accepted inconclusive QA retains safe environment reason without findings", () => {
  const h = harness();
  h.context.qaEntry = {id: "art_qa_wait", details: {kind: "qa-report", status: "FAIL",
    findings: [], environment: {reason: "增量测试入口尚未执行。", diagnostic: "<script>unsafe</script>"}}};
  const box = h.run('(() => { const target = el("section"); appendExecutionArtifactDetails(target, qaEntry); return target; })()');
  assert.match(text(box), /QA 验证环境与未完成原因/);
  assert.match(text(box), /增量测试入口尚未执行/);
  assert.match(text(box), /<script>unsafe<\/script>/);
  assert.equal(descend(box).some(node => node.tagName === "SCRIPT"), false);
  const fold = descend(box).find(node => node.tagName === "DETAILS");
  assert.notEqual(fold.open, true);
});

test("engineering wait controls submit exact facts and only the sealed permitted resolution", async () => {
  const h = harness();
  let box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  await control(box, "调查工程等待").events.click();
  assert.deepEqual(JSON.parse(h.run("JSON.stringify(submitted[0])")), {
    action: "INSPECT_DELIVERY_WAIT", project_id: h.request.project_id, delivery_id: h.request.id,
    expected_checkpoint_sha256: digest("a"), work_item_id: "work_current",
    expected_disposition_sha256: digest("d"), expected_task_intent_sha256: digest("b"),
    expected_source_revision: digest("c"), expected_checkpoint_sequence: 4,
  });
  investigation(h);
  box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  await control(box, "确认现场并继续原交付").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[1])"));
  assert.equal(intent.action, "RESOLVE_DELIVERY_WAIT");
  assert.equal(intent.proof_sha256, digest("e"));
  assert.equal(intent.resolution_kind, "RETRY_FROM_CHECKPOINT");
  assert.equal(Object.hasOwn(intent, "process_stopped"), false);
  assert.equal(Object.hasOwn(intent, "operator_id"), false);
  assert.equal(Object.hasOwn(intent, "retry_cause"), false);
});

test("unknown stop proof remains an engineering wait with explicit missing facts and no resolution", () => {
  const h = harness();
  investigation(h, ["STOP_UNRECORDED", "PROCESS_LIVE_OR_UNKNOWN"]);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /缺少可信停止记录/);
  assert.match(text(box), /进程仍在运行或停止状态未知/);
  assert.equal(control(box, "确认现场并继续原交付"), undefined);
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
  h.run('operations[0].status = "RUNNING"');
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
});

test("rejected recorded outcomes show a Chinese engineering action without replay controls", () => {
  const h = harness();
  investigation(h, ["OUTCOME_REJECTED", "STOP_UNRECORDED"]);
  h.context.proof.next_action = "原产出已被拒绝，工程团队需修复契约并核验真实停机现场。";
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /原产出已被拒绝/);
  assert.match(text(box), /不能重复接纳/);
  assert.match(text(box), /修复契约并核验真实停机现场/);
  assert.equal(control(box, "接纳已封存结果"), undefined);
  assert.equal(control(box, "确认现场并继续原交付"), undefined);
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
});

test("recorded result replay and unused preflight resume expose only the service-permitted kind", async () => {
  const names = {REPLAY_RECORDED_RESULT: "接纳已封存结果", RESUME_UNINVOKED: "确认前提并继续",
    REVERIFY_CANDIDATE: "保留候选并重新独立测试",
    RETRY_VERIFIER_PREPARATION: "保留候选并重试受控验证准备"};
  for (const [kind, name] of Object.entries(names)) {
    const h = harness();
    const proof = investigation(h);
    proof.permitted_resolutions = [kind];
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    assert.equal(control(box, "确认现场并继续原交付"), undefined);
    await control(box, name).events.click();
    assert.equal(h.run("submitted[0].resolution_kind"), kind);
    h.run('operations.push({operation_id: "running", status: "RUNNING", intent: {delivery_id: data.request.id}})');
    assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), name), undefined);
    assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
  }
});

test("stale checkpoint, disposition or proof cannot be submitted through an old control", async () => {
  for (const mutation of [
    'data.request.checkpoint_sha256 = "f".repeat(64)',
    'data.step.wait_disposition_sha256 = "f".repeat(64)',
    'operations[0].result.engineering_wait_investigation.proof_sha256 = "f".repeat(64)',
  ]) {
    const h = harness();
    investigation(h);
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    h.run(mutation);
    await control(box, "确认现场并继续原交付").events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
    if (!mutation.includes("proof_sha256"))
      assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "确认现场并继续原交付"), undefined);
  }
});

test("engineering decision keeps the durable wait visible and all operation records beyond eight", () => {
  const h = harness();
  investigation(h);
  h.run(`operations.push({operation_id: "resolve_current", status: "SUCCEEDED",
    updated_at: "2026-10-05T02:00:00Z",
    intent: {...engineeringWaitIntent(data.request, data.step), action: "RESOLVE_DELIVERY_WAIT", proof_sha256: proof.proof_sha256},
    result: {engineering_wait_resolution: {kind: "delivery_wait_resolution", resolution_kind: "RETRY_FROM_CHECKPOINT", proof_sha256: proof.proof_sha256,
      authorization_source: "engineering_operator_decision", operator_principal: {operator_id: "operator:actual"}}}});
    for (let index = 0; index < 10; index++) operations.push({operation_id: "old_" + index,
      status: "SUCCEEDED", updated_at: "2026-10-04T00:00:00Z", intent: {delivery_id: data.request.id,
      project_id: data.request.project_id, action: "CONTINUE_DELIVERY"}, result: {next_action: "<img onerror=evil>"}});`);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /决定已记录/);
  assert.equal(control(box, "确认现场并继续原交付"), undefined);
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
  const panel = new Element("div");
  h.context.panel = panel;
  h.run("requestOperationHistory(panel, data.request)");
  assert.match(text(panel), /共 12 条操作/);
  assert.match(text(panel), /operator:actual/);
  assert.match(text(panel), /<img onerror=evil>/);
  assert.equal(descend(panel).filter(node => node.tagName === "LI").length, 12);
});

function baselineFixture(h) {
  h.task.task_revision = 4;
  h.task.task_intent_sha256 = digest("b");
  h.step.wait_disposition.facts.source_revision = "c".repeat(40);
}
function baselinePlan(h, conflicted = false, mode = "preserve_draft") {
  const plan = {plan_sha256: digest("e"), target_base_ref: "f".repeat(40), input_mode: mode,
    conflicted, dirty_capture: {source_revision: "c".repeat(40)},
    facts: {task: {id: h.task.task_id, branch_name: "ai/feature/original"}, task_revision: 4,
      work_item_id: h.step.work_item_id}};
  h.context.baselinePlan = plan;
  h.run(`operations = [{operation_id: "baseline_proposal", status: "SUCCEEDED", updated_at: "2026-10-05T01:00:00Z",
    intent: {...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE",
      target_base_ref: baselinePlan.target_base_ref, input_mode: baselinePlan.input_mode},
    result: {checkpoint_sha256: data.request.checkpoint_sha256, execution_baseline_plan: baselinePlan}}];`);
  return plan;
}

test("baseline engineering controls bind original task and sealed exact plan", async () => {
  const h = harness();
  baselineFixture(h);
  let box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.equal(control(box, "批准并更新原分支基线"), undefined);
  const input = descend(box).find(node => node.tagName === "INPUT");
  input.value = "f".repeat(40);
  await control(box, "调查并保留原草稿").events.click();
  assert.deepEqual(JSON.parse(h.run("JSON.stringify(submitted[0])")), {
    action: "PROPOSE_EXECUTION_BASELINE", project_id: h.request.project_id, delivery_id: h.request.id,
    expected_checkpoint_sha256: digest("a"), task_id: h.task.task_id,
    expected_task_intent_sha256: digest("b"), expected_task_revision: 4,
    expected_work_item_id: h.step.work_item_id, expected_source_revision: "c".repeat(40),
    target_base_ref: "f".repeat(40), input_mode: "preserve_draft",
  });
  baselinePlan(h);
  box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /ai\/feature\/original/);
  await control(box, "批准并更新原分支基线").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[1])"));
  assert.equal(intent.action, "EXECUTE_EXECUTION_BASELINE");
  assert.equal(intent.expected_plan_sha256, digest("e"));
  assert.equal(intent.expected_checkpoint_sha256, digest("a"));
  assert.equal(Object.hasOwn(intent, "operator_id"), false);
  assert.equal(Object.hasOwn(intent, "process_stopped"), false);
});

test("baseline conflicts require a new explicit coder reapply plan before execution", async () => {
  const h = harness();
  baselineFixture(h);
  baselinePlan(h, true);
  let box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.equal(control(box, "批准并更新原分支基线"), undefined);
  await control(box, "提出 Coder 适配完整旧补丁的计划").events.click();
  assert.equal(h.run("submitted[0].input_mode"), "coder_reapply");
  assert.equal(h.run("submitted[0].action"), "PROPOSE_EXECUTION_BASELINE");
  baselinePlan(h, false, "coder_reapply");
  box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /读取完整旧补丁并适配/);
  await control(box, "批准并更新原分支基线").events.click();
  assert.equal(h.run("submitted[1].action"), "EXECUTE_EXECUTION_BASELINE");
});

test("stale baseline plans and QA stages cannot update the original coder branch", async () => {
  for (const mutation of [
    'data.request.checkpoint_sha256 = "f".repeat(64)',
    'data.task.task_revision = 5',
    'operations[0].result.execution_baseline_plan.plan_sha256 = "f".repeat(64)',
  ]) {
    const h = harness();
    baselineFixture(h);
    baselinePlan(h);
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    h.run(mutation);
    await control(box, "批准并更新原分支基线").events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
  const h = harness();
  baselineFixture(h);
  h.task.status = "QA";
  h.step.role = "qa";
  assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "调查并保留原草稿"), undefined);
});
