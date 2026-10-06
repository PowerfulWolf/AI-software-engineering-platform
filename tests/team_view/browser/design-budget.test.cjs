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

test("local execution time budget shows available window and hides exhausted retry", async (t) => {
  const h = await ui(t, {operations: [operation("FAILED", {error_code: "MODEL_EXECUTION_LIMIT"})]});
  Object.assign(h.team.requests[0], {stage: "DESIGNING", stage_budget: {role: "designer",
    attempts: 0, max_attempts: 3, transient_failures: 0, max_transient_failures: 5,
    capacity_timeouts: 2, max_capacity_timeouts: 3, next_timeout_seconds: 2400}});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await detail.getByText("需求工程详情", {exact: true}).click();
  assert.match(await detail.innerText(), /本地执行触顶 2\/3，当前可用执行窗口 2400 秒/);
  h.team.requests[0].stage_budget = {...h.team.requests[0].stage_budget,
    capacity_timeouts: 3, next_timeout_seconds: null, exhausted: "capacity"};
  await h.tick();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  assert.match(await detail.innerText(), /本地执行触顶 3\/3，已达上限/);
  assert.equal(await detail.getByRole("button", {name: "重试 Design", exact: true}).count(), 0);
});

test("stage budget keeps available-window semantics during running and failed upstream operations", async (t) => {
  const h = await ui(t);
  await h.requests();
  const detail = h.page.locator("#detail");
  for (const status of ["RUNNING", "FAILED"]) {
    h.state.operations = [operation(status, {error_code: status === "FAILED" ? "MODEL_EXECUTION_LIMIT" : null})];
    for (const [stage, role] of [["PRODUCT_DISCOVERY", "product"], ["DESIGNING", "designer"], ["PLANNING", "planner"]]) {
      Object.assign(h.team.requests[0], {stage, stage_budget: {role, attempts: 1, max_attempts: 3,
        transient_failures: 0, max_transient_failures: 5, capacity_timeouts: 1,
        max_capacity_timeouts: 3, next_timeout_seconds: 1200}});
      await h.tick();
      await h.page.evaluate(() => showDetail("request", "request_fixture"));
      if (await h.page.locator("#notification").isVisible()) await h.close();
      const engineering = detail.locator('details[data-key="engineering:request_fixture"]');
      if (!await engineering.evaluate(node => node.open)) await engineering.locator(":scope > summary").click();
      const text = await detail.innerText();
      assert.match(text, new RegExp(`${role} 工作尝试 1/3.*当前可用执行窗口 1200 秒`), `${status} ${role}`);
      assert.doesNotMatch(text, /下次时限/, `${status} ${role}`);
    }
  }
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
  assert.equal(await content.locator('input[type="number"][max="100"]').count(), 17);
  await limits.first().fill("101");
  assert.equal(await limits.first().evaluate(node => node.checkValidity()), false);
});

test("Manager and execution-time fields submit the same bounded configuration", async (t) => {
  const h = await ui(t);
  await h.page.locator("#nav-settings").click();
  const form = h.page.locator("#content .settings-form");
  await form.waitFor();
  const values = {
    "retry-manager-max_attempts": 4,
    "retry-manager-max_transient_failures": 7,
    "retry-manager-max_coordination_rounds": 6,
    "execution-time-manager-initial_seconds": 900,
    "execution-time-manager-max_seconds": 3600,
    "execution-time-manager-max_capacity_timeouts": 4,
  };
  for (const [name, value] of Object.entries(values))
    await form.locator(`input[name="${name}"]`).fill(String(value));
  const submission = h.page.waitForRequest(request =>
    request.url().endsWith("/api/v1/admin/settings") && request.method() === "PUT");
  await form.getByRole("button", {name: "保存设置"}).click();
  const policy = (await submission).postDataJSON().config.execution_retry_policy;
  assert.deepEqual(policy.manager,
    {max_attempts: 4, max_transient_failures: 7, max_coordination_rounds: 6});
  assert.deepEqual(policy.execution_time.manager,
    {initial_seconds: 900, max_seconds: 3600, max_capacity_timeouts: 4});
  assert.deepEqual(policy.execution_time.product,
    {initial_seconds: 600, max_seconds: 2400, max_capacity_timeouts: 3});
});

test("Manager wait retains original stage and cannot replace exact approval", async (t) => {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {stage: "PLANNING", next_action: "Review required context",
    coordination: {draft: {action: "WAITING_HUMAN", summary: "Required context is too large"}}});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  assert.match(await detail.innerText(), /Required context is too large/);
  assert.equal(await h.page.evaluate(() => requestPresentation(snapshot.requests[0]).status), "PLANNING");
  h.state.operations.push(operation("SUCCEEDED", {result: {
    project_id: "project_fixture", delivery_id: request.id, checkpoint_sha256: request.checkpoint_sha256,
    stage: "WAITING_HUMAN", next_action: "Approve exact recovery",
    approval: {kind: "coder_recovery", plan_sha256: "b".repeat(64), title: "批准 Coder 恢复任务", facts: []},
  }}));
  await h.tick();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  await h.page.getByText("工程管理 · 需工程授权者处理", {exact: true}).click();
  assert.equal(await detail.getByRole("button", {name: "批准并继续", exact: true}).count(), 1);
  assert.equal(await detail.getByRole("button", {name: "重试 Planner", exact: true}).count(), 0);
});
