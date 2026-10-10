const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ui, operation } = require("./fixture.cjs");
async function assertDraft(page) {
  assert.equal(await page.evaluate(() => draftInput.isConnected && draftInput.value === "保留正在编辑的需求"), true);
}
async function assertNoOverlay(page) {
  const display = await page.locator("#notification").evaluate((node) => ({ hidden: node.hidden, display: getComputedStyle(node).display, boxes: node.getClientRects().length }));
  assert.deepEqual(display, { hidden: true, display: "none", boxes: 0 }, "closed notification must leave no painted or clickable backdrop");
}

test("notification semantic colors distinguish queued and running info from success", async (t) => {
  const h = await ui(t, { operations: [operation("QUEUED")] });
  await h.requests();
  const icon = h.page.locator("#notification .settings-result-icon");
  for (const status of ["QUEUED", "RUNNING"]) {
    h.state.operations[0].status = status;
    await h.tick();
    assert.equal(await icon.innerText(), "i");
    assert.equal(await icon.getAttribute("class"), "settings-result-icon info");
    assert.deepEqual(await icon.evaluate(node => ({
      color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor,
    })), {color: "rgb(36, 89, 204)", background: "rgb(233, 239, 253)"});
  }
  await h.close();
  await h.tick();
  await assertNoOverlay(h.page);
});

test("notification semantic colors preserve success warning error and ordinary info", async (t) => {
  const h = await ui(t);
  const cases = [
    ["success", "✓", "rgb(20, 122, 75)", "rgb(230, 245, 237)"],
    ["warning", "i", "rgb(138, 91, 0)", "rgb(255, 245, 217)"],
    ["error", "!", "rgb(154, 72, 18)", "rgb(255, 240, 226)"],
    ["info", "i", "rgb(36, 89, 204)", "rgb(233, 239, 253)"],
  ];
  for (const [kind, symbol, color, background] of cases) {
    await h.page.evaluate(kind => {
      operationNotice = {kind, title: "语义图标fixture", message: "固定信息"};
      renderNotification();
    }, kind);
    const icon = h.page.locator("#notification .settings-result-icon");
    assert.equal(await icon.innerText(), symbol);
    assert.equal(await icon.getAttribute("class"), `settings-result-icon ${kind}`);
    assert.deepEqual(await icon.evaluate(node => ({
      color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor,
    })), {color, background});
  }
  await h.page.evaluate(() => {
    operationNotice = null;
    administrationNotice = {page, text: "普通操作提示"};
    renderNotification();
  });
  assert.equal(await h.page.locator("#notification .settings-result-icon").getAttribute("class"),
    "settings-result-icon info");
  await h.close();
  await assertNoOverlay(h.page);
});

test("project operation history archives unreachable old failures without blocking the current Requirement", async (t) => {
  const old = operation("FAILED", {operation_id: "old_project_creation", updated_at: "2026-10-04T10:51:00+08:00",
    intent: {action: "CREATE_REQUIREMENT", project_id: "project_fixture", name: "<img src=x onerror=alert(1)>"},
    error_summary: "prepared joint context exceeds budget"});
  const retired = operation("INTERRUPTED", {operation_id: "retired_request_operation", updated_at: "2026-10-04T03:00:00Z",
    intent: {action: "CONTINUE_DELIVERY", project_id: "project_fixture", delivery_id: "retired_request"},
    error_summary: "已退休需求的历史中断"});
  const foreign = operation("FAILED", {operation_id: "foreign_project_creation",
    intent: {action: "CREATE_REQUIREMENT", project_id: "other_project"}, error_summary: "外Project历史"});
  const foreignTeam = operation("FAILED", {operation_id: "foreign_team_creation", team_id: "another_team",
    intent: {action: "CREATE_REQUIREMENT", project_id: "project_fixture"}, error_summary: "外Team历史"});
  const h = await ui(t, {operations: [old, retired, foreign, foreignTeam]});
  const saved = JSON.stringify(h.state.operations);
  await h.requests();
  await assertNoOverlay(h.page);
  const history = h.page.locator(".project-operation-history");
  assert.equal(await history.getAttribute("open"), null);
  const summary = history.locator(":scope > summary");
  assert.match(await summary.innerText(), /项目操作记录.*2 条/);
  await summary.focus();
  await h.page.keyboard.press("Enter");
  assert.match(await history.innerText(), /未关联.*需求/);
  assert.match(await history.innerText(), /需求的必需上下文超过配置上限/);
  assert.match(await history.innerText(), /已退休需求的历史中断/);
  assert.doesNotMatch(await history.innerText(), /外Project历史/);
  assert.doesNotMatch(await history.innerText(), /外Team历史/);
  assert.equal(await history.locator("img").count(), 0);
  assert.match(await history.innerText(), /<img src=x onerror=alert\(1\)>/);
  const rows = await history.locator(":scope > ol > li").allTextContents();
  assert.match(rows[0], /<img src=x onerror=alert\(1\)>/);
  assert.match(rows[1], /已退休需求的历史中断/, "history orders actual instants across timezone offsets");
  await summary.evaluate(node => {window.savedProjectHistory = node.parentElement;});
  await h.tick();
  assert.equal(await h.page.evaluate(() => savedProjectHistory.isConnected && savedProjectHistory.open), true);
  const reads = h.state.reads.length;
  h.team.requests = [];
  await h.tick();
  assert.match(await h.page.locator("#content").innerText(), /还没有需求/);
  assert.equal(await h.page.evaluate(() => savedProjectHistory.isConnected && savedProjectHistory.open), true);
  assert.match(await history.innerText(), /已退休需求的历史中断/);
  assert.deepEqual(h.state.reads.slice(reads).filter(url => url.includes("operations")), ["/api/v1/operations"],
    "history reuses the normal Operations read without extra requests");
  for (const width of [1440, 390]) {
    await h.page.setViewportSize({width, height: 844});
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
      `project history has no horizontal overflow at ${width}px`);
  }
  await h.page.route("http://ui.test/api/v1/operations", route => route.fulfill({status: 503, json: {error: {code: "READ_UNAVAILABLE"}}}));
  await h.tick();
  assert.equal(await h.page.evaluate(() => savedProjectHistory.isConnected && savedProjectHistory.open), true);
  assert.match(await history.innerText(), /以下保留上次读取的记录，不能代表当前执行状态/);
  assert.equal(await history.locator(":scope > ol > li").count(), 2);
  await h.page.unroute("http://ui.test/api/v1/operations");
  await h.tick();
  assert.equal(await h.page.evaluate(() => savedProjectHistory.isConnected && savedProjectHistory.open), true);
  assert.doesNotMatch(await history.innerText(), /以下保留上次读取的记录，不能代表当前执行状态/);
  assert.equal(JSON.stringify(h.state.operations), saved);
});

test("project history keeps every record and its sealed outcome beyond eight entries", async (t) => {
  const records = Array.from({length: 12}, (_, index) => operation("SUCCEEDED", {
    operation_id: `archived_creation_${index}`, updated_at: "2026-10-04T10:51:00Z",
    intent: {action: "CREATE_REQUIREMENT", project_id: "project_fixture", name: `历史操作 ${index}`},
    result: {stage: "BLOCKED", diagnostic: `完整原因 ${index}`, next_action: `当次建议 ${index}`},
  }));
  const h = await ui(t, {operations: records});
  await h.requests();
  await assertNoOverlay(h.page);
  const history = h.page.locator(".project-operation-history");
  await history.locator(":scope > summary").click();
  assert.match(await history.innerText(), /12 条/);
  assert.equal(await history.locator(":scope > ol > li").count(), 12);
  for (let index = 0; index < records.length; index++) {
    const row = history.locator(":scope > ol > li").filter({
      has: h.page.getByText(`当次原因 · 完整原因 ${index}`, {exact: true}),
    });
    assert.equal(await row.count(), 1);
    assert.match(await row.innerText(), new RegExp(`当次建议 ${index}`));
    assert.match(await row.innerText(), /当次需求阶段 · 已阻塞/);
  }
  const ids = await history.locator(":scope > ol > li .engineering-details").allTextContents();
  assert.equal(ids.length, 12);
  assert.match(ids[2], /archived_creation_10/, "equal timestamps have stable operation identity order");
});

test("acknowledging a notification releases the real CSS backdrop and page clicks", async (t) => {
  const h = await ui(t, { operations: [operation()] });
  await h.requests();
  await h.close();
  await assertNoOverlay(h.page);
  await h.page.locator("#nav-team").click();
  assert.equal(await h.page.locator("#heading").innerText(), "团队成员");
});

test("polling updates and clears notices while a Requirement draft stays open", async (t) => {
  const h = await ui(t);
  await h.requests();
  await h.draft();
  h.state.operations = [operation()];
  await h.tick();
  assert.match(await h.page.locator("#notification").innerText(), /等待 Manager/);
  await assertDraft(h.page);
  h.state.operations = [operation("FAILED")];
  await h.tick();
  assert.match(await h.page.locator("#notification").innerText(), /模型暂不可用/);
  await assertDraft(h.page);
  await h.close();
  await h.page.locator('#composer input[name="name"]').fill("关闭后可以继续编辑");
});

test("historical preparation budget failures explain the engineering action in Chinese", async (t) => {
  const h = await ui(t, { operations: [operation("FAILED", {
    error_summary: "prepared joint context exceeds budget",
  })] });
  await h.requests();
  const text = await h.page.locator("#notification").innerText();
  assert.match(text, /需求的必需上下文超过配置上限/);
  assert.match(text, /工程负责人核验上下文预算和已选知识、规范/);
  assert.doesNotMatch(text, /prepared joint context exceeds budget/);
});

test("active notice auto-closes on success even over an open form", async (t) => {
  const h = await ui(t);
  await h.requests();
  await h.draft();
  h.state.operations = [operation()];
  await h.tick();
  assert.match(await h.page.locator("#notification").innerText(), /等待 Manager/);
  h.state.operations = [operation("SUCCEEDED")];
  await h.tick();
  await assertNoOverlay(h.page);
  await assertDraft(h.page);
});

test("notification jump initializes Settings and recovery clears stale system notice", async (t) => {
  const h = await ui(t, { ready: false });
  await h.requests();
  await h.page.getByRole("button", { name: "前往设置", exact: true }).click();
  await h.page.waitForFunction(() => document.getElementById("heading").textContent === "设置");
  assert.equal(await h.page.locator("#heading").innerText(), "设置");
  assert.ok(h.state.reads.includes("/api/v1/admin/settings"));
  assert.ok(await h.page.locator("#content form").count() > 0);
  h.state.ready = true;
  await h.tick();
  await assertNoOverlay(h.page);
});

test("background polling never rebuilds an unchanged notification or steals its keyboard focus", async (t) => {
  const h = await ui(t, { operations: [operation("FAILED")] });
  await h.requests();
  const jump = h.page.getByRole("button", { name: "打开需求工作区", exact: true });
  await jump.focus();
  await jump.evaluate((node) => { window.noticeButton = node; });
  h.state.operations.push(operation("SUCCEEDED", { operation_id: "unrelated", intent: { action: "CREATE_PROJECT" } }));
  await h.tick();
  assert.equal(await h.page.evaluate(() => noticeButton.isConnected && document.activeElement === noticeButton), true);
});

test("Escape closes only the top notice and restores focus to the untouched form", async (t) => {
  const h = await ui(t);
  await h.requests();
  await h.draft();
  h.state.operations = [operation()];
  await h.tick();
  await h.page.keyboard.press("Tab");
  assert.equal(await h.page.evaluate(() => document.getElementById("notification").contains(document.activeElement)), true);
  await h.page.keyboard.press("Escape");
  await assertNoOverlay(h.page);
  await assertDraft(h.page);
  assert.equal(await h.page.evaluate(() => document.activeElement === draftInput), true);
});

test("notification never offers a workspace jump for a missing or foreign Requirement", async (t) => {
  const h = await ui(t, { operations: [operation("FAILED", { intent: { action: "CONTINUE_DELIVERY", project_id: "another_project", delivery_id: "missing_request" } })] });
  await h.requests();
  assert.equal(await h.page.getByRole("button", { name: "打开需求工作区", exact: true }).count(), 0);
});

test("a notice preserves an open form and offers navigation only when editing has finished", async (t) => {
  const h = await ui(t);
  await h.requests();
  await h.draft();
  h.state.operations = [operation("FAILED")];
  await h.tick();
  assert.equal(await h.page.getByRole("button", { name: "打开需求工作区", exact: true }).count(), 0);
  assert.match(await h.page.locator("#notification").innerText(), /先完成或取消编辑/);
  await h.close();
  await assertDraft(h.page);
  await assertNoOverlay(h.page);
  h.page.once("dialog", dialog => dialog.accept());
  await h.page.locator("#composer").getByRole("button", { name: "取消", exact: true }).click();
  h.state.operations = [operation("FAILED", { operation_id: "next_failure", updated_at: "2026-09-21T00:02:00Z" })];
  await h.tick();
  await h.page.getByRole("button", { name: "打开需求工作区", exact: true }).click();
  assert.equal(await h.page.locator("#composer").isVisible(), false);
  await h.page.locator("#nav-team").click();
});

test("acknowledgement survives ACTIVE polling and reload but still shows a later failure", async (t) => {
  const h = await ui(t, { operations: [operation()] });
  await h.requests();
  await h.close();
  h.state.operations = [operation("RUNNING")];
  await h.tick();
  await assertNoOverlay(h.page);
  await h.page.reload();
  await h.page.waitForFunction(() => snapshot !== null && !refreshing);
  await h.requests();
  await assertNoOverlay(h.page);
  h.state.operations = [operation("FAILED")];
  await h.tick();
  assert.match(await h.page.locator("#notification").innerText(), /模型暂不可用/);
  await h.close();
  await h.tick();
  await assertNoOverlay(h.page);
});

test("a newer retry replaces an old failure and acknowledging it cannot revive the old dialog", async (t) => {
  const old = operation("FAILED");
  const retry = operation("RUNNING", { operation_id: "retry", updated_at: "2026-09-21T00:01:00Z" });
  const h = await ui(t, { operations: [old] });
  await h.requests();
  h.state.operations = [old, retry];
  await h.tick();
  assert.match(await h.page.locator("#notification").innerText(), /执行中/);
  assert.doesNotMatch(await h.page.locator("#notification").innerText(), /模型暂不可用/);
  await h.close();
  await h.tick();
  await assertNoOverlay(h.page);
});

test("a current recovery approval clears historical cross-action failure dialogs without hiding the approval or history", async (t) => {
  const old = operation("INTERRUPTED", {operation_id: "old_product_approval",
    intent: {action: "PRODUCT_APPROVAL", project_id: "project_fixture", delivery_id: "request_fixture"},
    error_summary: "历史产品批准后的交付操作中断。"});
  const h = await ui(t, {operations: [old]});
  await h.requests();
  assert.match(await h.page.locator("#notification").innerText(), /历史产品批准后的交付操作中断/);
  h.team.requests[0].stage = "BLOCKED";
  h.team.requests[0].blocker = "保留开发进度，等待当前方案确认。";
  h.state.operations.push(operation("SUCCEEDED", {operation_id: "current_recovery",
    updated_at: "2026-10-10T12:00:00Z", result: {delivery_id: "request_fixture", stage: "BLOCKED",
      checkpoint_sha256: "a".repeat(64), approval: {kind: "coder_recovery",
        title: "保留进度并继续原需求", facts: ["原开发进度保持完整，批准后继续原需求。"],
        plan_sha256: "b".repeat(64)}}}));
  const saved = JSON.stringify(h.state.operations);
  await h.tick();
  await assertNoOverlay(h.page);
  assert.match(await h.page.locator("#detail").innerText(), /保留进度并继续原需求/);
  assert.match(await h.page.locator("#detail").textContent(), /历史产品批准后的交付操作中断/,
    "sealed history remains readable after its instant notice is superseded");
  for (let tick = 0; tick < 3; tick++) { await h.tick(); await assertNoOverlay(h.page); }
  assert.equal(JSON.stringify(h.state.operations), saved);
  await h.page.locator("#nav-team").click();
  assert.equal(await h.page.locator("#heading").innerText(), "团队成员");
});

test("acknowledging the current cross-action wait never reveals an old interrupted Product approval", async (t) => {
  const old = operation("INTERRUPTED", {operation_id: "old_product_approval",
    intent: {action: "PRODUCT_APPROVAL", project_id: "project_fixture", delivery_id: "request_fixture"},
    error_summary: "历史产品批准后的交付操作中断。"});
  const current = operation("SUCCEEDED", {operation_id: "current_wait", updated_at: "2026-10-10T12:00:00Z",
    result: {delivery_id: "request_fixture", stage: "BLOCKED", diagnostic: "请查看当前工程缺项。"}});
  const h = await ui(t, {operations: [old, current]});
  await h.requests();
  assert.match(await h.page.locator("#notification").innerText(), /请查看当前工程缺项/);
  await h.close();
  for (let tick = 0; tick < 3; tick++) { await h.tick(); await assertNoOverlay(h.page); }
  await h.page.locator("#nav-team").click();
  assert.equal(await h.page.locator("#heading").innerText(), "团队成员");
});

test("a running Continue replaces an interrupted Product approval and does not revive it after dismissal", async (t) => {
  const old = operation("INTERRUPTED", {operation_id: "old_product_approval",
    intent: {action: "PRODUCT_APPROVAL", project_id: "project_fixture", delivery_id: "request_fixture"},
    error_summary: "历史产品批准后的交付操作中断。"});
  const h = await ui(t, {operations: [old]});
  await h.requests();
  h.state.operations.push(operation("RUNNING", {operation_id: "current_continue", updated_at: "2026-10-10T12:00:00Z"}));
  await h.tick();
  const notice = await h.page.locator("#notification").innerText();
  assert.match(notice, /执行中/);
  assert.doesNotMatch(notice, /历史产品批准后的交付操作中断/);
  await h.close();
  for (let tick = 0; tick < 3; tick++) { await h.tick(); await assertNoOverlay(h.page); }
});

test("a polled failure consumes an older Project success notice", async (t) => {
  const h = await ui(t);
  await h.requests();
  await h.page.getByRole("button", { name: "新建 Project", exact: true }).click();
  await h.page.locator("#composer input").fill("新项目");
  await h.page.getByRole("button", { name: "创建 Project", exact: true }).click();
  await h.page.waitForFunction(() => document.getElementById("notification").textContent.includes("Project 已创建"));
  h.state.operations = [operation("FAILED")];
  await h.tick();
  assert.match(await h.page.locator("#notification").innerText(), /模型暂不可用/);
  await h.close();
  await assertNoOverlay(h.page);
  await h.tick();
  await assertNoOverlay(h.page);
});

test("system readiness cannot retain an obsolete failure after a successful retry", async (t) => {
  const old = operation("FAILED");
  const h = await ui(t, { operations: [old] });
  await h.requests();
  h.state.ready = false;
  h.state.operations = [old, operation("SUCCEEDED", { operation_id: "retry", updated_at: "2026-09-21T00:01:00Z" })];
  await h.tick();
  assert.doesNotMatch(await h.page.locator("#notification").innerText(), /模型暂不可用/);
  assert.match(await h.page.locator("#notification").innerText(), /交付运行时尚未就绪/);
});

test("polling a different operation preserves the Product discussion draft and pasted screenshots", async (t) => {
  const h = await ui(t);
  await h.requests();
  const message = h.page.locator("#detail .discussion-form textarea");
  await message.fill("尚未提交给 Product 的详细需求");
  await message.evaluate((node) => {
    window.discussionInput = node;
    const clipboard = new DataTransfer();
    clipboard.items.add(new File(["fixture-image"], "draft.png", { type: "image/png" }));
    node.dispatchEvent(new ClipboardEvent("paste", { clipboardData: clipboard, bubbles: true }));
    node.setSelectionRange(2, 4);
  });
  h.state.operations = [operation("SUCCEEDED", { intent: { action: "CONTINUE_DELIVERY", project_id: "project_fixture", delivery_id: "another_request" } })];
  await h.tick();
  assert.equal(await h.page.evaluate(() => document.activeElement === discussionInput), true);
  assert.deepEqual(await message.evaluate(node => [node.selectionStart, node.selectionEnd]), [2, 4]);
  h.state.operations = [operation("FAILED", { intent: { action: "CONTINUE_DELIVERY", project_id: "project_fixture", delivery_id: "another_request" } })];
  await h.tick();
  await h.close();
  assert.equal(await message.inputValue(), "尚未提交给 Product 的详细需求");
  assert.equal(await h.page.evaluate(() => discussionInput.isConnected), true);
  assert.equal(await h.page.evaluate(() => document.activeElement === discussionInput), true);
  assert.match(await h.page.locator("#detail .screenshot-list").innerText(), /draft.png/);
  h.team.requests[0].checkpoint_sha256 = "b".repeat(64);
  await h.tick();
  assert.equal(await message.inputValue(), "", "a different checkpoint must not inherit stale input authority");
  assert.equal(await h.page.evaluate(() => discussionInput.isConnected), false);
  assert.doesNotMatch(await h.page.locator("#detail .screenshot-list").innerText(), /draft.png/);
});
