const {test} = require("node:test");
const assert = require("node:assert/strict");
const {ui, operation} = require("./fixture.cjs");
const {supportedActions} = require("../console-capabilities-fixture.cjs");

async function waiting(t) {
  const h = await ui(t, {operationManifest: {operation_contract_version: 6, supported_actions: supportedActions}});
  const request = h.team.requests[0];
  Object.assign(request, {stage: "DELIVERING", scopes: [{delivery_id: "delivery_coder", root: "/fixture/repository", selected_paths: ["."]}],
    execution: {state: "WAITING", responsibility: "engineering", reason_code: "TRANSIENT_INFRA", reason: "原调用失败，现场保留。", next_action: "检查原执行。", action_required: false}});
  const facts = {task_id: "task_coder", work_item_id: "work_coder", role: "coder", task_intent_sha256: "b".repeat(64),
    source_revision: "c".repeat(40), checkpoint_sequence: 4, classification: "TRANSIENT_INFRA"};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_DEPENDENCY", lease_liveness: "UNKNOWN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering", reason: request.execution.reason, next_action: request.execution.next_action}};
  const task = {id: "delivery_coder", task_id: facts.task_id, request_id: request.id, project_id: request.project_id, title: "同一需求的认证失败续跑",
    task_revision: 4, task_intent_sha256: facts.task_intent_sha256, status: "IMPLEMENTING", terminal: false, scope: request.scopes[0],
    last_activity: "2026-10-12T00:00:00Z", execution: request.execution, assignments: [], documents: [], timeline: [], runs: [], role_queue: [step], execution_history: []};
  h.team.tasks.push(task);
  const bound = {project_id: request.project_id, delivery_id: request.id, expected_checkpoint_sha256: request.checkpoint_sha256,
    task_id: task.task_id, expected_task_intent_sha256: facts.task_intent_sha256, expected_task_revision: 4,
    expected_work_item_id: step.work_item_id, expected_source_revision: facts.source_revision};
  const original = {task_id: task.task_id, run_id: "run_original", role: "coder", source_revision: facts.source_revision};
  const stopped = {kind: "stopped_provider_failure", proof_sha256: "2".repeat(64),
    outcome: {start: {request: original, work_item_id: step.work_item_id, checkpoint_sequence: 4}, result: {status: "FAILED", error: {code: "AUTHENTICATION_ERROR", transient: false}}},
    capture_start: {request: original, task_revision: 4, start_sha256: "3".repeat(64), worktree_path: "/fixture/coder"},
    capture_stop: {task_id: task.task_id, run_id: original.run_id, capture_start_sha256: "3".repeat(64), process_stop: {kind: "failed", returncode: 1}, output_present: false, original_error_code: "AUTHENTICATION_ERROR"}};
  const plan = {purpose: "stopped_provider_retry", plan_sha256: "4".repeat(64), input_mode: "preserve_draft", conflicted: false,
    target_base_ref: "c".repeat(40), prepared_source_revision: "c".repeat(40), dirty_capture: {source_revision: facts.source_revision, worktree_path: "/fixture/coder"},
    facts: {task: {id: task.task_id, base_ref: "c".repeat(40), branch_name: "ai/feature/original"}, task_revision: 4, work_item_id: step.work_item_id,
      stopped_provider_failure: stopped, continuation: {retry_cause: "provider_prerequisite_repaired", stopped_provider_failure_sha256: stopped.proof_sha256}}};
  h.state.operations.push(operation("SUCCEEDED", {operation_id: "operation_prepare", intent: {...bound, action: "PROPOSE_EXECUTION_BASELINE", purpose: "stopped_provider_retry", input_mode: "preserve_draft"},
    result: {checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}}));
  await h.tick(); await h.page.evaluate(() => showDetail("request", "request_fixture"));
  return {...h, request, task, step, plan};
}

test("provider prerequisite confirmation survives unrelated polling and stays visible at narrow widths", async t => {
  const h = await waiting(t);
  const confirmation = h.page.getByRole("checkbox", {name: "确认原模型认证或执行器配置前提已修复", exact: true});
  assert.equal(await confirmation.isVisible(), true);
  const approve = h.page.getByRole("button", {name: "确认前提已修复，保留进度", exact: true});
  assert.equal(await approve.isDisabled(), true);
  await confirmation.check(); await confirmation.focus();
  await confirmation.evaluate(node => {window.providerConfirmation = node;});
  h.task.last_activity = "2026-10-12T00:00:01Z"; await h.tick();
  assert.equal(await confirmation.evaluate(node => node === window.providerConfirmation && node.checked), true);
  assert.equal(await confirmation.evaluate(node => document.activeElement === node), true);
  assert.equal(await approve.isDisabled(), false);
  for (const width of [390, 1440]) {
    await h.page.setViewportSize({width, height: 900});
    assert.equal(await confirmation.isVisible(), true);
    const bounds = await approve.boundingBox(); assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width);
  }
  const detail = h.page.locator("#detail");
  assert.match(await detail.innerText(), /原失败记录保持/);
  assert.equal(await detail.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).count(), 0);
});

test("changed exact plan resets confirmation and detached approval cannot submit", async t => {
  const h = await waiting(t);
  const confirmation = h.page.getByRole("checkbox", {name: "确认原模型认证或执行器配置前提已修复", exact: true});
  await confirmation.check();
  const original = await h.page.getByRole("button", {name: "确认前提已修复，保留进度", exact: true}).elementHandle();
  h.plan.plan_sha256 = "5".repeat(64); await h.tick();
  assert.equal(await confirmation.isChecked(), false);
  let submissions = 0;
  await h.page.route("http://ui.test/api/v1/operations", async route => {if (route.request().method() === "POST") submissions++; return route.fallback();});
  await original.evaluate(node => node.click()); assert.equal(submissions, 0);
});
