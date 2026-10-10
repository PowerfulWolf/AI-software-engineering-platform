const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ui, operation } = require("./fixture.cjs");

async function runningRequirement(t) {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {stage: "DELIVERING", title: "保持开发中的原需求",
    scopes: [{root: "/fixture/repository", selected_paths: ["src/**"], delivery_id: "native_current"}],
    execution: {state: "UNKNOWN", responsibility: "team", reason: "尚无执行器心跳。",
      next_action: "等待本轮已领取的开发执行。", action_required: false},
    documents: [{name: "已保存设计", source_uri: "artifact://freshness-saved", sha256: "b".repeat(64),
      content: "Preserved body while Team reading fails\n" + "完整证据和验收记录\n".repeat(80)}]});
  const task = {id: "native_current", task_id: "task_current", project_id: request.project_id,
    request_id: request.id, title: "正在实施的仓库任务", status: "IMPLEMENTING", terminal: false,
    last_activity: "2026-10-10T00:00:00Z", scope: request.scopes[0],
    execution: {state: "RUNNING", responsibility: "team", reason: "当前角色正在执行。",
      next_action: "等待本轮执行。", action_required: false},
    role_queue: [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID", attempt: 1,
      heartbeat_at: "2026-10-10T00:00:00Z"}],
    assignments: [], documents: request.documents, timeline: [], runs: []};
  h.team.tasks = [task];
  let writes = 0;
  h.page.on("request", request => {if (request.method() !== "GET") writes++;});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  return {...h, request, task, writes: () => writes};
}

async function failTeamRead(h, code = "TEAM_UNAVAILABLE") {
  await h.page.route("http://ui.test/api/v1/team?**", route => route.fulfill({status: 503,
    json: {error: {code, message: "private provider secret must never be rendered"}}}));
  await h.tick();
}
const settleLayout = page => page.evaluate(() => new Promise(resolve =>
  requestAnimationFrame(() => requestAnimationFrame(resolve))));

test("a retained running Requirement labels old execution beside its title without changing its node or reading", async t => {
  const h = await runningRequirement(t);
  const detail = h.page.locator("#detail");
  const title = detail.locator(".request-title-row");
  assert.match(await title.innerText(), /实现 · 执行中/);
  const before = await h.page.evaluate(() => JSON.stringify([snapshot.requests, snapshot.tasks]));
  const savedTime = await h.page.evaluate(() => time(snapshot.as_of));
  const document = detail.locator('details[data-key="artifact://freshness-saved"]');
  await document.locator(":scope > summary").click();
  await settleLayout(h.page);
  await document.evaluate(node => {window.keptFreshnessDocument = node;});
  await detail.locator(".request-detail-overview").evaluate(node => {window.keptFreshnessOverview = node;});
  await document.locator("pre").evaluate(node => {
    window.keptFreshnessBody = node;
    const range = document.createRange();
    range.setStart(node.firstChild, 0);
    range.setEnd(node.firstChild, 14);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    window.keptFreshnessSelection = getSelection().toString();
    const detail = node.closest("#detail");
    detail.scrollTop = 600;
  });
  await settleLayout(h.page);
  await document.locator("pre").evaluate(node => {
    window.keptFreshnessBodyTop = node.getBoundingClientRect().top - node.closest("#detail").getBoundingClientRect().top;
  });
  await failTeamRead(h);
  await settleLayout(h.page);
  const notice = detail.locator(".request-detail-masthead .detail-read-freshness");
  assert.equal(await notice.isVisible(), true);
  assert.match(await notice.innerText(), /当前展示上次读取结果/);
  assert.ok((await notice.innerText()).includes(savedTime));
  assert.match(await notice.innerText(), /重新读取.*暂无法确认最新执行状态/);
  assert.doesNotMatch(await notice.innerText(), /交付已阻塞|后台.*停止|private provider secret/);
  assert.match(await title.innerText(), /实现 · 执行中/);
  assert.equal(await h.page.evaluate(() => JSON.stringify([snapshot.requests, snapshot.tasks])), before);
  assert.equal(await document.evaluate(node => node === keptFreshnessDocument && node.open), true);
  assert.equal(await document.locator("pre").evaluate(node => node === keptFreshnessBody), true);
  assert.equal(await detail.locator(".request-detail-overview").evaluate(node => node === keptFreshnessOverview), true);
  assert.equal(await h.page.evaluate(() => getSelection().toString() === keptFreshnessSelection), true);
  const reading = await document.locator("pre").evaluate(node => ({top: node.getBoundingClientRect().top - node.closest("#detail").getBoundingClientRect().top,
    oldTop: keptFreshnessBodyTop, scroll: node.closest("#detail").scrollTop}));
  assert.ok(Math.abs(reading.top - reading.oldTop) <= 8, JSON.stringify(reading));
  assert.equal(await h.page.evaluate(() => canControlCurrentTeam()), false);
  for (const width of [1440, 390]) {
    await h.page.setViewportSize({width, height: 844});
    await detail.evaluate(node => {node.scrollTop = 0;});
    await settleLayout(h.page);
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    assert.equal(await notice.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    if (process.env.ASE_UI_SCREENSHOT_DIR) await h.page.screenshot({
      path: process.env.ASE_UI_SCREENSHOT_DIR + `/detail-read-freshness-running-${width}.png`,
    });
  }
  await h.page.unroute("http://ui.test/api/v1/team?**");
  await h.tick();
  assert.equal(await detail.locator(".detail-read-freshness-slot").isVisible(), false);
  assert.equal(await document.evaluate(node => node === keptFreshnessDocument && node.open), true);
  assert.equal(await h.page.evaluate(() => canControlCurrentTeam()), true);
  assert.equal(h.writes(), 0);
});

test("a retained blocked approval stays blocked and unusable until matching current facts return", async t => {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {stage: "BLOCKED", failed_stages: ["DELIVERING"],
    blocker: "原开发执行已停止，完整进度保留。",
    execution: {state: "STOPPED", responsibility: "engineering", reason: "旧执行已停止，历史与现场保留。",
      next_action: "工程核对原执行。", action_required: false}});
  h.state.operations = [operation("SUCCEEDED", {operation_id: "prepared_recovery", team_id: h.team.team_id,
    intent: {action: "CONTINUE_DELIVERY", project_id: request.project_id, delivery_id: request.id,
      expected_checkpoint_sha256: request.checkpoint_sha256},
    result: {delivery_id: request.id, checkpoint_sha256: request.checkpoint_sha256,
      approval: {kind: "coder_recovery", plan_sha256: "e".repeat(64), title: "确认保留进度的继续方案",
        facts: ["保留原需求和开发进度。"]}}})];
  let writes = 0;
  h.page.on("request", request => {if (request.method() !== "GET") writes++;});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const badge = h.page.locator("#detail .request-title-row .request-node-badge");
  const originalBadge = await badge.innerText();
  assert.match(originalBadge, /待工程确认/);
  const approve = h.page.getByRole("button", {name: "批准并继续", exact: true});
  assert.equal(await approve.isEnabled(), true);
  await approve.evaluate(node => {window.oldFreshnessApproval = node;});
  await failTeamRead(h, "TEAM_READ_IN_PROGRESS");
  assert.equal(await h.page.locator(".detail-read-freshness").isVisible(), true);
  assert.match(await badge.getAttribute("class"), /blocked/);
  assert.match(await badge.innerText(), /已阻塞/);
  assert.equal(await h.page.evaluate(() => snapshot.requests[0].stage), "BLOCKED");
  assert.equal(await approve.count() === 0 || await approve.isDisabled(), true);
  await h.page.evaluate(() => oldFreshnessApproval.click());
  assert.equal(writes, 0);
  await h.page.unroute("http://ui.test/api/v1/team?**");
  await h.tick();
  assert.equal(await h.page.locator(".detail-read-freshness-slot").isVisible(), false);
  assert.equal(await approve.isEnabled(), true, "only matching current approval facts are restored");
  await failTeamRead(h);
  request.checkpoint_sha256 = "f".repeat(64);
  await h.page.unroute("http://ui.test/api/v1/team?**");
  await h.tick();
  assert.equal(await h.page.locator(".detail-read-freshness-slot").isVisible(), false);
  assert.equal(await approve.count(), 0, "a stale approval cannot revive on read recovery");
  await h.page.evaluate(() => oldFreshnessApproval.click());
  assert.equal(writes, 0);
});

test("a paused Task updates only the nearby read notice using the displayed snapshot time", async t => {
  const h = await runningRequirement(t);
  const originalTime = await h.page.evaluate(() => time(snapshot.as_of));
  await h.page.evaluate(() => showDetail("task", "native_current"));
  const detail = h.page.locator(".task-detail-dialog");
  const title = detail.locator(".task-detail-title");
  await title.evaluate(node => {window.keptPausedFreshnessTitle = node;});
  await detail.getByRole("button", {name: "暂停详情更新", exact: true}).click();
  h.team.as_of = "2026-10-10T02:00:00Z";
  h.task.title = "暂停之后的新任务标题";
  await h.tick();
  assert.equal(await title.innerText(), "正在实施的仓库任务");
  await failTeamRead(h);
  const notice = detail.locator(".task-detail-header .detail-read-freshness");
  assert.equal(await notice.isVisible(), true);
  assert.ok((await notice.innerText()).includes(originalTime));
  assert.equal(await title.evaluate(node => node === keptPausedFreshnessTitle), true);
  assert.equal(await title.innerText(), "正在实施的仓库任务");
  assert.equal(await h.page.evaluate(() => pausedTaskDetailKey !== null), true);
  await h.page.setViewportSize({width: 390, height: 844});
  await settleLayout(h.page);
  assert.equal(await detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
  if (process.env.ASE_UI_SCREENSHOT_DIR) await h.page.screenshot({
    path: process.env.ASE_UI_SCREENSHOT_DIR + "/detail-read-freshness-paused-task-390.png",
  });
  assert.equal(await detail.locator(".task-detail-header").count(), 1);
  assert.equal(await detail.locator(".task-detail-header").evaluate(node => node.getBoundingClientRect().height < 260), true,
    "the nearby read notice leaves most of a narrow viewport available for content");
  await h.page.unroute("http://ui.test/api/v1/team?**");
  await h.tick();
  assert.equal(await detail.locator(".detail-read-freshness-slot").isVisible(), false);
  assert.equal(await title.innerText(), "正在实施的仓库任务");
  await detail.getByRole("button", {name: "更新并恢复实时", exact: true}).click();
  assert.equal(await title.innerText(), "暂停之后的新任务标题");
  assert.equal(h.writes(), 0);
});

test("read freshness follows Project identity and cannot reuse the previous Project source", async t => {
  const h = await runningRequirement(t);
  await failTeamRead(h);
  const oldTime = await h.page.evaluate(() => time(snapshot.as_of));
  assert.ok((await h.page.locator(".detail-read-freshness").innerText()).includes(oldTime));
  await h.page.unroute("http://ui.test/api/v1/team?**");
  h.team.selected_project_id = "project_next";
  h.team.projects.push({id: "project_next", name: "另一个项目"});
  h.team.requests = [{...h.request, id: "request_next", project_id: "project_next", title: "新项目的需求",
    stage: "READY_FOR_DISCUSSION", execution: null, scopes: [], documents: []}];
  h.team.tasks = [];
  h.team.as_of = "2026-10-10T03:00:00Z";
  await h.page.evaluate(() => refresh("project_next"));
  assert.equal(await h.page.locator(".detail-read-freshness-slot").isVisible(), false);
  await failTeamRead(h);
  const notice = h.page.locator(".detail-read-freshness");
  const nextTime = await h.page.evaluate(() => time(snapshot.as_of));
  assert.ok((await notice.innerText()).includes(nextTime));
  assert.ok(!(await notice.innerText()).includes(oldTime));
  assert.match(await h.page.locator(".request-title-row").innerText(), /新项目的需求/);
  assert.equal(h.writes(), 0);
});

test("nearby read guidance updates without losing an open Requirement draft", async t => {
  const h = await ui(t);
  Object.assign(h.team.requests[0], {stage: "WAITING_PRODUCT_APPROVAL",
    dialogue: [{speaker: "product", text: "请确认产品范围"}]});
  let writes = 0;
  h.page.on("request", request => {if (request.method() !== "GET") writes++;});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  await h.draft();
  const reply = h.page.locator('#composer input[name="name"]');
  await reply.fill("仍在编辑的产品需求草稿");
  await reply.evaluate(node => {window.keptFreshnessDraft = node;});
  await failTeamRead(h);
  assert.equal(await h.page.locator(".detail-read-freshness").isVisible(), true);
  assert.equal(await reply.evaluate(node => node === keptFreshnessDraft), true);
  assert.equal(await reply.inputValue(), "仍在编辑的产品需求草稿");
  await h.page.unroute("http://ui.test/api/v1/team?**");
  await h.tick();
  assert.equal(await h.page.locator(".detail-read-freshness-slot").isVisible(), false);
  assert.equal(await reply.evaluate(node => node === keptFreshnessDraft), true);
  assert.equal(await reply.inputValue(), "仍在编辑的产品需求草稿");
  assert.equal(writes, 0);
});
