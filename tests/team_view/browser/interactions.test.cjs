const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ui, operation } = require("./fixture.cjs");

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
const documentFixture = name => ({ manifest: { document_id: name, source_name: name,
  media_type: "text/plain", source_bytes: 1, normalized_bytes: 1,
  source_sha256: "a".repeat(64), normalized_relative_path: name + "/content.md",
  imported_at: "2026-09-21T00:00:00Z" }, selected: false });

test("a submitted confirmation cannot be cancelled or submitted twice", async t => {
  const h = await ui(t);
  await h.requests();
  const started = deferred(), response = deferred();
  let posts = 0;
  await h.page.route("**/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    posts++;
    started.resolve();
    await response.promise;
    return route.fulfill({ json: operation("QUEUED", { intent: {
      action: "DELETE_REQUIREMENT", project_id: "project_fixture", delivery_id: "request_fixture",
    } }) });
  });
  await h.page.getByRole("button", { name: "删除需求", exact: true }).click();
  await h.page.getByRole("button", { name: "确认删除", exact: true }).click();
  await started.promise;
  const cancel = h.page.locator("#composer").getByRole("button", { name: "取消", exact: true });
  assert.equal(await cancel.isEnabled(), false);
  await h.page.keyboard.press("Escape");
  assert.equal(await h.page.locator("#composer").isVisible(), true);
  assert.match(await h.page.locator("#composer").innerText(), /正在提交/);
  response.resolve();
  await h.page.waitForFunction(() => !pendingConfirmation);
  await h.close();
  await h.draft();
  await h.tick();
  assert.equal(await h.page.locator('#composer input[name="name"]').inputValue(), "保留正在编辑的需求");
  assert.equal(posts, 1);
});

test("late knowledge responses cannot replace a newer scope", async t => {
  const h = await ui(t);
  await h.page.locator("#nav-knowledge").click();
  await h.page.getByRole("button", { name: "导入通用知识", exact: true }).waitFor();
  const started = deferred(), release = deferred();
  await h.page.route("**/api/v1/admin/team/knowledge", async route => {
    started.resolve(); await release.promise;
    return route.fulfill({ json: [documentFixture("team-only.txt")] });
  });
  await h.page.route("**/api/v1/admin/projects/project_fixture/knowledge", route =>
    route.fulfill({ json: [documentFixture("project-only.txt")] }));
  await h.page.route("**/api/v1/admin/projects/project_fixture/knowledge/index", route => route.fulfill({ json: null }));
  await h.page.getByRole("tab", { name: "团队知识库", exact: true }).click();
  await started.promise;
  await h.page.getByRole("tab", { name: "项目知识库", exact: true }).click();
  await h.page.getByText("project-only.txt", { exact: true }).waitFor();
  const finished = h.page.waitForResponse("**/api/v1/admin/team/knowledge");
  release.resolve(); await finished;
  // Drain the awaited response body and its continuation through the real event loop.
  await h.page.evaluate(() => new Promise(resolve => setTimeout(resolve, 50)));
  assert.equal(await h.page.getByText("team-only.txt", { exact: true }).count(), 0);
  assert.equal(await h.page.getByText("project-only.txt", { exact: true }).count(), 1);
});

test("unsaved Settings survive page navigation without storing secrets", async t => {
  const h = await ui(t);
  await h.page.locator("#nav-settings").click();
  await h.page.locator("#content input").first().fill("/fixture/unsaved-edit");
  await h.page.locator("#nav-team").click();
  await h.page.locator("#nav-settings").click();
  await h.page.locator("#content input").first().waitFor();
  assert.equal(await h.page.locator("#content input").first().inputValue(), "/fixture/unsaved-edit");
});

test("composer traps keyboard focus and Escape protects a dirty draft", async t => {
  const h = await ui(t);
  await h.requests();
  await h.draft();
  for (let index = 0; index < 10; index++) {
    await h.page.keyboard.press(index % 2 ? "Shift+Tab" : "Tab");
    assert.equal(await h.page.evaluate(() => document.getElementById("composer").contains(document.activeElement)), true);
  }
  h.page.once("dialog", dialog => dialog.dismiss());
  await h.page.keyboard.press("Escape");
  assert.equal(await h.page.locator('#composer input[name="name"]').inputValue(), "保留正在编辑的需求");
  h.page.once("dialog", dialog => dialog.accept());
  await h.page.keyboard.press("Escape");
  assert.equal(await h.page.locator("#composer").isVisible(), false);
  assert.equal(await h.page.evaluate(() => document.activeElement.textContent), "新建需求");
});

test("foreign Project failures are scoped to their Project", async t => {
  const h = await ui(t, { operations: [operation("FAILED", { intent: {
    action: "CONTINUE_DELIVERY", project_id: "project_other", delivery_id: "foreign",
  }, error_summary: "另一个项目的失败" })] });
  await h.requests();
  assert.equal(await h.page.locator("#notification").isVisible(), false);
});

test("discussion drafts survive switching Requirements and pages", async t => {
  const h = await ui(t);
  h.team.requests.push({ ...h.team.requests[0], id: "request_second", title: "Second request" });
  await h.tick();
  await h.requests();
  await h.page.locator("#detail .discussion-form textarea").fill("第一份尚未提交的需求");
  await h.page.getByRole("button", { name: /Second request/ }).click();
  await h.page.locator("#detail .discussion-form textarea").fill("第二份草稿");
  await h.page.getByRole("button", { name: /Fixture request/ }).click();
  assert.equal(await h.page.locator("#detail .discussion-form textarea").inputValue(), "第一份尚未提交的需求");
  await h.page.locator("#nav-team").click();
  await h.requests();
  assert.equal(await h.page.locator("#detail .discussion-form textarea").inputValue(), "第一份尚未提交的需求");
});

test("the newest same-scope knowledge read wins even when the older request fails", async t => {
  const h = await ui(t);
  await h.page.locator("#nav-knowledge").click();
  await h.page.getByRole("button", { name: "导入通用知识", exact: true }).waitFor();
  const started = deferred(), release = deferred();
  let count = 0;
  await h.page.route("**/api/v1/admin/team/knowledge", async route => {
    if (++count === 1) {
      started.resolve(); await release.promise;
      return route.fulfill({ status: 500, json: { error: { message: "过期读取错误" } } });
    }
    return route.fulfill({ json: [documentFixture("newest.txt")] });
  });
  await h.page.getByRole("tab", { name: "团队知识库", exact: true }).click();
  await started.promise;
  await h.page.getByRole("tab", { name: "团队知识库", exact: true }).click();
  await h.page.getByText("newest.txt", { exact: true }).waitFor();
  const finished = h.page.waitForResponse("**/api/v1/admin/team/knowledge");
  release.resolve(); await finished;
  await h.page.evaluate(() => new Promise(resolve => setTimeout(resolve, 50)));
  assert.equal(await h.page.getByText("newest.txt", { exact: true }).count(), 1);
  assert.doesNotMatch(await h.page.locator("#content").innerText(), /过期读取错误/);
});

test("changing knowledge mode ignores stale documents and index status", async t => {
  const h = await ui(t);
  await h.page.locator("#nav-knowledge").click();
  await h.page.getByRole("button", { name: "导入通用知识", exact: true }).waitFor();
  const started = deferred(), release = deferred();
  await h.page.route("**/api/v1/admin/team/knowledge/index", async route => {
    started.resolve(); await release.promise;
    return route.fulfill({ json: { backlog: 999, failed: 0, oldest_pending_seconds: 0, jobs: [] } });
  });
  await h.page.route("**/api/v1/admin/team/specs", route => route.fulfill({ json: [] }));
  await h.page.getByRole("tab", { name: "团队知识库", exact: true }).click();
  await started.promise;
  await h.page.getByRole("tab", { name: "开发规范", exact: true }).click();
  await h.page.getByRole("button", { name: "导入开发规范", exact: true }).waitFor();
  const finished = h.page.waitForResponse("**/api/v1/admin/team/knowledge/index");
  release.resolve(); await finished;
  await h.page.evaluate(() => new Promise(resolve => setTimeout(resolve, 50)));
  assert.equal(await h.page.evaluate(() => knowledgeIndexStatus), null);
  assert.equal(await h.page.getByRole("tab", { name: "开发规范", exact: true }).getAttribute("aria-selected"), "true");
});

test("late knowledge selection results do not overwrite a different scope or editor", async t => {
  const h = await ui(t);
  await h.page.route("**/api/v1/admin/team/knowledge", route => route.fulfill({ json: [documentFixture("team.txt")] }));
  await h.page.route("**/api/v1/admin/projects/project_fixture/knowledge", route => route.fulfill({ json: [] }));
  await h.page.route("**/api/v1/admin/projects/project_fixture/knowledge/index", route => route.fulfill({ json: null }));
  await h.page.locator("#nav-knowledge").click();
  const started = deferred(), release = deferred();
  await h.page.route("**/api/v1/admin/team/knowledge/selection", async route => {
    started.resolve(); await release.promise;
    return route.fulfill({ json: [{ ...documentFixture("team.txt"), selected: true }] });
  });
  await h.page.getByRole("button", { name: "用于新需求", exact: true }).click();
  await started.promise;
  await h.page.getByRole("tab", { name: "项目知识库", exact: true }).click();
  await h.page.getByRole("button", { name: "导入背景知识", exact: true }).click();
  const file = h.page.locator('#composer input[type="file"]');
  await file.setInputFiles({ name: "draft.txt", mimeType: "text/plain", buffer: Buffer.from("draft") });
  const finished = h.page.waitForResponse("**/api/v1/admin/team/knowledge/selection");
  release.resolve(); await finished;
  await h.page.evaluate(() => new Promise(resolve => setTimeout(resolve, 50)));
  assert.equal(await file.evaluate(node => node.files[0].name), "draft.txt");
  assert.equal(await h.page.getByText("team.txt", { exact: true }).count(), 0);
  assert.equal(await h.page.locator("#notification").isVisible(), false);
});

test("Settings keep secret drafts in memory and protect pending saves from polling", async t => {
  const h = await ui(t);
  await h.page.locator("#nav-settings").click();
  await h.page.getByRole("button", { name: /^MySQL/ }).click();
  const secret = h.page.locator('#content input[type="password"]').first();
  await secret.fill("fixture-secret-never-persist");
  await h.page.locator("#nav-team").click();
  await h.page.locator("#nav-settings").click();
  await secret.waitFor();
  assert.equal(await secret.inputValue(), "fixture-secret-never-persist");
  assert.equal(await h.page.evaluate(() => JSON.stringify(localStorage).includes("fixture-secret-never-persist")), false);
  const started = deferred(), release = deferred();
  await h.page.route("**/api/v1/admin/settings", async route => {
    if (route.request().method() !== "PUT") return route.fallback();
    started.resolve(); await release.promise;
    return route.fulfill({ status: 500, json: { error: { message: "保存失败，请重试" } } });
  });
  await h.page.getByRole("button", { name: "保存设置", exact: true }).click();
  await started.promise;
  await secret.evaluate(node => { window.savedSecretNode = node; });
  h.state.operations.push(operation("SUCCEEDED"));
  await h.tick();
  assert.equal(await secret.isEnabled(), false);
  assert.equal(await h.page.evaluate(() => savedSecretNode.isConnected), true);
  release.resolve();
  await h.page.locator("#composer").getByRole("button", { name: "知道了", exact: true }).click();
  assert.equal(await secret.isEnabled(), true);
  assert.equal(await secret.inputValue(), "fixture-secret-never-persist");
});

test("clean confirmation and task dialogs trap focus and Escape restores the page", async t => {
  const h = await ui(t);
  await h.requests();
  await h.page.getByRole("button", { name: "删除需求", exact: true }).click();
  await h.page.keyboard.press("Shift+Tab");
  assert.equal(await h.page.evaluate(() => document.getElementById("composer").contains(document.activeElement)), true);
  await h.page.keyboard.press("Escape");
  assert.equal(await h.page.locator("#composer").isVisible(), false);
  h.team.tasks.push({ id: "task_fixture", request_id: "request_fixture", title: "Task fixture", status: "NEW",
    scope: { root: "/fixture", selected_paths: ["."] }, assignments: [], timeline: [], runs: [], documents: [] });
  await h.tick();
  await h.page.evaluate(() => showDetail("task", "task_fixture"));
  for (let i = 0; i < 5; i++) {
    await h.page.keyboard.press("Tab");
    assert.equal(await h.page.evaluate(() => document.getElementById("detail").contains(document.activeElement)), true);
  }
  await h.page.keyboard.press("Escape");
  assert.equal(await h.page.locator(".task-detail-dialog").count(), 0);
  await h.page.locator("#nav-team").click();
  assert.equal(await h.page.locator("#heading").innerText(), "团队成员");
});
