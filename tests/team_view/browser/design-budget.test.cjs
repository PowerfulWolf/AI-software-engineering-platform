const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ui, operation } = require("./fixture.cjs");

test("Product and Planner exhaustion hides futile actions; increased Planner allowance enables retry", async (t) => {
  const h = await ui(t, {operations: [operation("FAILED")]});
  await h.requests();
  await h.close();
  for (const [stage, role] of [["PRODUCT_DISCOVERY", "product"], ["PLANNING", "planner"]]) {
    Object.assign(h.team.requests[0], {stage, stage_budget: {role, attempts: 1, max_attempts: 3,
      transient_failures: 2, max_transient_failures: 2, exhausted: "transient"}});
    await h.tick();
    await h.page.evaluate(() => showDetail("request", "request_fixture"));
    const detail = h.page.locator("#detail");
    assert.match(await detail.innerText(), /临时故障 2\/2/);
    assert.equal(await detail.getByRole("button", {name: /^(继续交付|继续需求讨论|重试 Planner)$/}).count(), 0);
  }
  h.team.requests[0].stage_budget.max_transient_failures = 3;
  delete h.team.requests[0].stage_budget.exhausted;
  await h.tick();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  assert.equal(await h.page.locator("#detail").getByRole("button", {name: "重试 Planner", exact: true}).count(), 1);
});

test("real browser selects recovery over the failed retry and hides it while running", async (t) => {
  const h = await ui(t, {operations: [operation("FAILED")]});
  Object.assign(h.team.requests[0], {stage: "DESIGNING", design_recovery_available: true,
    design_budget: {design_attempts: 3, max_design_attempts: 3,
      transient_failures: 0, max_transient_failures: 5, exhausted: "design"}});
  await h.tick();
  await h.requests();
  await h.close();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  assert.equal(await detail.getByRole("button", {name: "重试 Design", exact: true}).count(), 0);
  const recovery = detail.getByRole("button", {name: "恢复设计", exact: true});
  assert.equal(await recovery.isVisible(), true);
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const body = route.request().postDataJSON();
    assert.deepEqual(body.intent, {action: "RECOVER_DESIGN", project_id: "project_fixture",
      delivery_id: "request_fixture", expected_checkpoint_sha256: "a".repeat(64)});
    return route.fulfill({status: 202, json: operation("RUNNING", {intent: body.intent})});
  });
  await recovery.click();
  await h.page.waitForFunction(() => Boolean(activeOperation("request_fixture")));
  assert.equal(await detail.getByRole("button", {name: "恢复设计", exact: true}).count(), 0);
});

test("real browser displays separate exhausted counters and budget settings inputs", async (t) => {
  const h = await ui(t);
  Object.assign(h.team.requests[0], {stage: "DESIGNING", design_recovery_available: false,
    design_budget: {design_attempts: 1, max_design_attempts: 3,
      transient_failures: 5, max_transient_failures: 5, exhausted: "transient"}});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  assert.match(await detail.innerText(), /设计尝试 1\/3；临时故障 5\/5/);
  assert.equal(await detail.getByRole("button", {name: "重试 Design", exact: true}).count(), 0);
  assert.equal(await detail.getByRole("button", {name: "继续交付", exact: true}).count(), 0);
  await h.page.locator("#nav-settings").click();
  await h.page.locator("#content .settings-form").waitFor();
  const content = h.page.locator("#content");
  const limits = content.locator('input[name^="retry-designer-"]');
  assert.equal(await limits.count(), 2);
  await limits.first().fill("8");
  await limits.last().fill("20");
  assert.deepEqual(await h.page.evaluate(() => settingsDraft.execution_retry_policy.designer),
    {max_attempts: 8, max_transient_failures: 20});
  assert.equal(await content.locator('input[type="number"][max="100"]').count(), 10);
  await limits.first().fill("101");
  assert.equal(await limits.first().evaluate(node => node.checkValidity()), false);
});
