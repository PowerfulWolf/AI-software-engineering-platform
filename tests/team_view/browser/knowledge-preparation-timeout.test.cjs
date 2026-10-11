const {test} = require("node:test");
const assert = require("node:assert/strict");
const {ui} = require("./fixture.cjs");

test("a pre-code knowledge timeout shows an available preparation step before any approval", async t => {
  const h = await ui(t);
  const reason = "TRANSIENT_INFRA: coder knowledge preparation reached local time limit";
  const execution = {state: "STOPPED", responsibility: "engineering", reason,
    next_action: "由工程团队核对停止原因和安全恢复路径; 当前无需产品操作。", action_required: false};
  const request = h.team.requests[0];
  Object.assign(request, {stage: "BLOCKED", failed_stages: ["DELIVERING"], blocker: reason, execution,
    scopes: [{root: "/fixture", selected_paths: ["src/**"], delivery_id: "native_current"}]});
  h.team.tasks = [{id: "native_current", task_id: "task_current", request_id: request.id,
    project_id: request.project_id, title: request.title, status: "BLOCKED", terminal: true,
    blocker: reason, execution, last_activity: "2026-10-10T11:31:30Z", scope: request.scopes[0],
    role_queue: [], assignments: [], documents: [], timeline: [], runs: []}];
  let writes = 0;
  h.page.on("request", r => {if (r.method() !== "GET") writes++;});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const section = h.page.locator("#detail .request-blocking-section");
  assert.match(await section.innerText(), /本轮尚未开始.*代码执行或验证/);
  assert.match(await section.innerText(), /点击本页“继续交付”.*准备.*恢复方案.*准备好后.*批准继续/s);
  assert.doesNotMatch(await section.innerText(), /请检查并批准精确恢复计划|核对停止原因|当前无需产品操作/);
  const continueButton = h.page.getByRole("button", {name: "继续交付", exact: true});
  assert.equal(await continueButton.isEnabled(), true);
  assert.equal(await h.page.getByRole("button", {name: "批准并继续", exact: true}).count(), 0);
  for (const width of [1440, 390]) {
    await h.page.setViewportSize({width, height: 900});
    await h.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    assert.equal(await section.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
  }
  await h.page.route("http://ui.test/api/v1/team?**", route => route.fulfill({status: 503,
    json: {error: {code: "TEAM_READ_IN_PROGRESS", message: "secret provider message"}}}));
  await h.tick();
  assert.match(await section.innerText(), /读取/);
  assert.doesNotMatch(await section.innerText(), /点击本页“继续交付”|secret provider message/);
  assert.equal(await continueButton.count() === 0 || await continueButton.isDisabled(), true);
  await h.page.unroute("http://ui.test/api/v1/team?**");
  await h.tick();
  assert.equal(await continueButton.isEnabled(), true);
  assert.equal(writes, 0);
});
