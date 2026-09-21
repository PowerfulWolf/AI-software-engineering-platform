const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ui } = require("./fixture.cjs");
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
async function projectKnowledge(h) {
  await h.page.route("**/api/v1/admin/projects/*/knowledge", route => route.fulfill({ json: [] }));
  await h.page.route("**/api/v1/admin/projects/*/knowledge/index", route => route.fulfill({ json: null }));
  await h.page.route("**/api/v1/admin/projects/*/learnings", route => route.fulfill({ json: [] }));
  await h.page.locator("#nav-knowledge").click();
  await h.page.getByRole("tab", { name: "项目知识库", exact: true }).click();
  await h.page.getByRole("button", { name: "导入背景知识", exact: true }).waitFor();
}
async function drain(h, pattern, release) {
  const response = h.page.waitForResponse(pattern);
  release.resolve();
  await response;
  await h.page.evaluate(() => new Promise(resolve => setTimeout(resolve, 50)));
}

test("a late learning scan cannot publish into another Project", async t => {
  const h = await ui(t);
  h.team.projects.push({ id: "project_other", name: "Other project" });
  await h.tick();
  await projectKnowledge(h);
  await h.page.getByRole("tab", { name: "学习改进", exact: true }).click();
  const started = deferred(), release = deferred();
  await h.page.route("**/learnings/collect", async route => {
    started.resolve(); await release.promise;
    return route.fulfill({ json: [{ proposal: { proposal_id: "old-project-proposal", title: "旧项目建议",
      observation: "old", proposed_improvement: "old", verification: "old", occurrence_count: 1, evidence: [] } }] });
  });
  await h.page.getByRole("button", { name: "扫描 QA / Review 失败", exact: true }).click();
  await started.promise;
  h.team.selected_project_id = "project_other";
  h.team.requests = [];
  await h.page.getByRole("tab", { name: "Other project", exact: true }).click();
  await h.page.waitForFunction(() => !refreshing && currentProjectId() === "project_other");
  await drain(h, "**/learnings/collect", release);
  assert.equal(await h.page.getByText("旧项目建议", { exact: true }).count(), 0);
  assert.equal(await h.page.locator("#notification").isVisible(), false);
});

test("a rejected command from a previous Project does not interrupt the current one", async t => {
  const h = await ui(t);
  h.team.projects.push({ id: "project_other", name: "Other project" });
  h.team.requests[0].stage = "BLOCKED";
  await h.tick();
  await h.requests();
  await h.page.getByRole("tab", { name: /^阻塞中/ }).click();
  const started = deferred(), release = deferred();
  await h.page.route("**/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    started.resolve(); await release.promise;
    return route.fulfill({ status: 409, json: { error: { message: "旧项目的操作未被接受" } } });
  });
  await h.page.getByRole("button", { name: "继续交付", exact: true }).click();
  await started.promise;
  await h.page.locator("#projects summary").click();
  h.team.selected_project_id = "project_other";
  h.team.requests = [];
  await h.page.locator("#projects").getByRole("button", { name: "Other project", exact: true }).click();
  await h.page.waitForFunction(() => !refreshing && currentProjectId() === "project_other");
  await drain(h, "**/api/v1/operations", release);
  assert.equal(await h.page.locator("#notification").isVisible(), false);
});

test("a late index retry preserves a newly opened import draft", async t => {
  const h = await ui(t);
  await h.page.route("**/api/v1/admin/team/knowledge/index", route => route.fulfill({ json: {
    backlog: 0, failed: 1, oldest_pending_seconds: 0,
    jobs: [{ job_id: "job_fixture", source_name: "old.txt", status: "FAILED", error_code: "INDEX_INVALID" }],
  } }));
  await h.page.locator("#nav-knowledge").click();
  const started = deferred(), release = deferred();
  await h.page.route("**/index/job_fixture/retry", async route => {
    started.resolve(); await release.promise;
    return route.fulfill({ json: { status: "QUEUED" } });
  });
  await h.page.getByRole("button", { name: "重试索引", exact: true }).click();
  await started.promise;
  await h.page.getByRole("button", { name: "导入通用知识", exact: true }).click();
  const file = h.page.locator('#composer input[type="file"]');
  await file.setInputFiles({ name: "draft.txt", mimeType: "text/plain", buffer: Buffer.from("draft") });
  await drain(h, "**/index/job_fixture/retry", release);
  assert.equal(await file.evaluate(node => node.files[0]?.name), "draft.txt");
});

test("Knowledge navigation loads the new Project while an older Project read is pending", async t => {
  const h = await ui(t);
  h.team.projects.push({ id: "project_other", name: "Other project" });
  await h.tick();
  await projectKnowledge(h);
  await h.page.locator("#nav-team").click();
  const started = deferred(), release = deferred();
  await h.page.route("**/api/v1/admin/projects/project_fixture/knowledge", async route => {
    started.resolve(); await release.promise;
    return route.fulfill({ json: [] });
  });
  await h.page.locator("#nav-knowledge").click();
  await started.promise;
  await h.requests();
  await h.page.locator("#projects summary").click();
  h.team.selected_project_id = "project_other";
  h.team.requests = [];
  await h.page.locator("#projects").getByRole("button", { name: "Other project", exact: true }).click();
  await h.page.waitForFunction(() => !refreshing && currentProjectId() === "project_other");
  await h.page.locator("#nav-knowledge").click();
  await h.page.getByRole("button", { name: "导入背景知识", exact: true }).waitFor();
  await drain(h, "**/api/v1/admin/projects/project_fixture/knowledge", release);
  assert.equal(await h.page.getByRole("button", { name: "导入背景知识", exact: true }).count(), 1);
  assert.equal(await h.page.evaluate(() => knowledgeLoading), false);
});
