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
