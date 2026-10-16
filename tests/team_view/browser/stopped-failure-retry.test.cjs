const {test} = require("node:test");
const assert = require("node:assert/strict");
const {ui, operation} = require("./fixture.cjs");
const {supportedActions} = require("../console-capabilities-fixture.cjs");

async function waitingCoder(t) {
  const h = await ui(t, {operationManifest: {operation_contract_version: 10, supported_actions: supportedActions}});
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{delivery_id: "delivery_coder", root: "/fixture/repository", selected_paths: ["."]}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "NONTRANSIENT_INFRA",
    reason: "调用失败，原因未知，原草稿保留。", next_action: "核验失败后的保留进度。", action_required: true};
  const facts = {task_id: "task_coder", work_item_id: "work_coder", role: "coder", task_intent_sha256: "b".repeat(64),
    source_revision: "c".repeat(40), checkpoint_sequence: 4, classification: "NONTRANSIENT_INFRA"};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_DEPENDENCY", lease_liveness: "UNKNOWN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  const task = {id: "delivery_coder", task_id: facts.task_id, request_id: request.id, project_id: request.project_id,
    title: "失败后保留同一需求", task_revision: 4, task_intent_sha256: facts.task_intent_sha256,
    status: "IMPLEMENTING", terminal: false, scope: request.scopes[0], last_activity: "2026-10-16T00:00:00Z",
    execution: request.execution, assignments: [], documents: [], timeline: [], runs: [], role_queue: [step], execution_history: []};
  h.team.tasks.push(task);
  const submitted = [];
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const intent = route.request().postDataJSON().intent;
    submitted.push(intent);
    const record = operation("QUEUED", {operation_id: "operation_failure_" + submitted.length,
      updated_at: "2026-10-16T00:01:00Z", intent});
    h.state.operations.push(record);
    await route.fulfill({status: 202, json: record});
  });
  await h.tick(); await h.requests(); await h.page.evaluate(() => showDetail("request", "request_fixture"));
  return {...h, request, task, step, facts, submitted};
}
function stoppedPlan(h) {
  const request = {task_id: h.task.task_id, run_id: "run_original", role: "coder", source_revision: h.facts.source_revision};
  const proof = {kind: "stopped_failure", proof_sha256: "2".repeat(64),
    outcome: {start: {request, work_item_id: h.step.work_item_id, checkpoint_sequence: 4},
      result: {status: "FAILED", error: {code: "PROVIDER_UNAVAILABLE", transient: false}}},
    capture_start: {request, task_revision: 4, start_sha256: "3".repeat(64), worktree_path: "/fixture/coder"},
    capture_stop: {task_id: h.task.task_id, run_id: request.run_id, capture_start_sha256: "3".repeat(64),
      process_stop: {kind: "failed", returncode: 1, session_proof: {proof_scope: "owned_session_empty", proof_sha256: "5".repeat(64)}},
      output_present: false, original_error_code: "PROVIDER_UNAVAILABLE"}};
  return {purpose: "stopped_failure_retry", plan_sha256: "4".repeat(64), input_mode: "preserve_draft", conflicted: false,
    target_base_ref: h.facts.source_revision, prepared_source_revision: h.facts.source_revision,
    dirty_capture: {source_revision: h.facts.source_revision, worktree_path: "/fixture/coder"},
    facts: {task: {id: h.task.task_id, base_ref: h.facts.source_revision, branch_name: "ai/feature/original"}, task_revision: 4,
      work_item_id: h.step.work_item_id, stopped_failure: proof,
      continuation: {retry_cause: "stopped_failure_retry", stopped_failure_sha256: proof.proof_sha256}}};
}
async function prepare(h) {
  await h.page.locator("#detail").getByRole("button", {name: "检查失败后的保留进度", exact: true}).click(); await h.close();
  const plan = stoppedPlan(h);
  Object.assign(h.state.operations[0], {status: "SUCCEEDED", result: {project_id: h.request.project_id,
    delivery_id: h.request.id, checkpoint_sha256: h.request.checkpoint_sha256, execution_baseline_plan: plan}});
  await h.tick(); return plan;
}

test("failure check prepares an exact ordinary-work decision, preserves consent during polling and submits PAUSE", async t => {
  const h = await waitingCoder(t);
  const detail = h.page.locator("#detail");
  assert.match(await detail.innerText(), /原因仍未知/);
  assert.equal(await detail.getByRole("checkbox").count(), 0);
  const plan = await prepare(h);
  assert.equal(h.submitted[0].purpose, "stopped_failure_retry");
  assert.equal(Object.hasOwn(h.submitted[0], "target_base_ref"), false);
  const confirmation = detail.getByRole("checkbox", {name: "接受原失败原因未知，并消耗一次普通工作额度", exact: true});
  const approve = detail.getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  assert.equal(await approve.isDisabled(), true);
  await confirmation.check(); await confirmation.focus();
  await confirmation.evaluate(node => {window.failureConsent = node;});
  h.task.last_activity = "2026-10-16T00:00:01Z"; await h.tick();
  assert.equal(await confirmation.evaluate(node => node === window.failureConsent && node.checked && document.activeElement === node), true);
  assert.match(await detail.innerText(), /消耗 1 次剩余开发额度/);
  assert.match(await detail.innerText(), /独立 QA 和 Review/);
  for (const width of [1440, 390]) {
    await h.page.setViewportSize({width, height: 1000});
    assert.equal(await detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
  }
  await approve.click(); await h.close();
  assert.equal(h.submitted[1].confirm_stopped_failure_retry, true);
  assert.equal(h.submitted[1].expected_plan_sha256, plan.plan_sha256);
  assert.equal(h.submitted[1].continuation_mode, "pause");
  assert.equal(Object.hasOwn(h.submitted[1], "confirm_provider_prerequisites_repaired"), false);
});

test("changed failure plan resets consent and detached or capability-withdrawn approvals cannot POST", async t => {
  const h = await waitingCoder(t); const plan = await prepare(h);
  const detail = h.page.locator("#detail");
  const confirmation = detail.getByRole("checkbox", {name: "接受原失败原因未知，并消耗一次普通工作额度", exact: true});
  const approve = detail.getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  await confirmation.check(); const old = await approve.elementHandle();
  plan.plan_sha256 = "6".repeat(64); await h.tick();
  assert.equal(await confirmation.isChecked(), false); assert.equal(await approve.isDisabled(), true);
  await old.evaluate(node => node.click()); assert.equal(h.submitted.length, 1); await h.close();
  await confirmation.check(); const current = await approve.elementHandle();
  h.state.operationManifest.operation_contract_version = 9; await h.tick();
  await current.evaluate(node => node.click()); assert.equal(h.submitted.length, 1);
  assert.equal(await approve.count(), 0);
});
