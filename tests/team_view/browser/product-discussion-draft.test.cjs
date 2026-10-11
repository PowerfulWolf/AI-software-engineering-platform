const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ui, operation } = require("./fixture.cjs");

function deferred() {
  let resolve;
  const promise = new Promise(done => {resolve = done;});
  return {promise, resolve};
}
async function discussion(t) {
  const h = await ui(t);
  h.team.requests[0].stage = "WAITING_PRODUCT_REPLY";
  h.team.requests[0].dialogue = [{speaker: "product", text: "请补充需求背景"}];
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const form = h.page.locator("#detail .discussion-form");
  const message = form.locator("textarea");
  await message.fill("等待发送的产品草稿，包含完整业务背景");
  await message.evaluate(node => {
    window.keptDiscussionMessage = node;
    window.keptDiscussionForm = node.closest("form");
    const clipboard = new DataTransfer();
    const png = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1sAAAAASUVORK5CYII="), char => char.charCodeAt(0));
    clipboard.items.add(new File([png], "draft.png", {type: "image/png"}));
    node.dispatchEvent(new ClipboardEvent("paste", {clipboardData: clipboard, bubbles: true}));
    window.keptDiscussionImage = node.closest("form").querySelector(".screenshot-chip img");
    node.setSelectionRange(2, 7);
  });
  let writes = 0;
  h.page.on("request", request => {if (request.method() !== "GET") writes++;});
  return {...h, form, message, submit: form.locator('button[type="submit"]'), writes: () => writes};
}
const oldSubmit = h => h.page.evaluate(() => {
  keptDiscussionForm.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
});
const settle = page => page.evaluate(() => new Promise(resolve =>
  requestAnimationFrame(() => requestAnimationFrame(resolve))));

for (const code of ["TEAM_READ_IN_PROGRESS", "TEAM_UNAVAILABLE"]) {
  test(`Product draft remains editable through ${code}, while saved callbacks cannot upload or submit`, async t => {
    const h = await discussion(t);
    await h.page.route("http://ui.test/api/v1/team?**", route => route.fulfill({status: 503,
      json: {error: {code, message: "provider-private-message"}}}));
    await h.tick();
    assert.equal(await h.form.isVisible(), true, "a read outage must not hide the draft");
    assert.equal(await h.message.evaluate(node => node === keptDiscussionMessage), true);
    assert.equal(await h.page.evaluate(() => document.activeElement === keptDiscussionMessage), true);
    assert.deepEqual(await h.message.evaluate(node => [node.selectionStart, node.selectionEnd]), [2, 7]);
    assert.equal(await h.form.locator(".screenshot-chip img").evaluate(node => node === keptDiscussionImage), true);
    assert.match(await h.message.inputValue(), /完整业务背景/);
    assert.equal(await h.message.isEnabled(), true);
    assert.equal(await h.submit.isDisabled(), true);
    assert.match(await h.form.locator(".discussion-availability").innerText(), /暂停发送.*草稿.*编辑.*复制/);
    assert.doesNotMatch(await h.form.innerText(), /provider-private-message/);
    if (process.env.ASE_UI_SCREENSHOT_DIR && code === "TEAM_UNAVAILABLE") {
      for (const width of [1440, 390]) {
        await h.page.setViewportSize({width, height: 844});
        await h.form.scrollIntoViewIfNeeded();
        await settle(h.page);
        await h.page.screenshot({path: process.env.ASE_UI_SCREENSHOT_DIR + `/product-discussion-outage-${width}.png`});
      }
    }
    await oldSubmit(h);
    await h.page.waitForFunction(() => !uiCommands.has(keptDiscussionForm));
    assert.equal(h.writes(), 0, "the old submit event must not upload screenshots");
    await h.message.fill("读取失败时仍可整理的草稿");
    await h.message.evaluate(node => node.setSelectionRange(1, 5));
    await h.page.unroute("http://ui.test/api/v1/team?**");
    await h.tick();
    assert.equal(await h.message.evaluate(node => node === keptDiscussionMessage), true);
    assert.equal(await h.page.evaluate(() => document.activeElement === keptDiscussionMessage), true);
    assert.deepEqual(await h.message.evaluate(node => [node.selectionStart, node.selectionEnd]), [1, 5]);
    assert.equal(await h.message.inputValue(), "读取失败时仍可整理的草稿");
    assert.equal(await h.submit.isEnabled(), true);
    assert.equal(await h.form.locator(".discussion-availability").isVisible(), false);
    await h.page.setViewportSize({width: 390, height: 844});
    await settle(h.page);
    assert.equal(await h.form.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(h.writes(), 0);
  });
}

test("an existing draft stays visible and editable when the Team GET deadline expires", async t => {
  const h = await discussion(t);
  await h.page.evaluate(() => {
    window.productDraftOriginalTimeout = window.setTimeout;
    window.setTimeout = (callback, delay, ...args) => productDraftOriginalTimeout(callback, delay === 40000 ? 30 : delay, ...args);
  });
  let held;
  await h.page.route("http://ui.test/api/v1/team?**", route => {held = route;});
  await h.tick();
  assert.equal(await h.page.evaluate(() => teamReadIssue), "timeout");
  assert.equal(await h.form.isVisible(), true);
  assert.equal(await h.message.evaluate(node => node === keptDiscussionMessage), true);
  assert.equal(await h.message.isEnabled(), true);
  assert.equal(await h.submit.isDisabled(), true);
  await oldSubmit(h);
  await h.page.waitForFunction(() => !uiCommands.has(keptDiscussionForm));
  assert.equal(h.writes(), 0);
  if (held) await held.abort().catch(() => {});
  await h.page.unroute("http://ui.test/api/v1/team?**");
  await h.tick();
  assert.equal(await h.submit.isEnabled(), true);
  assert.equal(await h.message.evaluate(node => node === keptDiscussionMessage), true);
});

test("a saved Product callback cannot write after an in-place checkpoint change or Project switch", async t => {
  const h = await discussion(t);
  await h.page.evaluate(() => {snapshot.requests[0].checkpoint_sha256 = "b".repeat(64);});
  await oldSubmit(h);
  await h.page.waitForFunction(() => !uiCommands.has(keptDiscussionForm));
  assert.equal(h.writes(), 0, "a mutable request object cannot give its old callback a new checkpoint");
  h.team.requests[0].checkpoint_sha256 = "b".repeat(64);
  h.team.requests[0].title = "新 checkpoint 的当前需求";
  await h.tick();
  assert.equal(await h.page.evaluate(() => keptDiscussionForm.isConnected), false);
  await oldSubmit(h);
  await h.page.waitForFunction(() => !uiCommands.has(keptDiscussionForm));
  assert.equal(h.writes(), 0);
  h.team.selected_project_id = "project_next";
  h.team.projects.push({id: "project_next", name: "新项目"});
  h.team.requests = [{...h.team.requests[0], project_id: "project_next", title: "新项目需求"}];
  await h.page.evaluate(() => refresh("project_next"));
  await oldSubmit(h);
  await h.page.waitForFunction(() => !uiCommands.has(keptDiscussionForm));
  assert.equal(h.writes(), 0);
  assert.equal(await h.message.inputValue(), "");
});

for (const invalidation of ["checkpoint", "team-read", "active-operation"]) test(`each screenshot await rechecks ${invalidation} before the next write and retains the draft`, async t => {
  const h = await discussion(t);
  await h.message.evaluate(node => {
    const clipboard = new DataTransfer();
    clipboard.items.add(new File(["second-image"], "second.png", {type: "image/png"}));
    node.dispatchEvent(new ClipboardEvent("paste", {clipboardData: clipboard, bubbles: true}));
  });
  const uploaded = deferred(), release = deferred();
  let uploads = 0, operations = 0;
  await h.page.route("**/screenshots?**", async route => {
    uploads++; uploaded.resolve(); await release.promise;
    await route.fulfill({json: {id: "attachment_fixture"}});
  });
  await h.page.route("**/api/v1/operations", route => {
    if (route.request().method() !== "POST") return route.fallback();
    operations++;
    return route.fulfill({json: operation("QUEUED")});
  });
  await h.submit.click();
  await uploaded.promise;
  await h.page.evaluate(invalidation => {
    if (invalidation === "checkpoint") snapshot.requests[0].checkpoint_sha256 = "c".repeat(64);
    else if (invalidation === "team-read") teamReadIssue = "unavailable";
    else operations.push({operation_id: "intervening_product_operation", status: "QUEUED",
      intent: {action: "PRODUCT_REPLY", project_id: "project_fixture", delivery_id: "request_fixture"}});
  }, invalidation);
  release.resolve();
  await h.page.waitForFunction(() => !uiCommands.has(keptDiscussionForm));
  assert.equal(uploads, 1);
  assert.equal(operations, 0);
  assert.match(await h.message.inputValue(), /完整业务背景/);
  assert.equal(await h.form.locator(".screenshot-chip").count(), 2);
  assert.match(await h.form.locator(".form-feedback").innerText(), /更新|失效|重新核对/);
});

test("a pending Product submit and its accepted Operation reject repeated saved callbacks", async t => {
  const h = await discussion(t);
  const uploaded = deferred(), release = deferred();
  let uploads = 0, operations = 0, submitted;
  await h.page.route("**/screenshots?**", async route => {
    uploads++; uploaded.resolve(); await release.promise;
    return route.fulfill({json: {id: "attachment_fixture"}});
  });
  await h.page.route("**/api/v1/operations", route => {
    if (route.request().method() !== "POST") return route.fallback();
    operations++;
    submitted = route.request().postDataJSON().intent;
    return route.fulfill({json: operation("QUEUED", {intent: submitted})});
  });
  await h.submit.click();
  await uploaded.promise;
  await oldSubmit(h);
  assert.equal(uploads, 1);
  release.resolve();
  await h.page.waitForFunction(() => !uiCommands.has(keptDiscussionForm));
  assert.equal(operations, 1);
  assert.deepEqual(submitted, {action: "PRODUCT_REPLY", project_id: "project_fixture",
    delivery_id: "request_fixture", expected_checkpoint_sha256: "a".repeat(64),
    message: "等待发送的产品草稿，包含完整业务背景", screenshot_ids: ["attachment_fixture"]});
  await oldSubmit(h);
  await h.page.waitForFunction(() => !uiCommands.has(keptDiscussionForm));
  assert.equal(uploads, 1);
  assert.equal(operations, 1);
  assert.equal(await h.message.isDisabled(), true);
  assert.equal(await h.submit.count(), 1);
  assert.equal(await h.submit.isDisabled(), true);
});

test("a pending interrupted Product continuation rejects repeated saved click events", async t => {
  const h = await discussion(t);
  h.team.requests[0].stage = "PRODUCT_DISCOVERY";
  await h.tick();
  const form = h.page.locator("#detail .discussion-form");
  const submit = form.locator('button[data-delivery-control="true"]');
  await submit.evaluate(node => {window.keptProductContinue = node;});
  const started = deferred(), release = deferred();
  let posts = 0;
  await h.page.route("**/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    posts++; started.resolve(); await release.promise;
    return route.fulfill({json: operation("QUEUED", {intent: route.request().postDataJSON().intent})});
  });
  await submit.click();
  await started.promise;
  await h.page.evaluate(() => keptProductContinue.dispatchEvent(new MouseEvent("click", {bubbles: true})));
  await settle(h.page);
  assert.equal(posts, 1, "pending continuation must not accept a second click event");
  assert.equal(await submit.isDisabled(), true);
  release.resolve();
  await h.page.waitForFunction(() => !uiCommands.has(keptProductContinue.closest("form")));
  await h.page.evaluate(() => keptProductContinue.dispatchEvent(new MouseEvent("click", {bubbles: true})));
  await settle(h.page);
  assert.equal(posts, 1, "the accepted Operation also blocks the old click callback");
});
