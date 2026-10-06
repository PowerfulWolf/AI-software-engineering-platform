const {test} = require("node:test");
const assert = require("node:assert/strict");
const {ui} = require("./fixture.cjs");

const qaEntry = {
  id: "qa_entry", task_id: "task_reading", kind: "artifact",
  summary: "QA 报告 · FAIL", occurred_at: "2026-10-06T01:00:00Z",
  source_uri: "artifact://qa", details: {kind: "qa-report", status: "FAIL",
    summary: "缺少边界测试，需 Coder 修改。", artifact_sha256: "a".repeat(64),
    findings: [{message: "Selected QA evidence", recommendation: "补充空输入回归测试。"}],
  },
};
const taskFixture = () => ({
  id: "task_reading", task_id: "task_reading", project_id: "project_fixture",
  request_id: "request_fixture", title: "修复需求的完整执行过程", status: "IMPLEMENTING",
  terminal: false, last_activity: "2026-10-06T01:01:00Z",
  scope: {root: "/fixture", selected_paths: ["."]}, assignments: [],
  execution: {state: "WAITING", responsibility: "engineering", reason: "验证环境未就绪。",
    next_action: "请工程负责人处理环境后重新调查。", action_required: false},
  role_queue: [], timeline: [], execution_history: [qaEntry],
  runs: [{run_id: "run_reading", role: "qa", provider: "codex", model: "fixture",
    route_index: 1, outcome: "SUCCEEDED", duration_ms: 1234, completed_at: "2026-10-06T01:00:00Z",
    source_uri: "run://reading"}],
  documents: [{name: "完整报告", source_uri: "artifact://reading", sha256: "b".repeat(64),
    content: "完整报告开始\n" + "Long evidence and command\n".repeat(80) + "全文末尾"}],
});

async function openTask(t) {
  const h = await ui(t);
  const task = taskFixture();
  h.team.tasks.push(task);
  await h.tick();
  await h.page.evaluate(() => showDetail("task", "task_reading"));
  return {...h, task, detail: h.page.locator(".task-detail-dialog")};
}

test("heartbeats and appended history preserve QA text selection, rows, reports and model records", async t => {
  const h = await openTask(t);
  const history = h.detail.locator(".execution-history");
  const row = history.locator(".execution-history-entry").first();
  await row.locator(":scope > details > summary").first().click();
  const report = h.detail.locator('details[data-key="artifact://reading"]');
  await report.locator(":scope > summary").click();
  const calls = h.detail.locator(".task-reading-fold").filter({has: h.page.locator("summary", {hasText: "已完成的模型调用"})});
  await calls.locator(":scope > summary").click();
  await row.evaluate(node => {window.keptRow = node;});
  await report.evaluate(node => {window.keptReport = node;});
  await h.detail.locator(".task-model-call-card").evaluate(node => {window.keptRun = node;});
  await row.locator(".execution-findings p").first().evaluate(node => {
    window.keptText = node.firstChild;
    const range = document.createRange();
    range.selectNodeContents(node);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    const dialog = node.closest(".task-detail-dialog");
    dialog.scrollTop = 240;
    window.keptScroll = dialog.scrollTop;
  });
  h.task.last_activity = "2026-10-06T01:02:00Z";
  await h.tick();
  h.task.execution_history.push({...qaEntry, id: "next_entry", summary: "Coder 接收反馈", kind: "state_event", details: {}});
  await h.tick();
  assert.equal(await row.evaluate(node => node === window.keptRow), true);
  assert.equal(await report.evaluate(node => node === window.keptReport && node.open), true);
  assert.equal(await h.detail.locator(".task-model-call-card").evaluate(node => node === window.keptRun), true);
  assert.equal(await h.page.evaluate(() => keptText.isConnected && getSelection().toString()), "Selected QA evidence");
  assert.equal(await h.detail.evaluate(node => node.scrollTop === window.keptScroll), true);
  assert.equal(await history.locator(".execution-history-entry").count(), 2);
  assert.equal(await row.locator(":scope > details").first().evaluate(node => node.open), true);
});

test("reading pause freezes only the Task view while fresh facts arrive and resume updates it", async t => {
  const h = await openTask(t);
  await h.detail.getByRole("button", {name: "暂停详情更新", exact: true}).click();
  h.task.title = "更新后的任务标题";
  h.task.status = "QA";
  await h.tick();
  assert.equal(await h.page.evaluate(() => snapshot.tasks[0].status), "QA");
  assert.equal(await h.detail.locator(".task-detail-title").innerText(), "修复需求的完整执行过程");
  assert.match(await h.detail.locator(".task-reading-status").innerText(), /有新进展/);
  assert.equal(await h.detail.getByRole("button", {name: "更新并恢复实时", exact: true}).getAttribute("aria-pressed"), "true");
  // An unrelated command completion can request a nonincremental detail render.
  // It must not overwrite a paused reading surface or claim that fresh facts are displayed.
  await h.detail.locator(".task-detail-title").evaluate(node => {window.pausedTitle = node;});
  await h.page.evaluate(() => renderDetail());
  assert.equal(await h.detail.locator(".task-detail-title").evaluate(node => node === window.pausedTitle), true);
  assert.equal(await h.detail.locator(".task-detail-title").innerText(), "修复需求的完整执行过程");
  assert.match(await h.detail.locator(".task-reading-status").innerText(), /有新进展/);
  await h.detail.getByRole("button", {name: "更新并恢复实时", exact: true}).click();
  assert.equal(await h.detail.locator(".task-detail-title").innerText(), "更新后的任务标题");
  assert.match(await h.detail.locator(".task-reading-status").innerText(), /实时更新/);
  await h.detail.getByRole("button", {name: "暂停详情更新", exact: true}).click();
  h.team.tasks = [];
  await h.tick();
  assert.equal(await h.page.locator(".task-detail-dialog").count(), 0, "a missing Task cannot keep a stale paused dialog");
  assert.match(await h.page.locator("#detail").innerText(), /找不到/);
});

test("reading pause cannot cross Team, page, Project or selected entity boundaries", async t => {
  const h = await openTask(t);
  for (const boundary of ["page", "project", "team"]) {
    await h.detail.getByRole("button", {name: "暂停详情更新", exact: true}).click();
    await h.page.evaluate(boundary => {
      taskById("task_reading").title = "边界更新 · " + boundary;
      if (boundary === "page") page = "requests";
      if (boundary === "project") snapshot.selected_project_id = "project_other";
      if (boundary === "team") snapshot.team_id = "team_other";
      renderDetail({incremental: true});
    }, boundary);
    assert.equal(await h.page.evaluate(() => pausedTaskDetailKey), null);
    assert.equal(await h.detail.locator(".task-detail-title").innerText(), "边界更新 · " + boundary);
    assert.equal(await h.detail.getByRole("button", {name: "暂停详情更新", exact: true}).getAttribute("aria-pressed"), "false");
  }
  // Return to the fixture scope and navigate from a paused Task to a live Requirement.
  await h.page.evaluate(() => {
    page = "team";
    snapshot.team_id = "team_fixture";
    snapshot.selected_project_id = "project_fixture";
    renderDetail({incremental: true});
  });
  await h.detail.getByRole("button", {name: "暂停详情更新", exact: true}).click();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  assert.equal(await h.page.evaluate(() => pausedTaskDetailKey), null);
  assert.equal(await h.page.locator(".task-reading-toolbar").count(), 0);
  h.team.requests[0].title = "需求仍然实时更新";
  await h.tick();
  assert.match(await h.page.locator("#detail").innerText(), /需求仍然实时更新/);
});

test("Task hierarchy and long reports fit narrow screens with one scrolling reading surface", async t => {
  const h = await openTask(t);
  h.task.title += "超长连续标题".repeat(20);
  await h.tick();
  assert.match(await h.detail.locator(".task-detail-overview").innerText(), /验证环境未就绪/);
  assert.match(await h.detail.locator(".task-detail-overview").innerText(), /重新调查/);
  assert.match(await h.detail.locator(".task-feedback-card").innerText(), /补充空输入/);
  assert.equal(await h.detail.locator(".task-activity-block").evaluate(node => getComputedStyle(node).display), "none");
  assert.equal(await h.detail.locator('[data-key="engineering:task_reading"]').evaluate(node => node.open), false);
  const report = h.detail.locator('details[data-key="artifact://reading"]');
  await report.locator(":scope > summary").click();
  assert.match(await report.innerText(), /全文末尾/);
  assert.doesNotMatch(await report.innerText(), /SHA-256/);
  for (const width of [1440, 1024, 390]) {
    await h.page.setViewportSize({width, height: 800});
    await h.detail.evaluate(node => {node.scrollTop = 0;});
    assert.equal(await h.page.locator("#detail").evaluate(node => getComputedStyle(node).position), "fixed");
    assert.equal(await h.detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    for (const selector of [".execution-history", "pre"]) {
      assert.equal(await h.detail.locator(selector).evaluate(node => getComputedStyle(node).maxHeight), "none");
      assert.equal(await h.detail.locator(selector).evaluate(node => node.scrollHeight <= node.clientHeight + 1), true);
    }
    if (process.env.ASE_UI_SCREENSHOT_DIR) await h.page.screenshot({
      path: process.env.ASE_UI_SCREENSHOT_DIR + `/task-detail-reading-${width}.png`,
    });
    await h.detail.evaluate(node => {node.scrollTop = 600;});
    assert.equal(await h.detail.evaluate(node => Math.abs(node.querySelector(".task-detail-header").getBoundingClientRect().top - node.getBoundingClientRect().top) <= 2), true);
  }
});
