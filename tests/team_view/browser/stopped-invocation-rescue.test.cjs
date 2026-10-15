const {test} = require("node:test");
const assert = require("node:assert/strict");
const {ui, operation} = require("./fixture.cjs");
const {supportedActions} = require("../console-capabilities-fixture.cjs");

async function waitingCoder(t) {
  const h = await ui(t, {operationManifest: {operation_contract_version: 9, supported_actions: supportedActions}});
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{delivery_id: "delivery_coder", root: "/fixture/repository", selected_paths: ["."]}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "EXECUTION_UNCERTAIN",
    reason: "执行结果未封存，真实停止和原草稿保留。", next_action: "核验完整停止证明和保留进度。", action_required: true};
  const facts = {task_id: "task_coder", work_item_id: "work_coder", role: "coder", task_intent_sha256: "b".repeat(64),
    source_revision: "c".repeat(40), checkpoint_sequence: 4, classification: "EXECUTION_UNCERTAIN"};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_DEPENDENCY", lease_liveness: "UNKNOWN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  const task = {id: "delivery_coder", task_id: facts.task_id, request_id: request.id, project_id: request.project_id,
    title: "停止后保留同一需求", task_revision: 4, task_intent_sha256: facts.task_intent_sha256,
    status: "IMPLEMENTING", terminal: false, scope: request.scopes[0], last_activity: "2026-10-15T00:00:00Z",
    execution: request.execution, assignments: [], documents: [], timeline: [], runs: [], role_queue: [step], execution_history: []};
  const proof = {...facts, disposition_sha256: step.wait_disposition_sha256, proof_sha256: "e".repeat(64),
    original_run_id: "run_original", process_stop_sha256: "1".repeat(64),
    missing: ["OUTCOME_UNKNOWN", "CHECKPOINT_UNAVAILABLE"], permitted_resolutions: []};
  h.team.tasks.push(task);
  const waitIntent = {action: "INSPECT_DELIVERY_WAIT", project_id: request.project_id, delivery_id: request.id,
    expected_checkpoint_sha256: request.checkpoint_sha256, work_item_id: facts.work_item_id,
    expected_disposition_sha256: step.wait_disposition_sha256, expected_task_intent_sha256: facts.task_intent_sha256,
    expected_source_revision: facts.source_revision, expected_checkpoint_sequence: 4};
  h.state.operations.push(operation("SUCCEEDED", {operation_id: "operation_inspect", intent: waitIntent,
    result: {project_id: request.project_id, delivery_id: request.id,
      checkpoint_sha256: request.checkpoint_sha256, engineering_wait_investigation: proof}}));
  const submitted = [];
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const intent = route.request().postDataJSON().intent;
    submitted.push(intent);
    const record = operation("QUEUED", {operation_id: "operation_stopped_" + submitted.length,
      updated_at: "2026-10-15T00:01:00Z", intent});
    h.state.operations.push(record);
    await route.fulfill({status: 202, json: record});
  });
  await h.tick(); await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  return {...h, request, task, step, facts, proof, submitted};
}
function stoppedPlan(h) {
  const request = {task_id: h.task.task_id, run_id: h.proof.original_run_id, role: "coder", source_revision: h.facts.source_revision};
  const proof = {kind: "stopped_coder_execution_without_outcome", proof_sha256: "2".repeat(64),
    invocation_start: {request, work_item_id: h.step.work_item_id, checkpoint_sequence: 4},
    capture_start: {request, task_revision: 4, start_sha256: "3".repeat(64), worktree_path: "/fixture/coder"},
    capture_stop: {task_id: h.task.task_id, run_id: request.run_id, capture_start_sha256: "3".repeat(64),
      process_stop: {kind: "failed", returncode: -15, session_proof: {proof_scope: "owned_session_empty", proof_sha256: "5".repeat(64)}},
      output_present: false, original_error_code: "PROVIDER_ERROR"}};
  return {purpose: "stopped_execution_rescue", plan_sha256: "4".repeat(64), input_mode: "preserve_draft", conflicted: false,
    target_base_ref: h.facts.source_revision, prepared_source_revision: h.facts.source_revision,
    dirty_capture: {source_revision: h.facts.source_revision, worktree_path: "/fixture/coder"},
    facts: {task: {id: h.task.task_id, base_ref: h.facts.source_revision, branch_name: "ai/feature/original"}, task_revision: 4,
      work_item_id: h.step.work_item_id, stopped_execution: proof,
      continuation: {retry_cause: "stopped_execution_unknown", stopped_execution_sha256: proof.proof_sha256}}};
}

test("stopped rescue reads exact plan incrementally and approves PAUSE without historical stop attestation", async t => {
  const h = await waitingCoder(t);
  const detail = h.page.locator("#detail");
  const prepare = detail.getByRole("button", {name: "检查停止后的保留进度", exact: true});
  assert.equal(await prepare.isVisible(), true);
  assert.equal(await detail.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).count(), 0);
  await prepare.click(); await h.close();
  assert.equal(h.submitted[0].purpose, "stopped_execution_rescue");
  assert.equal(Object.hasOwn(h.submitted[0], "target_base_ref"), false);
  const plan = stoppedPlan(h);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {project_id: h.request.project_id,
    delivery_id: h.request.id, checkpoint_sha256: h.request.checkpoint_sha256,
    execution_baseline_plan: plan}});
  await h.tick();
  const approve = detail.getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  assert.equal(await approve.isVisible(), true);
  assert.match(await detail.innerText(), /原调用结果仍未封存/);
  assert.match(await detail.innerText(), /消耗 1 次剩余开发额度/);
  assert.equal(await detail.getByRole("checkbox").count(), 0);
  for (const width of [1440, 390]) {
    await h.page.setViewportSize({width, height: 1000});
    assert.equal(await detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
  }
  await approve.click(); await h.close();
  assert.equal(h.submitted[1].continuation_mode, "pause");
  assert.equal(h.submitted[1].expected_plan_sha256, plan.plan_sha256);
  assert.equal(Object.hasOwn(h.submitted[1], "confirm_local_execution_stopped"), false);
});

test("withdrawn server capability and detached old approval cannot submit", async t => {
  const h = await waitingCoder(t);
  const plan = stoppedPlan(h);
  h.state.operations.push(operation("SUCCEEDED", {operation_id: "operation_plan", intent: {
    action: "PROPOSE_EXECUTION_BASELINE", project_id: h.request.project_id, delivery_id: h.request.id,
    expected_checkpoint_sha256: h.request.checkpoint_sha256, task_id: h.task.task_id,
    expected_task_intent_sha256: h.task.task_intent_sha256, expected_task_revision: 4,
    expected_work_item_id: h.step.work_item_id, expected_source_revision: h.facts.source_revision,
    purpose: "stopped_execution_rescue", input_mode: "preserve_draft",
  }, result: {project_id: h.request.project_id, delivery_id: h.request.id,
    checkpoint_sha256: h.request.checkpoint_sha256, execution_baseline_plan: plan}}));
  await h.tick();
  const approve = h.page.locator("#detail").getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  await approve.evaluate(node => {window.oldStoppedApproval = node;});
  h.state.operationManifest.operation_contract_version = 8; await h.tick();
  await h.page.evaluate(() => window.oldStoppedApproval.click());
  assert.equal(h.submitted.length, 0);
  assert.equal(await approve.count(), 0);
});
