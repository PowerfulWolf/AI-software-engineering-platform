const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");

test("engineering wait investigation and decision use exact proof without hiding the durable wait", async (t) => {
  const h = await ui(t);
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{root: "/fixture", selected_paths: ["."], delivery_id: "delivery_wait"}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "EXECUTION_UNCERTAIN",
    reason: "原执行结果待核验。", next_action: "工程授权者调查原执行与现场。"};
  const facts = {task_id: "task_wait", work_item_id: "work_wait", role: "coder",
    task_intent_sha256: "b".repeat(64), source_revision: "c".repeat(64), checkpoint_sequence: 4};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_HUMAN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  h.team.tasks.push({id: "delivery_wait", task_id: "task_wait", request_id: request.id,
    project_id: request.project_id, title: request.title, status: "IMPLEMENTING", terminal: false,
    scope: request.scopes[0], last_activity: "2026-10-05T00:00:00Z", execution: request.execution,
    assignments: [], documents: [], timeline: [], runs: [], role_queue: [step]});
  const submitted = [];
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const intent = route.request().postDataJSON().intent;
    submitted.push(intent);
    const record = operation("QUEUED", {operation_id: "operation_engineering_" + submitted.length,
      intent, updated_at: `2026-10-05T0${submitted.length}:00:00Z`});
    h.state.operations.push(record);
    await route.fulfill({status: 202, json: record});
  });
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  assert.match(await detail.innerText(), /等待工程处理/);
  assert.doesNotMatch(await detail.innerText(), /d{64}/);
  assert.equal(await detail.getByRole("button", {name: "继续交付", exact: true}).count(), 0);
  const panel = detail.locator('section.engineering-wait-panel[data-key="engineering:work_wait"]');
  assert.equal(await panel.isVisible(), true, "current engineering intervention is visible without opening a disclosure");
  assert.equal(await panel.getByRole("button", {name: "调查工程等待", exact: true}).isVisible(), true);
  const binding = panel.locator("details.engineering-wait-binding");
  assert.equal(await binding.evaluate(node => node.open), false, "exact technical identities remain a secondary disclosure");
  await panel.getByRole("button", {name: "调查工程等待", exact: true}).click();
  await h.close();
  await panel.evaluate(node => {window.engineeringWaitPanel = node;});
  assert.equal(submitted[0].expected_disposition_sha256, "d".repeat(64));
  assert.equal(submitted[0].expected_checkpoint_sequence, 4);
  const proof = {kind: "delivery_wait_investigation", task_id: facts.task_id, work_item_id: facts.work_item_id,
    disposition_sha256: "d".repeat(64), task_intent_sha256: facts.task_intent_sha256,
    source_revision: facts.source_revision, checkpoint_sequence: 4, proof_sha256: "e".repeat(64),
    inspected_at: "2026-10-05T01:10:00Z", missing: ["STOP_UNRECORDED"], permitted_resolutions: [],
    next_action: "缺少可信停止记录，继续等待工程核验。"};
  Object.assign(h.state.operations[0], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, engineering_wait_investigation: proof,
  }});
  await h.tick();
  assert.equal(await panel.evaluate(node => node === window.engineeringWaitPanel), true, "the visible intervention panel survives polling");
  assert.match(await panel.innerText(), /缺少可信停止记录/);
  assert.equal(await binding.evaluate(node => node.open), false);
  assert.equal(await panel.getByRole("button", {name: "确认现场并继续原交付", exact: true}).count(), 0);
  Object.assign(proof, {proof_sha256: "f".repeat(64), missing: [],
    permitted_resolutions: ["RETRY_FROM_CHECKPOINT"], next_action: "现场已核验，可记录精确继续决定。"});
  await h.tick();
  assert.match(await panel.innerText(), /现场已核验，可记录精确继续决定/);
  assert.equal(await panel.getByRole("button", {name: "确认现场并继续原交付", exact: true}).isVisible(), true,
    "a decision backed by the current proof is directly visible");
  await panel.getByRole("button", {name: "确认现场并继续原交付", exact: true}).click();
  await h.close();
  assert.equal(submitted[1].action, "RESOLVE_DELIVERY_WAIT");
  assert.equal(submitted[1].proof_sha256, "f".repeat(64));
  assert.equal(Object.hasOwn(submitted[1], "process_stopped"), false);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {engineering_wait_resolution: {
    kind: "delivery_wait_resolution", resolution_kind: "RETRY_FROM_CHECKPOINT", proof_sha256: proof.proof_sha256,
    authorization_source: "engineering_operator_decision", operator_principal: {operator_id: "operator:fixture"},
  }}});
  await h.tick();
  assert.match(await detail.locator(".product-execution-summary").innerText(), /等待工程处理/);
  assert.match(await panel.innerText(), /工程决定已记录/);
  assert.equal(await panel.getByRole("button", {name: "确认现场并继续原交付", exact: true}).count(), 0);
  assert.match(await detail.innerText(), /操作记录（完整历史）/);
  await detail.locator('.request-history-fold[data-key^="operation-history:"] > summary').click();
  assert.match(await detail.innerText(), /operator:fixture/);
});

test("original branch baseline update has a separate exact engineering plan and decision", async (t) => {
  const h = await ui(t);
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{root: "/fixture", selected_paths: ["."], delivery_id: "delivery_baseline"}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "SOURCE_PREPARATION_DRIFT",
    reason: "代码执行输入需要工程核验。", next_action: "核验原分支和平台修复版本。"};
  const facts = {task_id: "task_baseline", work_item_id: "work_baseline", role: "coder",
    task_intent_sha256: "b".repeat(64), source_revision: "c".repeat(40), checkpoint_sequence: 4};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_HUMAN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  h.team.tasks.push({id: "delivery_baseline", task_id: facts.task_id, task_revision: 4,
    task_intent_sha256: facts.task_intent_sha256, request_id: request.id, project_id: request.project_id,
    title: request.title, status: "IMPLEMENTING", terminal: false, scope: request.scopes[0],
    last_activity: "2026-10-05T00:00:00Z", execution: request.execution,
    assignments: [], documents: [], timeline: [], runs: [], role_queue: [step]});
  let writes = 0;
  h.page.on("request", req => {if (req.method() !== "GET") writes++;});
  const submitted = [];
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const intent = route.request().postDataJSON().intent;
    submitted.push(intent);
    const record = operation("QUEUED", {operation_id: "operation_baseline_" + submitted.length,
      intent, updated_at: `2026-10-05T0${submitted.length}:00:00Z`});
    h.state.operations.push(record);
    await route.fulfill({status: 202, json: record});
  });
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  assert.doesNotMatch(await detail.innerText(), /c{40}/);
  const wait = detail.locator('section.engineering-wait-panel[data-key="engineering:work_baseline"]');
  assert.equal(await wait.isVisible(), true);
  assert.equal(await wait.locator("details.engineering-wait-binding").evaluate(node => node.open), false);
  const baseline = detail.locator('.engineering-baseline-panel[data-key="engineering:work_baseline:baseline"]');
  assert.equal(await baseline.evaluate(node => node.tagName === "DETAILS" && !node.open), true,
    "an optional baseline investigation stays secondary until an exact plan needs review");
  await baseline.locator("summary").first().click();
  assert.equal(await baseline.getByRole("button", {name: "批准并更新原分支基线", exact: true}).count(), 0);
  const input = baseline.getByRole("textbox", {name: "目标代码完整版本"});
  await input.fill("f".repeat(40));
  await input.evaluate(node => {
    window.baselineInput = node;
    window.baselineForm = node.closest(".engineering-baseline-form");
  });
  request.title += " · 只读事实更新";
  h.team.tasks[0].last_activity = "2026-10-05T00:01:00Z";
  await h.tick();
  assert.equal(await input.evaluate(node => node === window.baselineInput &&
    node.closest(".engineering-baseline-form") === window.baselineForm && document.activeElement === node), true,
    "unrelated titles and heartbeats preserve the exact form, input and editing focus");
  assert.equal(await input.inputValue(), "f".repeat(40));
  assert.equal(await baseline.evaluate(node => node.open), true);
  for (const width of [1440, 1024, 390]) {
    await h.page.setViewportSize({width, height: 900});
    const layout = await baseline.evaluate(node => {
      const form = node.querySelector(".engineering-baseline-form");
      const field = form.querySelector("label");
      const input = form.querySelector("input");
      const button = form.querySelector("button");
      const text = document.createRange();
      text.selectNode(field.firstChild);
      const labelText = text.getBoundingClientRect();
      const inputRect = input.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();
      const panelRect = node.getBoundingClientRect();
      return {
        fonts: [field, input, button].map(el => parseFloat(getComputedStyle(el).fontSize)),
        labelGap: inputRect.top - labelText.bottom,
        buttonGap: buttonRect.top - inputRect.bottom,
        inside: [inputRect, buttonRect].every(rect => rect.left >= panelRect.left && rect.right <= panelRect.right + 1),
      };
    });
    assert.ok(layout.fonts.every(size => size >= 13 && size <= 15) && new Set(layout.fonts).size === 1,
      `baseline label, input and button typography is coordinated at ${width}px: ${layout.fonts}`);
    assert.ok(layout.labelGap >= 6 && layout.buttonGap >= 8,
      `baseline form has readable vertical spacing at ${width}px: ${layout.labelGap}/${layout.buttonGap}`);
    assert.equal(layout.inside, true, `baseline controls stay within their card at ${width}px`);
    assert.equal(await detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    if (process.env.ASE_UI_SCREENSHOT_DIR) {
      await input.scrollIntoViewIfNeeded();
      await h.page.screenshot({path: process.env.ASE_UI_SCREENSHOT_DIR + `/engineering-baseline-${width}.png`});
    }
  }
  assert.equal(writes, 0, "reading, drafting, polling and layout checks do not issue delivery commands");
  await baseline.getByRole("button", {name: "调查并保留原草稿", exact: true}).click();
  await h.close();
  assert.equal(submitted[0].expected_task_revision, 4);
  assert.equal(submitted[0].expected_source_revision, facts.source_revision);
  assert.equal(submitted[0].input_mode, "preserve_draft");
  const plan = {plan_sha256: "e".repeat(64), target_base_ref: "f".repeat(40),
    input_mode: "preserve_draft", conflicted: false, dirty_capture: {source_revision: facts.source_revision},
    facts: {task: {id: facts.task_id, branch_name: "ai/feature/original"},
      task_revision: 4, work_item_id: facts.work_item_id}};
  Object.assign(h.state.operations[0], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan,
  }});
  await h.tick();
  assert.equal(await baseline.evaluate(node => node.tagName === "SECTION" && node.classList.contains("engineering-baseline-pending")), true,
    "a current unexecuted plan is promoted to a visible review section");
  assert.equal(await baseline.locator(":scope > h4").isVisible(), true);
  assert.match(await baseline.innerText(), /ai\/feature\/original/);
  assert.equal(await baseline.getByRole("textbox", {name: "目标代码完整版本"}).evaluate(node => node !== window.baselineInput), true,
    "an exact new plan replaces the original draft controls rather than retaining stale callbacks");
  assert.equal(await baseline.getByRole("button", {name: "批准并更新原分支基线", exact: true}).isVisible(), true);
  await baseline.getByRole("button", {name: "批准并更新原分支基线", exact: true}).click();
  await h.close();
  assert.equal(submitted[1].action, "EXECUTE_EXECUTION_BASELINE");
  assert.equal(submitted[1].expected_plan_sha256, plan.plan_sha256);
  assert.equal(submitted[1].expected_checkpoint_sha256, request.checkpoint_sha256);
  assert.equal(Object.hasOwn(submitted[1], "operator_id"), false);
  assert.match(await detail.locator(".product-execution-summary").innerText(), /等待工程处理/);
});
