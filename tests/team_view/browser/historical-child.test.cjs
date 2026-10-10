const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");

test("historical child stays auditable without becoming a current blocker, queue or count", async (t) => {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {id: "delivery_multi_original", title: "K1", stage: "PLANNING",
    scopes: [{root: "/fixture/repo", selected_paths: ["."], reference_only: false}],
    next_action: "继续计划", execution: {state: "UNKNOWN", responsibility: "team",
      reason_code: "PLANNING", reason: "计划已保存。", next_action: "继续计划"}});
  const old = {id: "delivery_old", request_id: request.id, project_id: request.project_id,
    title: "K1", status: "BLOCKED", checkpoint_stage: "DESIGNING", terminal: true,
    scope: {...request.scopes[0], delivery_id: "delivery_old"}, blocker: "旧设计的验证类型不匹配。",
    last_activity: "2026-10-01T00:00:00Z", next_action: "旧恢复建议",
    assignments: [], documents: [], timeline: [], runs: [], role_queue: []};
  h.team.tasks = [old];
  h.team.agents = [{id: "coder", name: "开发成员", roles: ["coder"], enabled: true,
    max_parallel_assignments: 1, assigned_delivery_ids: [], current_stage_delivery_ids: [],
    history_delivery_ids: [old.id]}];
  h.state.operations = [operation("RUNNING", {intent: {action: "CONTINUE_DELIVERY",
    project_id: request.project_id, delivery_id: request.id}})];
  await h.tick();
  await h.requests();
  await h.close();
  assert.equal(await h.page.locator("#content article.request").count(), 1);
  await h.page.evaluate(() => showDetail("request", "delivery_multi_original"));
  const detail = h.page.locator("#detail");
  assert.match(await detail.locator(".product-execution-summary").innerText(), /计划编排/);
  assert.equal(await detail.locator(".delivery-flow li.current").count(), 1);
  assert.equal(await detail.locator(".delivery-flow li.blocked").count(), 0);
  assert.match(await detail.innerText(), /尚未生成交付任务/);
  await detail.getByText("历史仓库交付记录（1 条）", {exact: true}).click();
  assert.match(await detail.locator("details.historical-delivery-records").innerText(), /旧设计的验证类型不匹配/);
  old.blocker = "历史执行诊断已更新。";
  old.last_activity = "2026-10-01T00:05:00Z";
  await h.tick();
  assert.equal(await detail.locator("details.historical-delivery-records").evaluate(node => node.open), true);
  assert.match(await detail.locator("details.historical-delivery-records").innerText(), /历史执行诊断已更新/);
  assert.doesNotMatch(await detail.locator("details.historical-delivery-records").innerText(), /旧设计的验证类型不匹配/);
  assert.equal(await detail.locator(".delivery-flow li.blocked").count(), 0);
  await detail.getByRole("button", {name: "查看当次执行记录", exact: true}).click();
  assert.match(await detail.locator(".task-historical-context").innerText(), /历史执行记录.*不代表当前需求/s);
  assert.match(await detail.locator(".task-historical-context").innerText(), /当前需求.*计划编排.*执行中/s);
  assert.match(await detail.locator(".task-chapter-heading").first().innerText(), /当次执行结果/);
  assert.match(await detail.locator(".task-detail-overview").innerText(), /当次处理建议 · 旧恢复建议/);
  assert.doesNotMatch(await detail.locator(".task-detail-overview").innerText(), /当前执行|下一步/);
  assert.equal(await detail.locator('[data-delivery-control="true"]').count(), 0);
  await detail.getByText("任务工程详情", {exact: true}).click();
  assert.match(await detail.innerText(), /历史执行诊断已更新/);
  assert.equal(await h.page.evaluate(() => selected.id), old.id);
  await detail.getByRole("button", {name: "查看当前需求", exact: true}).click();
  assert.equal(await h.page.evaluate(() => selected.id), request.id);
  assert.equal(await detail.locator(".task-detail-dialog").count(), 0);
  assert.equal(await detail.locator(".delivery-flow li.blocked").count(), 0);
  await h.page.evaluate(() => showDetail("task", "delivery_old"));
  await detail.getByRole("button", {name: "关闭", exact: true}).click();
  await h.page.locator("#nav-team").click();
  assert.equal(await h.page.locator(".agent-queue.blocked .work-row").count(), 0);
  assert.equal(await h.page.locator(".agent-queue.completed .work-row").count(), 1);
  assert.match(await h.page.locator(".agent-queue.completed .work-row").innerText(), /历史记录/);
  assert.match(await h.page.locator(".team-summary").innerText(), /0\s+项当前 Project 未结束任务/);
  old.terminal = false;
  old.status = "IMPLEMENTING";
  await h.tick();
  assert.match(await h.page.locator(".team-summary").innerText(), /0\s+项当前 Project 未结束任务/);
  assert.equal(await h.page.locator(".agent-queue.blocked .work-row").count(), 0);
  assert.equal(await h.page.evaluate(() => snapshot.tasks[0].status), "IMPLEMENTING");
  assert.equal(await h.page.evaluate(() => snapshot.tasks.length), 1);
});

test("historical modal distinguishes current native execution and retains reports through parent-only polling", async t => {
  const h = await ui(t);
  const posts = [];
  h.page.on("request", request => {if (request.method() === "POST") posts.push(request.url());});
  const request = h.team.requests[0];
  Object.assign(request, {title: "K1", stage: "DELIVERING", scopes: [{root: "/fixture/repo",
    selected_paths: ["."], reference_only: false, delivery_id: "delivery_current"}]});
  const old = {id: "delivery_old", task_id: "task_old", request_id: request.id, project_id: request.project_id,
    title: "K1", status: "BLOCKED", terminal: true, scope: request.scopes[0],
    last_activity: "2026-10-01T00:00:00Z", blocker: "旧执行停止于产出校验。", next_action: "核实旧执行后恢复。",
    execution: {state: "STOPPED", responsibility: "engineering", reason: "旧执行停止于产出校验。",
      next_action: "核实旧执行后恢复。", action_required: false},
    assignments: [], role_queue: [], runs: [],
    documents: [{name: "完整旧报告", content: "保留的历史正文。", source_uri: "artifact://historical",
      sha256: "b".repeat(64)}],
    timeline: Array.from({length: 13}, (_, index) => ({id: "event_" + index, task_id: "task_old",
      kind: "state_event", summary: "保存的记录 " + index, source_uri: "event://" + index,
      occurred_at: "2026-10-01T00:00:00Z", details: {}}))};
  const current = {...old, id: "delivery_current", task_id: "task_current", terminal: false, status: "IMPLEMENTING",
    last_activity: "2026-10-10T00:00:00Z", blocker: null, next_action: "等待本轮执行。",
    execution: {state: "RUNNING", responsibility: "team", reason: "当前角色正在执行。",
      next_action: "等待本轮执行。", action_required: false}, documents: [], timeline: [],
    role_queue: [{role: "coder", status: "RUNNING", attempt: 8, lease_liveness: "LEASE_VALID",
      heartbeat_at: "2026-10-10T00:00:00Z"}]};
  h.team.tasks = [old, current];
  await h.tick();
  await h.page.evaluate(() => showDetail("task", "delivery_old"));
  const detail = h.page.locator(".task-detail-dialog");
  assert.equal(await h.page.getByRole("dialog", {name: "历史任务详情", exact: true}).count(), 1);
  assert.match(await detail.locator(".task-historical-context").innerText(), /当前需求.*实现.*执行中/s);
  assert.match(await detail.locator(".task-title-row").innerText(), /当次 · 已阻塞/);
  assert.doesNotMatch(await detail.innerText(), /当前执行 · 已阻塞|下一步 · 核实旧执行|当前轮/);
  assert.equal(await detail.locator(".execution-history-entry").count(), 13);
  const report = detail.locator('details[data-key="artifact://historical"]');
  await report.locator(":scope > summary").click();
  await report.evaluate(node => {window.keptHistoricalReport = node;});
  await detail.locator(".execution-history").evaluate(node => {window.keptHistoricalList = node;});
  current.role_queue = [];
  await h.tick();
  assert.match(await detail.locator(".task-historical-context").innerText(), /当前需求.*等待工程处理/s);
  request.stage = "DONE";
  await h.tick();
  assert.match(await detail.locator(".task-historical-context").innerText(), /当前需求.*已完成/s);
  assert.equal(await report.evaluate(node => node === window.keptHistoricalReport && node.open), true);
  assert.equal(await detail.locator(".execution-history").evaluate(node => node === window.keptHistoricalList), true);
  await report.getByText("文档来源与校验摘要", {exact: true}).click();
  assert.match(await report.innerText(), /artifact:\/\/historical/);
  assert.match(await report.innerText(), new RegExp("b".repeat(64)));
  const originalFacts = JSON.stringify(old);
  // Ensure the current parent is visible at narrow widths without creating an extra scroll surface.
  for (const width of [1440, 1024, 390]) {
    await h.page.setViewportSize({width, height: 1000});
    const box = await detail.evaluate(node => ({client: node.clientWidth, scroll: node.scrollWidth}));
    assert.ok(box.scroll <= box.client + 1, `historical dialog has no horizontal overflow at ${width}px`);
    await detail.locator(".task-historical-context").scrollIntoViewIfNeeded();
    assert.equal(await detail.getByRole("button", {name: "查看当前需求", exact: true}).isVisible(), true);
  }
  await detail.getByRole("button", {name: "查看当前需求", exact: true}).click();
  assert.equal(await h.page.evaluate(() => selected.id), request.id);
  assert.match(await h.page.locator("#detail .request-heading-status, #detail .request-node-badge").first().innerText(), /已完成/);
  assert.equal(JSON.stringify(old), originalFacts);
  assert.deepEqual(posts, [], "rendering and parent navigation are read-only");
});
