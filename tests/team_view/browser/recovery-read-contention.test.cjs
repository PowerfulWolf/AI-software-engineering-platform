// Real layout, reading and control checks with isolated API fixtures; never production writes.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");

test("accepted recovery stays readable during Team busy and unavailable reads without reviving approval", async t => {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {title: "K1 自动知识采集", stage: "BLOCKED", failed_stages: ["DELIVERING"],
    blocker: "Coder 第 8 次执行失败：原始诊断与现场保留。",
    scopes: [{root: "/fixture", selected_paths: ["."], delivery_id: "delivery_stopped"}],
    execution: {state: "STOPPED", responsibility: "engineering", reason: "旧执行已停止，历史与现场保留。",
      next_action: "工程核对原执行。"},
    documents: [{name: "已保存的开发计划", source_uri: "artifact://saved-plan", sha256: "f".repeat(64),
      content: "可以持续阅读的开发计划\n" + "已保存的验收步骤和证据\n".repeat(30)}]});
  h.team.tasks = [{id: "delivery_stopped", task_id: "task_stopped", request_id: request.id,
    project_id: request.project_id, title: request.title, status: "BLOCKED", terminal: true,
    scope: request.scopes[0], last_activity: "2026-10-05T00:00:00Z", blocker: request.blocker,
    assignments: [], documents: [], timeline: [], runs: [], role_queue: []}];
  const source = operation("SUCCEEDED", {operation_id: "recovery_prepared", team_id: h.team.team_id,
    updated_at: "2026-10-05T01:00:00Z",
    intent: {action: "CONTINUE_DELIVERY", project_id: request.project_id, delivery_id: request.id,
      expected_checkpoint_sha256: request.checkpoint_sha256},
    result: {delivery_id: request.id, checkpoint_sha256: request.checkpoint_sha256,
      approval: {kind: "coder_recovery", plan_sha256: "e".repeat(64), title: "确认保留进度的继续方案",
        facts: ["保留原需求和开发进度，按精确方案继续独立验收。"]}}});
  h.state.operations = [source];
  let writes = 0;
  h.page.on("request", req => {if (req.method() !== "GET") writes++;});
  await h.tick();
  await h.requests();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  await detail.getByRole("button", {name: "批准并继续", exact: true}).evaluate(node => {window.oldRecoveryApproval = node;});
  const document = detail.locator(".artifact-document");
  await document.locator(":scope > summary").click();
  await document.evaluate(node => {window.savedRecoveryDocument = node;});
  const active = operation("RUNNING", {operation_id: "recovery_accepted", team_id: h.team.team_id,
    requested_at: "2026-10-05T02:00:00Z", updated_at: "2026-10-05T02:00:00Z",
    intent: {...source.intent, approved_plan_sha256: source.result.approval.plan_sha256}});
  h.state.operations.push(active);
  const sealed = JSON.stringify([h.team, h.state.operations]);
  let failureCode = "TEAM_READ_IN_PROGRESS";
  await h.page.route("http://ui.test/api/v1/team?**", route => route.fulfill({status: 503,
    json: {error: {code: failureCode}}}));
  for (const [code, title] of [["TEAM_READ_IN_PROGRESS", "团队数据正在读取"], ["TEAM_UNAVAILABLE", "团队数据读取失败"]]) {
    failureCode = code;
    await h.tick();
    if (await h.page.locator("#notification").isVisible()) await h.close();
    const overview = detail.locator(".request-detail-overview");
    assert.equal(await detail.locator(".request-title-row > .request-node-badge").innerText(), "平台正在处理恢复");
    assert.match(await overview.innerText(), /处理记录尚未结束.*尚未取得新的可核验角色执行记录/s);
    assert.match(await overview.innerText(), new RegExp(title));
    assert.match(await overview.innerText(), /新操作暂不可提交.*页面会自动重试/s);
    assert.doesNotMatch(await overview.innerText(), /当前操作已暂停|Coder.*正在执行|旧执行已停止|交付阶段 · 已阻塞/);
    assert.equal(await detail.locator(".request-blocking-section").count(), 0);
    assert.equal(await detail.getByRole("button", {name: "批准并继续", exact: true}).count(), 0);
    assert.equal(await document.evaluate(node => node === window.savedRecoveryDocument && node.open), true);
    const history = detail.locator('.request-history-fold[data-key^="operation-history:"]');
    if (!await history.evaluate(node => node.open)) await history.locator(":scope > summary").click();
    const current = history.locator(".execution-history-entry").filter({hasText: "recovery_accepted"});
    assert.equal(await current.locator("strong").first().innerText(), "当前阶段 · 恢复准备 · 平台正在处理恢复");
    for (const width of [1440, 1024, 390]) {
      await h.page.setViewportSize({width, height: 900});
      await overview.scrollIntoViewIfNeeded();
      assert.equal(await detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
      assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      if (process.env.ASE_UI_SCREENSHOT_DIR) await h.page.screenshot({
        path: process.env.ASE_UI_SCREENSHOT_DIR + `/recovery-${code.toLowerCase()}-${width}.png`});
    }
  }
  await h.page.evaluate(async () => {window.oldRecoveryApproval.click(); await new Promise(resolve => setTimeout(resolve, 0));});
  assert.equal(writes, 0, "a retained pre-approval callback cannot submit during current recovery or failed reads");
  await h.page.unroute("http://ui.test/api/v1/team?**");
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.match(await detail.locator(".request-detail-overview").innerText(), /平台正在处理恢复/);
  assert.doesNotMatch(await detail.locator(".request-detail-overview").innerText(), /团队数据正在读取|团队数据读取失败|新操作暂不可提交/);
  assert.equal(await document.evaluate(node => node === window.savedRecoveryDocument && node.open), true);
  assert.equal(writes, 0);
  assert.equal(JSON.stringify([h.team, h.state.operations]), sealed, "reading cannot mutate saved facts");
});
