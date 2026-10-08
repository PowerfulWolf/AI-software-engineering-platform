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
  assert.match(await panel.innerText(), /原执行是否已结束还没有可靠记录/);
  assert.match(await panel.innerText(), /重复调查不会补齐缺失记录/);
  assert.equal(await binding.evaluate(node => node.open), false);
  assert.equal(await panel.getByRole("button", {name: "继续原交付", exact: true}).count(), 0);
  Object.assign(proof, {proof_sha256: "f".repeat(64), missing: [],
    permitted_resolutions: ["RETRY_FROM_CHECKPOINT"], next_action: "现场已核验，可记录精确继续决定。"});
  await h.tick();
  assert.match(await panel.innerText(), /检查已通过，可按以下方案继续/);
  assert.equal(await panel.getByRole("button", {name: "继续原交付", exact: true}).isVisible(), true,
    "a decision backed by the current proof is directly visible");
  await panel.getByRole("button", {name: "继续原交付", exact: true}).click();
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
  assert.match(await panel.innerText(), /继续决定已记录/);
  assert.equal(await panel.getByRole("button", {name: "继续原交付", exact: true}).count(), 0);
  assert.match(await detail.innerText(), /操作记录（完整历史）/);
  await detail.locator('.request-history-fold[data-key^="operation-history:"] > summary').click();
  assert.match(await detail.innerText(), /operator:fixture/);
});

test("product users ask the platform to handle an interruption and see honest maintenance guidance", async t => {
  const h = await ui(t);
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{root: "/fixture", selected_paths: ["."], delivery_id: "delivery_handle"}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "EXECUTION_UNCERTAIN",
    reason: "原工作没有返回完整结果，原进度需要检查。", next_action: "平台处理原执行后继续。"};
  const facts = {task_id: "task_handle", work_item_id: "work_handle", role: "coder",
    task_intent_sha256: "b".repeat(64), source_revision: "c".repeat(40), checkpoint_sequence: 4};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_HUMAN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  h.team.tasks.push({id: "delivery_handle", task_id: facts.task_id, request_id: request.id,
    project_id: request.project_id, title: request.title, status: "IMPLEMENTING", terminal: false,
    scope: request.scopes[0], last_activity: "2026-10-05T00:00:00Z", execution: request.execution,
    assignments: [], documents: [], timeline: [], runs: [], role_queue: [step]});
  const submitted = [];
  let writes = 0;
  h.page.on("request", req => {if (req.method() !== "GET") writes++;});
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const intent = route.request().postDataJSON().intent;
    submitted.push(intent);
    const record = operation("QUEUED", {operation_id: "operation_handle", intent,
      updated_at: "2026-10-05T01:00:00Z"});
    h.state.operations.push(record);
    await route.fulfill({status: 202, json: record});
  });
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  const panel = detail.locator('section.engineering-wait-panel[data-key="engineering:work_handle"]');
  assert.deepEqual(await panel.locator(".engineering-wait-facts dt").allTextContents(),
    ["发生了什么", "开发进度", "平台可以做什么", "你需要做什么"]);
  assert.equal(await panel.getByRole("button", {name: "让平台处理中断", exact: true}).isVisible(), true);
  assert.equal(writes, 0);
  await panel.getByRole("button", {name: "让平台处理中断", exact: true}).click();
  await h.close();
  assert.equal(submitted[0].action, "HANDLE_DELIVERY_WAIT");
  assert.equal(submitted[0].expected_disposition_sha256, step.wait_disposition_sha256);
  assert.equal(submitted[0].expected_checkpoint_sha256, request.checkpoint_sha256);
  assert.equal(Object.hasOwn(submitted[0], "process_stopped"), false);
  Object.assign(h.state.operations[0], {status: "RUNNING"});
  await h.tick();
  assert.match(await panel.innerText(), /平台正在处理中断/);
  const proof = {kind: "delivery_wait_investigation", ...facts, disposition_sha256: step.wait_disposition_sha256,
    proof_sha256: "e".repeat(64), inspected_at: "2026-10-05T01:10:00Z", missing: ["STOP_UNRECORDED"],
    permitted_resolutions: [], next_action: "缺少可信停止记录，需工程核验。"};
  const handling = {kind: "delivery_wait_handling", schema_version: "v1", ...facts,
    disposition_sha256: step.wait_disposition_sha256, investigation: proof, status: "PLATFORM_ATTENTION",
    manual_resolution_allowed: false, handling_sha256: "f".repeat(64), handled_at: "2026-10-05T01:10:00Z",
    summary: "平台尚未取得原执行的结束记录，不能安全继续。",
    user_action: "请将处理报告交给平台维护者，无需自行确认执行记录。",
    recheck_when: "平台维护者修复原执行记录后再检查。"};
  Object.assign(h.state.operations[0], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, engineering_wait_handling: handling,
  }});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.match(await panel.innerText(), /平台尚未取得原执行的结束记录/);
  assert.match(await panel.innerText(), /处理方 · 平台执行服务或维护者/);
  assert.match(await panel.innerText(), /无需自行确认执行记录/);
  assert.match(await panel.innerText(), /平台维护者修复原执行记录后再检查/);
  assert.doesNotMatch(await panel.innerText(), /可信停止|Manager.*(?:正在|已经)/);
  assert.equal(await panel.getByRole("button", {name: "继续原交付", exact: true}).count(), 0);
  assert.equal(await panel.getByRole("button", {name: "让平台处理中断", exact: true}).count(), 0);
  assert.equal(await panel.getByRole("button", {name: "重新检查状态", exact: true}).getAttribute("class"), "secondary");
  assert.equal(await panel.locator(".engineering-wait-binding").evaluate(node => node.open), false);
  assert.match(await detail.locator(".product-execution-summary").innerText(), /等待工程处理/);
  for (const width of [1440, 1024, 390]) {
    await h.page.setViewportSize({width, height: 1000});
    assert.equal(await panel.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    assert.equal(await panel.locator(".engineering-wait-facts").evaluate(node => parseFloat(getComputedStyle(node).fontSize)), 14);
    if (process.env.ASE_UI_SCREENSHOT_DIR) {
      await panel.scrollIntoViewIfNeeded();
      await h.page.screenshot({path: process.env.ASE_UI_SCREENSHOT_DIR + `/engineering-handling-${width}.png`});
    }
  }
  await h.page.evaluate(() => Object.defineProperty(navigator, "clipboard", {configurable: true,
    value: {writeText: async value => {window.copiedHandlingReport = value;}}}));
  await panel.getByRole("button", {name: "复制处理报告", exact: true}).click();
  await h.close();
  assert.match(await h.page.evaluate(() => window.copiedHandlingReport), /ASE 交付处理报告/);
  assert.match(await h.page.evaluate(() => window.copiedHandlingReport), /待处理事项 · 原执行是否已结束还没有可靠记录/);
  assert.match(await h.page.evaluate(() => window.copiedHandlingReport), /任务 · task_handle/);
  proof.missing = [];
  proof.permitted_resolutions = ["RETRY_FROM_CHECKPOINT"];
  Object.assign(proof, {interruption_receipt_sha256: "1".repeat(64), process_stop_sha256: "2".repeat(64),
    workspace_inventory_sha256: "3".repeat(64)});
  handling.collection_failed = true;
  handling.summary = "平台未通过执行事实收集校验，需要维护者处理，原工作区和记录已保留。";
  handling.user_action = "复制处理报告交给平台维护者。";
  await h.tick();
  assert.match(await panel.innerText(), /部分执行事实已核验，但收集校验失败，当前不能继续/);
  assert.doesNotMatch(await panel.innerText(), /检查已通过，可按以下方案继续/);
  assert.equal(await panel.getByRole("button", {name: "继续原交付", exact: true}).count(), 0);
  await panel.getByRole("button", {name: "复制处理报告", exact: true}).click();
  await h.close();
  assert.match(await h.page.evaluate(() => window.copiedHandlingReport), /收集校验失败，当前不能继续/);
  assert.doesNotMatch(await h.page.evaluate(() => window.copiedHandlingReport), /检查已通过|已恢复|已交付/);
  assert.equal(writes, 1, "copying and reading a result cannot submit another delivery command");
  handling.collection_failed = false;
  handling.status = "NEEDS_AUTHORIZATION";
  handling.summary = "检查已通过，需要工程授权者确认所列继续方案。";
  handling.user_action = "请工程授权者确认按页面所列方案继续。";
  proof.missing = [];
  proof.permitted_resolutions = ["RETRY_FROM_CHECKPOINT"];
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await panel.getByRole("button", {name: "继续原交付", exact: true}).count(), 0,
    "product duty cannot approve an engineering resolution");
  handling.manual_resolution_allowed = true;
  await h.tick();
  assert.equal(await panel.getByRole("button", {name: "继续原交付", exact: true}).isVisible(), true);
  await panel.getByRole("button", {name: "继续原交付", exact: true}).evaluate(node => {window.oldHandlingApproval = node;});
  h.state.operations.push(operation("FAILED", {operation_id: "inspection_failed_newer",
    intent: {...submitted[0], action: "INSPECT_DELIVERY_WAIT"}, updated_at: "2026-10-05T02:00:00Z"}));
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await panel.getByRole("button", {name: "继续原交付", exact: true}).count(), 0);
  await h.page.evaluate(() => window.oldHandlingApproval.click());
  assert.equal(writes, 1, "a retained old approval closure cannot consume a proof invalidated by a newer failed check");
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
