const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");

test("product execution summary separates phase from engineering wait and retry", async (t) => {
  const h = await ui(t);
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{root: "/fixture", selected_paths: ["."], delivery_id: "delivery_execution"}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "WAITING_HUMAN",
    reason: "开发等待工程前提处理。", next_action: "工程团队处理，当前无需产品操作。",
    action_required: false, receipt_uri: "receipt://technical-hash", policy_id: "policy_technical"};
  h.team.tasks.push({id: "delivery_execution", request_id: request.id, project_id: request.project_id,
    title: request.title, status: "IMPLEMENTING", checkpoint_stage: "DELIVERING", terminal: false,
    scope: request.scopes[0], last_activity: "2026-10-04T00:00:00Z", next_action: "old next",
    execution: request.execution, assignments: [], documents: [], timeline: [], runs: [],
    role_queue: [{role: "coder", status: "WAITING_HUMAN", lease_liveness: "UNKNOWN"}]});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const summary = h.page.locator(".product-execution-summary");
  const text = await summary.innerText();
  assert.match(text, /交付阶段 · 实现/);
  assert.match(text, /当前执行 · 等待工程处理/);
  assert.match(text, /处理方 · 工程团队/);
  assert.doesNotMatch(text, /technical-hash|policy_technical|租约|lease/);
  assert.doesNotMatch(await h.page.locator("#detail").innerText(), /technical-hash|policy_technical/);
  await h.page.getByText("需求工程详情", {exact: true}).click();
  assert.match(await h.page.locator("#detail").innerText(), /technical-hash/);
  request.execution = {...request.execution, state: "RETRY_SCHEDULED", responsibility: "team",
    reason_code: "ROLE_RETRY_SCHEDULED", reason: "已安排开发重试。", available_at: "2026-10-04T00:00:45Z"};
  h.team.tasks[0].execution = request.execution;
  h.team.tasks[0].role_queue[0].status = "RETRY_SCHEDULED";
  await h.tick();
  assert.equal(await h.page.locator(".delivery-flow li.current").count(), 0);
  assert.equal(await h.page.locator(".delivery-flow li.paused").count(), 1);
  assert.match(await summary.innerText(), /待重试/);
  assert.match(await summary.innerText(), /计划重试时间/);
});

test("legacy product approval facts show Chinese actions and retain the original read-side facts", async (t) => {
  const h = await ui(t);
  const original = "Review product_spec and approve this exact checkpoint, or reply with revisions.";
  Object.assign(h.team.requests[0], {stage: "WAITING_PRODUCT_APPROVAL", next_action: original, blocker: original,
    execution: {state: "WAITING", responsibility: "product", reason_code: "WAITING_PRODUCT_APPROVAL",
      reason: original, next_action: original, action_required: true}});
  h.state.operations = [operation("SUCCEEDED", {result: {next_action: original}})];
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  const expected = "请审阅本版产品规格并批准，或回复需要修改的内容。";
  assert.match(await detail.locator(".product-execution-summary").innerText(), new RegExp(expected));
  assert.match(await detail.locator(".execution-history").innerText(), new RegExp(expected));
  assert.doesNotMatch(await detail.innerText(), /Review product_spec and approve/);
  assert.equal(await h.page.evaluate(() => snapshot.requests[0].execution.next_action), original);
  assert.equal(await h.page.evaluate(() => operations[0].result.next_action), original);
  assert.equal(await detail.getByRole("button", {name: "批准 ProductSpec 并开始交付", exact: true}).count(), 1);
});

test("delivery node colors follow operation, wait and completion facts instead of executor heartbeat", async (t) => {
  const h = await ui(t);
  await h.requests();
  const request = h.team.requests[0];
  Object.assign(request, {stage: "DESIGNING", execution: {state: "UNKNOWN", responsibility: "team",
    reason_code: "EXECUTION_UNCONFIRMED", reason: "尚无执行器心跳。", next_action: "请核对执行状态。", action_required: false}});
  h.state.operations = [operation("RUNNING", {intent: {action: "PRODUCT_APPROVAL", delivery_id: request.id, project_id: request.project_id}})];
  await h.tick();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const flow = h.page.locator(".delivery-flow");
  const color = index => flow.locator("li").nth(index).locator("span").evaluate(node => getComputedStyle(node).backgroundColor);
  assert.equal(await color(0), "rgb(23, 99, 75)");
  assert.equal(await color(1), "rgb(36, 89, 204)");
  assert.match(await flow.locator("li").nth(1).innerText(), /执行中/);
  assert.equal(await flow.locator("li").nth(1).getAttribute("aria-current"), "step");
  assert.match(await h.page.locator(".request-node-badge").first().innerText(), /执行中/);
  assert.match(await h.page.locator(".product-execution-summary").innerText(), /当前执行 · 执行中/);
  assert.equal(await h.page.evaluate(() => snapshot.requests[0].execution.state), "UNKNOWN");
  await h.close();
  await h.page.getByText("需求工程详情", {exact: true}).click();
  assert.match(await h.page.locator("#detail").innerText(), /执行事实状态 · 执行状态待确认/);
  request.execution.state = "WAITING"; request.execution.responsibility = "engineering";
  await h.tick();
  assert.equal(await color(1), "rgb(198, 40, 40)");
  assert.match(await flow.locator("li").nth(1).innerText(), /已阻塞/);
  request.execution.state = "UNKNOWN"; request.execution.responsibility = "team";
  h.state.operations[0].status = "QUEUED";
  await h.tick();
  assert.equal(await color(1), "rgb(226, 232, 240)");
  assert.match(await flow.locator("li").nth(1).innerText(), /已排队/);
  h.state.operations = [];
  await h.tick();
  assert.match(await flow.locator("li").nth(1).innerText(), /待继续/);
  request.stage = "DONE"; request.execution.state = "COMPLETED";
  await h.tick();
  assert.equal(await flow.locator("li.done").count(), 7);
  assert.equal(await color(6), "rgb(23, 99, 75)");
  assert.match(await flow.locator("li").nth(6).innerText(), /已完成/);
});

test("polling updates the card phase when all three native role nodes stay running", async (t) => {
  const h = await ui(t);
  await h.requests();
  const request = h.team.requests[0];
  Object.assign(request, {stage: "DELIVERING", scopes: [{root: "/fixture", selected_paths: ["."], delivery_id: "native_current"}],
    execution: {state: "UNKNOWN", responsibility: "team", reason_code: "EXECUTION_UNCONFIRMED",
      reason: "尚无执行器心跳。", next_action: "核对状态。", action_required: false}});
  const task = {id: "native_current", project_id: request.project_id, request_id: request.id, title: request.title,
    status: "IMPLEMENTING", terminal: false, last_activity: "2026-10-04T00:01:00Z", next_action: "请等待当前角色。",
    scope: request.scopes[0], role_queue: [], assignments: [], documents: [], timeline: [], runs: []};
  h.team.tasks.push(task);
  for (const [status, role, phase] of [["IMPLEMENTING", "coder", "实现"], ["QA", "qa", "测试"], ["REVIEW", "reviewer", "评审"]]) {
    task.status = status;
    task.role_queue = [{role, status: "RUNNING", lease_liveness: "LEASE_VALID"}];
    await h.tick();
    assert.equal(await h.page.locator("#content .request-node-badge").innerText(), `${phase} · 执行中`);
    await h.page.evaluate(() => showDetail("request", "request_fixture"));
    assert.equal(await h.page.locator("#detail .request-node-badge").innerText(), `${phase} · 执行中`);
  }
});

test("host interruption turns the retained stage and Designer queue red and offers exact continuation", async (t) => {
  const h = await ui(t);
  await h.requests();
  const request = h.team.requests[0];
  Object.assign(request, {stage: "DESIGNING", checkpoint_sha256: "b".repeat(64),
    execution: {state: "UNKNOWN", responsibility: "engineering", reason: "尚无执行事实。",
      next_action: "核对执行状态。", action_required: false}});
  h.team.agents = [{id: "designer", name: "设计成员", roles: ["designer"], enabled: true,
    max_parallel_assignments: 1, assigned_delivery_ids: [request.id], current_stage_delivery_ids: [request.id], history_delivery_ids: []}];
  const original = "The console host stopped before the operation completed.";
  h.state.operations = [operation("INTERRUPTED", {result: null, error_code: "HOST_INTERRUPTED", error_summary: original,
    intent: {action: "PRODUCT_APPROVAL", project_id: request.project_id, delivery_id: request.id,
      expected_checkpoint_sha256: "a".repeat(64)}})];
  await h.tick();
  await h.close();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  assert.equal(await detail.locator(".delivery-flow li").nth(1).locator("span").evaluate(node => getComputedStyle(node).backgroundColor), "rgb(198, 40, 40)");
  assert.match(await detail.locator(".product-execution-summary").innerText(), /操作已中断/);
  assert.doesNotMatch(await detail.locator(".product-execution-summary").innerText(), /状态待核对|尚无执行事实/);
  const stoppedBadge = detail.locator(".execution-history .badge.execution-interrupted");
  assert.equal(await stoppedBadge.evaluate(node => getComputedStyle(node).color), "rgb(198, 40, 40)");
  assert.match(await detail.locator(".execution-history").innerText(), /服务在本次操作完成前已停止/);
  assert.equal(await detail.getByRole("button", {name: "继续设计", exact: true}).isVisible(), true);
  assert.equal(await detail.getByRole("button", {name: "批准 ProductSpec 并开始交付", exact: true}).count(), 0);
  await h.page.locator("#nav-team").click();
  assert.match(await h.page.locator(".agent-roster").innerText(), /已阻塞/);
  assert.equal(await h.page.locator(".agent-queue.blocked .work-row").count(), 1);
  assert.equal(await h.page.locator(".agent-queue.active .work-row").count(), 0);
  assert.match(await h.page.locator(".team-summary").innerText(), /1\s+项当前 Project 待处理需求/);
  assert.match(await h.page.locator(".agent-queue.blocked .work-row").innerText(), /设计 · 操作已中断/);
  h.state.operations[0].status = "RUNNING";
  await h.tick();
  assert.match(await h.page.locator(".agent-roster").innerText(), /执行中/);
  assert.equal(await h.page.locator(".agent-queue.active .work-row").count(), 1);
  assert.match(await h.page.locator(".team-summary").innerText(), /0\s+项当前 Project 待处理需求/);
  h.state.operations[0].status = "INTERRUPTED";
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const submitted = [];
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const {intent} = route.request().postDataJSON(); submitted.push(intent);
    const accepted = operation("QUEUED", {operation_id: "continuation", updated_at: "2026-10-05T12:34:00Z", intent});
    h.state.operations.push(accepted);
    return route.fulfill({json: accepted});
  });
  await detail.getByRole("button", {name: "继续设计", exact: true}).click();
  await h.page.waitForFunction(() => operations.some(item => item.operation_id === "continuation"));
  assert.deepEqual(submitted, [{action: "CONTINUE_DELIVERY", project_id: request.project_id,
    delivery_id: request.id, expected_checkpoint_sha256: "b".repeat(64)}]);
  assert.equal(await h.page.evaluate(() => operations.find(item => item.operation_id === "operation_fixture").error_summary), original);
  assert.equal(await h.page.evaluate(() => snapshot.requests[0].execution.state), "UNKNOWN");
  assert.deepEqual(h.team.agents[0].current_stage_delivery_ids, [request.id]);
});

test("claimed role changes update member queues without painting other assignments as executing", async (t) => {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {stage: "DELIVERING", execution: {state: "UNKNOWN", responsibility: "engineering",
    reason: "尚无执行事实。", next_action: "核验执行状态。", action_required: false}});
  const task = {id: "native", request_id: request.id, project_id: request.project_id, title: "当前任务",
    status: "IMPLEMENTING", terminal: false, last_activity: "2026-10-05T12:34:00Z", scope: {root: "/fixture", selected_paths: ["src/**"]},
    next_action: "请等待当前角色。", execution: request.execution, assignments: [], role_queue: [], documents: [], timeline: [], runs: []};
  h.team.tasks.push(task);
  h.team.agents = ["coder", "qa", "reviewer"].map(role => ({id: role, name: role, roles: [role], enabled: true,
    max_parallel_assignments: 1, assigned_delivery_ids: [task.id], current_stage_delivery_ids: role === "coder" ? [task.id] : [], history_delivery_ids: []}));
  task.assignments = h.team.agents.map(agent => ({agent_id: agent.id, role: agent.id, current_stage: agent.id === "coder"}));
  task.role_queue = [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID"}];
  await h.tick();
  await h.page.locator("#nav-team").click();
  await h.page.locator(".agent-roster button").filter({hasText: "coder"}).click();
  assert.match(await h.page.locator(".agent-queue.active .work-row").innerText(), /执行中/);
  task.status = "QA"; task.role_queue = [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID"}, {role: "qa", status: "RUNNING", lease_liveness: "LEASE_VALID"}];
  task.assignments.forEach(assignment => {assignment.current_stage = assignment.role === "qa";});
  h.team.agents.forEach(agent => {agent.current_stage_delivery_ids = agent.id === "qa" ? [task.id] : [];});
  await h.tick();
  const coderRow = h.page.locator(".agent-queue.waiting .work-row");
  assert.match(await coderRow.innerText(), /本轮已完成/);
  assert.doesNotMatch(await coderRow.innerText(), /执行中/);
  await h.page.locator(".agent-roster button").filter({hasText: "reviewer"}).click();
  assert.doesNotMatch(await h.page.locator(".agent-queue.waiting .work-row").innerText(), /执行中/);
  await h.page.locator(".agent-roster button").filter({hasText: "qa"}).click();
  assert.match(await h.page.locator(".agent-queue.active .work-row").innerText(), /执行中/);
  task.role_queue = [];
  await h.tick();
  assert.equal(await h.page.locator(".agent-queue.active .work-row").count(), 0);
  assert.match(await h.page.locator(".agent-queue.blocked .work-row").innerText(), /等待工程处理/);
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const summary = h.page.locator("#detail .product-execution-summary");
  assert.match(await summary.innerText(), /等待工程处理/);
  assert.doesNotMatch(await summary.innerText(), /执行状态待确认|状态待核对/);
  assert.equal(await h.page.locator("#detail").getByRole("button", {name: "继续交付", exact: true}).count(), 0);
  task.role_queue = [{role: "qa", status: "READY", lease_liveness: "UNKNOWN"}];
  await h.tick();
  assert.match(await summary.innerText(), /已排队/);
  assert.doesNotMatch(await summary.innerText(), /尚无执行事实|处理方 · 工程团队/);
});
