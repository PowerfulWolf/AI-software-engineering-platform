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
  await detail.getByText("任务工程详情", {exact: true}).click();
  assert.match(await detail.innerText(), /历史执行诊断已更新/);
  assert.equal(await h.page.evaluate(() => selected.id), old.id);
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
