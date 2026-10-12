const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {ui, operation} = require("./fixture.cjs");
const {supportedActions} = require("../console-capabilities-fixture.cjs");

async function waiting(t, {ready = false, version = 8} = {}) {
  const h = await ui(t, {operationManifest: {operation_contract_version: version, supported_actions: supportedActions}});
  const request = h.team.requests[0];
  Object.assign(request, {title: "K1 自动知识采集首个闭环", stage: "DELIVERING",
    scopes: [{delivery_id: "delivery_coder", root: "/fixture/repository", selected_paths: ["."]}],
    execution: {state: "WAITING", responsibility: "engineering", reason_code: "CONTEXT_CAPACITY",
      reason: "本次模型输入超过容量，原开发进度已保留。", next_action: "平台修复输入准备后，在原需求准备保留进度的恢复方案。", action_required: false}});
  const facts = {task_id: "task_coder", work_item_id: "work_coder", role: "coder", task_intent_sha256: "b".repeat(64),
    source_revision: "c".repeat(40), checkpoint_sequence: 4, classification: "CONTEXT_CAPACITY",
    evidence_ids: ["context-capacity://" + "e".repeat(64)]};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_DEPENDENCY", lease_liveness: "UNKNOWN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  const task = {id: "delivery_coder", task_id: facts.task_id, request_id: request.id, project_id: request.project_id,
    title: "原需求的开发任务", task_revision: 4, task_intent_sha256: facts.task_intent_sha256,
    status: "IMPLEMENTING", terminal: false, scope: request.scopes[0], last_activity: "2026-10-12T00:00:00Z",
    execution: request.execution, assignments: [], documents: [], timeline: [], runs: [], role_queue: [step], execution_history: []};
  h.team.tasks.push(task);
  const bound = {project_id: request.project_id, delivery_id: request.id, expected_checkpoint_sha256: request.checkpoint_sha256,
    task_id: task.task_id, expected_task_intent_sha256: facts.task_intent_sha256, expected_task_revision: 4,
    expected_work_item_id: step.work_item_id, expected_source_revision: facts.source_revision};
  const plan = {purpose: "context_capacity_resume", plan_sha256: "f".repeat(64), input_mode: "preserve_draft", conflicted: false,
    target_base_ref: "9".repeat(40), prepared_source_revision: facts.source_revision,
    dirty_capture: {source_revision: facts.source_revision, worktree_path: "/fixture/coder"},
    facts: {task: {id: task.task_id, base_ref: "9".repeat(40), branch_name: "ai/feature/original"},
      task_revision: 4, work_item_id: step.work_item_id, context_capacity_receipt_sha256: "e".repeat(64)}};
  if (ready) h.state.operations.push(operation("SUCCEEDED", {operation_id: "operation_prepare",
    intent: {...bound, action: "PROPOSE_EXECUTION_BASELINE", purpose: "context_capacity_resume", input_mode: "preserve_draft"},
    result: {project_id: request.project_id, delivery_id: request.id,
      checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}}));
  await h.tick(); await h.page.evaluate(() => showDetail("request", "request_fixture"));
  return {...h, request, task, step, bound, plan, panel: h.page.locator("#detail .engineering-capacity-resume")};
}

async function captureWrites(h) {
  const writes = [];
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const payload = route.request().postDataJSON(); writes.push(payload.intent);
    const saved = operation("SUCCEEDED", {operation_id: "operation_write_" + writes.length, intent: payload.intent,
      updated_at: "2026-10-12T00:02:00Z", result: {project_id: h.request.project_id, delivery_id: h.request.id,
        execution_baseline_binding: {purpose: "context_capacity_resume"}}});
    h.state.operations.push(saved);
    return route.fulfill({status: 202, json: saved});
  });
  return writes;
}

test("capacity wait offers a visible preparation with exact original identity and no target-version input", async t => {
  const h = await waiting(t); const writes = await captureWrites(h);
  const prepare = h.panel.getByRole("button", {name: "准备保留进度的恢复方案", exact: true});
  assert.equal(await prepare.isVisible(), true);
  assert.equal(await h.panel.locator("input:visible").count(), 0);
  assert.equal(await h.panel.locator("input[type=checkbox]").count(), 0);
  assert.match(await h.panel.innerText(), /主开发调用尚未开始/);
  assert.doesNotMatch(await h.panel.innerText(), /[a-f0-9]{40}/);
  for (const width of [390, 1440]) {
    await h.page.setViewportSize({width, height: 900});
    const box = await prepare.boundingBox(); assert.ok(box.x >= 0 && box.x + box.width <= width);
  }
  await prepare.click();
  await h.page.waitForFunction(() => operations.some(item => item.operation_id === "operation_write_1"));
  assert.deepEqual(writes, [{...h.bound, action: "PROPOSE_EXECUTION_BASELINE", purpose: "context_capacity_resume", input_mode: "preserve_draft"}]);
  assert.equal(Object.hasOwn(writes[0], "target_base_ref"), false);
});

test("ready plan retains reading, exact approval DOM and focus across unrelated polling at both widths", async t => {
  const h = await waiting(t, {ready: true});
  const approve = h.panel.getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  const details = h.panel.locator("details").filter({has: h.page.getByText("恢复方案核对信息", {exact: true})});
  await details.locator("summary").click();
  await approve.focus();
  await h.panel.evaluate(panel => {
    const heading = panel.querySelector("h3"), description = panel.querySelector("ol"),
      button = [...panel.querySelectorAll("button")].find(node => node.textContent === "批准保留进度，保持暂停");
    const range = document.createRange(); range.setStart(description.firstChild.firstChild, 0);
    range.setEnd(description.firstChild.firstChild, 10);
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    window.capacityReading = {heading, description, button, selected: selection.toString()};
  });
  h.task.last_activity = "2026-10-12T00:00:01Z"; await h.tick();
  assert.equal(await h.panel.evaluate(panel => {
    const saved = window.capacityReading;
    return panel.querySelector("h3") === saved.heading && panel.querySelector("ol") === saved.description &&
      saved.button.isConnected && document.activeElement === saved.button && window.getSelection().toString() === saved.selected;
  }), true);
  assert.equal(await details.evaluate(node => node.open), true);
  assert.equal(await h.panel.locator("input:visible").count(), 0);
  const artifactDirectory = "/tmp/ase-context-capacity-ui-20261012";
  fs.mkdirSync(artifactDirectory, {recursive: true});
  for (const width of [390, 1440]) {
    await h.page.setViewportSize({width, height: 900});
    const box = await approve.boundingBox(); assert.ok(box.x >= 0 && box.x + box.width <= width);
    await h.panel.screenshot({path: artifactDirectory + "/ready-" + width + ".png"});
  }
});

test("changed plan, receipt and withdrawn v8 capability revoke detached old approvals", async t => {
  for (const change of ["plan", "receipt", "capability"]) {
    const h = await waiting(t, {ready: true}); const writes = await captureWrites(h);
    const old = await h.panel.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).elementHandle();
    if (change === "plan") h.plan.plan_sha256 = "8".repeat(64);
    if (change === "receipt") h.step.wait_disposition.facts.evidence_ids = ["context-capacity://" + "8".repeat(64)];
    if (change === "capability") h.state.operationManifest.operation_contract_version = 7;
    await h.tick();
    assert.equal(await old.evaluate(node => node.isConnected), false, change);
    await old.evaluate(node => node.click()); assert.equal(writes.length, 0, change);
  }
});

test("exact approval only pauses and explicit separate continue uses the saved original binding", async t => {
  const h = await waiting(t, {ready: true}); const writes = await captureWrites(h);
  assert.equal(await h.panel.getByRole("button", {name: "继续原需求", exact: true}).count(), 0);
  await h.panel.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).click();
  await h.page.waitForFunction(() => operations.some(item => item.operation_id === "operation_write_1"));
  assert.equal(writes.length, 1);
  assert.deepEqual(writes[0], {action: "EXECUTE_EXECUTION_BASELINE", project_id: h.request.project_id,
    delivery_id: h.request.id, expected_checkpoint_sha256: h.request.checkpoint_sha256, task_id: h.task.task_id,
    expected_plan_sha256: h.plan.plan_sha256, continuation_mode: "pause", reference: writes[0].reference});
  assert.match(writes[0].reference, /代码版本保持/);
  h.step.status = "WAITING_HUMAN";
  Object.assign(h.step.wait_disposition.facts, {classification: "EXECUTION_BASELINE_PAUSED", execution_baseline_sha256: "6".repeat(64)});
  h.step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
  h.step.wait_disposition_sha256 = "7".repeat(64);
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  const paused = h.page.locator("#detail .engineering-baseline-pause");
  assert.match(await paused.innerText(), /没有启动新的 Coder/);
  assert.equal(writes.length, 1, "PAUSE does not submit RESUME");
  await paused.getByRole("button", {name: "继续原需求", exact: true}).click();
  await h.page.waitForFunction(() => operations.some(item => item.operation_id === "operation_write_2"));
  assert.equal(writes.length, 2);
  assert.deepEqual(writes[1], {...h.bound, action: "RESUME_EXECUTION_BASELINE",
    expected_execution_baseline_sha256: "6".repeat(64), expected_disposition_sha256: "7".repeat(64), reference: writes[1].reference});
});
