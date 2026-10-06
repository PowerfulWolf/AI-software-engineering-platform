const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");

test("current engineering wait precedes complete folded history and keeps its actions separate", async t => {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {title: "K1 自动知识采集首个闭环", stage: "DELIVERING",
    scopes: [{root: "/fixture/repository", selected_paths: ["src/**"], delivery_id: "native_current"}],
    dialogue: [{speaker: "user", text: "原始需求讨论内容"}],
    documents: [{name: "TechnicalDesign", source_uri: "artifact://design", sha256: "f".repeat(64), content: "当前已验证设计"}],
    execution: {state: "WAITING", responsibility: "engineering", reason_code: "ENVIRONMENT_UNAVAILABLE",
      reason: "当前受控验证环境不可用，实施前核验尚未通过。", next_action: "工程授权者重新调查前提，事实满足后继续原交付。", action_required: false}});
  const step = {work_item_id: "work_current", role: "coder", status: "WAITING_DEPENDENCY",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action,
      facts: {task_id: "task_current", work_item_id: "work_current", role: "coder",
        task_intent_sha256: "b".repeat(64), source_revision: "c".repeat(40), checkpoint_sequence: 4}}};
  const task = {id: "native_current", task_id: "task_current", project_id: request.project_id, request_id: request.id,
    title: request.title, status: "IMPLEMENTING", terminal: false, scope: request.scopes[0],
    last_activity: "2026-10-06T00:19:48Z", execution: request.execution, role_queue: [step],
    assignments: [], documents: [], timeline: [], runs: []};
  h.team.tasks = [task, {...task, id: "native_historical", task_id: null, status: "BLOCKED", terminal: true,
    historical_child: true, checkpoint_stage: "DESIGNING", execution: null, role_queue: [],
    last_activity: "2026-10-04T00:00:00Z", blocker: "Designer did not publish a verified planning handoff"}];
  h.state.operations = Array.from({length: 12}, (_, index) => operation("SUCCEEDED", {
    operation_id: `history_${index}`, updated_at: `2026-10-05T00:${String(index).padStart(2, "0")}:00Z`,
    result: {stage: "BLOCKED", next_action: `第 ${index + 1} 轮的处理建议。`},
  }));
  let writes = 0;
  h.page.on("request", req => {if (req.method() !== "GET") writes++;});
  await h.tick();
  await h.requests();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  const operations = detail.locator('.request-history-fold[data-key^="operation-history:"]');
  const discussion = detail.locator('.request-history-fold[data-key^="discussion-history:"]');
  assert.equal(await operations.evaluate(node => node.open), false);
  assert.equal(await discussion.evaluate(node => node.open), false);
  assert.equal(await detail.locator(".historical-delivery-records").evaluate(node => node.open), false);
  assert.equal(await operations.locator(".execution-history-entry").count(), 12);
  assert.match(await detail.locator(".request-blocking-section").innerText(), /当前受控验证环境不可用/);
  assert.doesNotMatch(await detail.innerText(), /Designer|当次交付已阻塞|第 12 轮的处理建议/);
  assert.equal(await detail.evaluate(node => {
    const before = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    return before(node.querySelector(".request-blocking-section"), node.querySelector(".delivery-flow")) &&
      before(node.querySelector(".delivery-flow"), node.querySelector('[data-key^="operation-history:"]'));
  }), true);
  const engineer = detail.locator('section.engineering-wait-panel[data-key="engineering:work_current"]');
  assert.equal(await engineer.evaluate(node => Boolean(node.closest(".request-blocking-section")) && !node.closest(".request-history-fold")), true);
  assert.equal(await engineer.isVisible(), true, "current engineering intervention is visible with the current blocker");
  assert.equal(await engineer.locator("details.engineering-wait-binding").evaluate(node => node.open), false,
    "opaque investigation identities do not compete with the visible action");
  assert.equal(await engineer.getByRole("button", {name: "调查工程等待", exact: true}).isVisible(), true);
  assert.equal(await detail.getByRole("button", {name: "继续交付", exact: true}).count(), 0);
  await operations.locator(":scope > summary").click();
  assert.match(await operations.innerText(), /当次下一步 · 第 12 轮的处理建议/);
  await operations.evaluate(node => {window.historyFold = node; window.firstHistoryRow = node.querySelector(".execution-history-entry");});
  request.title += " · 当前事实更新";
  await h.tick();
  assert.equal(await operations.evaluate(node => node === window.historyFold && node.open && node.querySelector(".execution-history-entry") === window.firstHistoryRow), true);
  for (const width of [1440, 1024, 390]) {
    await h.page.setViewportSize({width, height: 900});
    assert.equal(await detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true, `detail stays within ${width}px viewport`);
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
  }
  assert.equal(writes, 0, "layout rendering and disclosures never submit delivery commands");
});

test("current baseline controls never move into folded past discussion", async t => {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {stage: "DESIGNING", dialogue: [{speaker: "user", text: "此前的产品讨论"}]});
  h.state.operations = [operation("FAILED", {error_code: "SOURCE_REVISION_DRIFT",
    error_summary: "source revision changed after Requirement preparation"})];
  await h.tick();
  await h.requests();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  const current = detail.locator('details[data-key="engineering:request_fixture:baseline"]');
  assert.equal(await current.locator(":scope > summary").isVisible(), true);
  assert.equal(await current.evaluate(node => Boolean(node.closest(".request-current-actions")) && !node.closest(".request-history-fold")), true);
  await current.locator(":scope > summary").click();
  assert.equal(await current.getByRole("button", {name: "基于当前代码新建需求", exact: true}).isVisible(), true);
  assert.equal(await detail.locator('[data-key^="discussion-history:"]').evaluate(node => node.open), false);
});

test("current product reply stays visible with its draft and legacy knowledge appears only once", async t => {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {stage: "WAITING_PRODUCT_APPROVAL", dialogue: [{speaker: "product", text: "请确认产品范围"}]});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  assert.equal(await detail.getByRole("button", {name: "批准 ProductSpec 并开始交付", exact: true}).isVisible(), true);
  const reply = detail.getByRole("textbox", {name: "继续讨论并修订", exact: true});
  await reply.fill("仍在编辑的产品补充");
  request.title = "新的只读标题";
  await h.tick();
  assert.equal(await reply.inputValue(), "仍在编辑的产品补充");
  assert.equal(await reply.evaluate(node => !node.closest(".request-history-fold")), true);
  Object.assign(request, {stage: "WAITING_HUMAN", checkpoint_sha256: "e".repeat(64),
    knowledge_gap: {is_current: true, gap: {gap_id: "gap_current"}, resolution: null}});
  await h.tick();
  assert.equal(await detail.locator(".knowledge-gap-section").count(), 1);
  assert.equal(await detail.getByRole("button", {name: "查看待确认的知识", exact: true}).isVisible(), true);
  for (const responsibility of ["team", "engineering"]) {
    request.execution = {state: "WAITING", responsibility, reason: "当前角色需要知识确认。",
      next_action: "处理当前知识事项后继续。", action_required: false};
    await h.tick();
    assert.equal(await detail.locator(".knowledge-gap-section").count(), 1);
    assert.equal(await detail.locator(".knowledge-gap-section").evaluate(node => node.closest(".request-chapter").id),
      "request-chapter-current", "a current knowledge decision cannot hide in reference even when assigned to the team or engineering");
    assert.equal(await detail.getByRole("button", {name: "查看待确认的知识", exact: true}).isVisible(), true);
  }
});

test("four Requirement chapters make documents and complete history distinct and preserve reading during polling", async t => {
  const h = await ui(t);
  const request = h.team.requests[0];
  Object.assign(request, {title: "K1 自动知识采集", stage: "DESIGNING",
    dialogue: [{speaker: "user", text: "已保存的产品讨论"}],
    documents: ["ProductSpec", "TechnicalDesign", "ExecutionPlan", "产品规格批准记录", "需求准备上下文"].map((name, index) => ({
      name, source_uri: "artifact://chapter/" + index, sha256: String(index + 1).repeat(64),
      content: "可以持续阅读的文档正文\n" + "测试步骤与验收证据\n".repeat(40) + "完整正文末尾",
    }))});
  h.state.operations = [operation("SUCCEEDED", {result: {stage: "DESIGNING"}})];
  let writes = 0;
  h.page.on("request", req => {if (req.method() !== "GET") writes++;});
  await h.tick();
  await h.requests();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const detail = h.page.locator("#detail");
  const chapters = detail.locator(":scope > .request-chapter");
  assert.deepEqual(await chapters.locator(":scope > .request-chapter-heading > h2").allTextContents(),
    ["当前进展", "产物与交付", "完整交付记录", "工程参考"]);
  assert.equal(await detail.locator("h2").count(), 4, "documents and subsection titles cannot look like additional chapters");
  const outputs = detail.locator("#request-chapter-outputs");
  assert.equal(await outputs.locator(".artifact-document").count(), 5);
  assert.equal(await detail.locator("#request-chapter-history > .request-history-fold").count(), 2);
  assert.equal(await detail.locator("#request-chapter-history .execution-history-entry").count(), 1);
  assert.equal(await detail.locator("#request-chapter-reference .request-reference-section").count(), 1);
  const summaries = await outputs.locator(".artifact-document > summary").evaluateAll(nodes => nodes.map(node => {
    const style = getComputedStyle(node);
    return [style.fontSize, style.fontWeight, style.padding, style.backgroundColor];
  }));
  assert.ok(summaries.every(style => JSON.stringify(style) === JSON.stringify(summaries[0])), "every stage document is a peer with the same style");
  const historySummaries = await detail.locator("#request-chapter-history > .request-history-fold > summary").evaluateAll(nodes => nodes.map(node => {
    const style = getComputedStyle(node);
    return [style.fontSize, style.fontWeight, getComputedStyle(node.parentElement).borderTopWidth];
  }));
  assert.ok(historySummaries.every(style => JSON.stringify(style) === JSON.stringify(historySummaries[0])), "every historical record type is a peer card");
  const document = outputs.locator(".artifact-document").first();
  await document.locator(":scope > summary").click();
  assert.match(await document.innerText(), /完整正文末尾/);
  await document.locator("pre").evaluate(node => {
    window.chapterDocument = node;
    const range = document.createRange();
    range.setStart(node.firstChild, 0);
    range.setEnd(node.firstChild, 11);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    window.chapterSelection = getSelection().toString();
  });
  request.title = "K1 自动知识采集 · 当前事实更新";
  await h.tick();
  assert.equal(await document.locator("pre").evaluate(node => node === window.chapterDocument), true);
  assert.equal(await h.page.evaluate(() => getSelection().toString() === window.chapterSelection), true);
  assert.equal(await document.evaluate(node => node.open), true);
  await document.locator(":scope > summary").click();
  for (const width of [1440, 1024, 390]) {
    await h.page.setViewportSize({width, height: 900});
    await detail.getByRole("button", {name: "产物与交付", exact: true}).click();
    assert.equal(await outputs.locator(".request-chapter-heading").isVisible(), true);
    assert.equal(await outputs.evaluate(node => {
      const nav = document.querySelector(".request-chapter-nav").getBoundingClientRect();
      const heading = node.querySelector(".request-chapter-heading").getBoundingClientRect();
      return heading.top >= nav.bottom - 1 && heading.top < innerHeight;
    }), true, "chapter navigation cannot hide the target heading behind its sticky bar");
    assert.equal(await chapters.evaluateAll(nodes => nodes.every(node => {
      const style = getComputedStyle(node);
      return style.borderTopStyle !== "none" && parseFloat(style.borderTopWidth) >= 1 && parseFloat(style.paddingTop) >= 12;
    })), true, "each chapter has a visible card boundary and consistent inner spacing");
    assert.equal(await detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    if (process.env.ASE_UI_SCREENSHOT_DIR) await h.page.screenshot({
      path: process.env.ASE_UI_SCREENSHOT_DIR + `/requirement-chapters-${width}.png`,
    });
  }
  assert.equal(writes, 0, "chapter navigation and disclosure are read-side only");
});
