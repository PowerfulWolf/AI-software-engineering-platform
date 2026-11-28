const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");

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
