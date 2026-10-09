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

test("late Requirement edit facts preserve the user's explicit detail close", async t => {
  const h = await ui(t);
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const teamStarted = deferred(), teamRelease = deferred(), operationsRelease = deferred();
  await h.page.route("**/api/v1/team?*", async route => {
    teamStarted.resolve();
    await teamRelease.promise;
    return route.fulfill({json: h.team});
  });
  await h.page.route("**/api/v1/operations", async route => {
    await operationsRelease.promise;
    return route.fulfill({json: [{operation_id: "operation_edit", status: "SUCCEEDED",
      updated_at: "2026-10-09T00:00:00Z",
      intent: {action: "UPDATE_REQUIREMENT", project_id: "project_fixture", delivery_id: "request_fixture"},
      result: {delivery_id: "request_replacement"}}]});
  });
  t.after(() => {teamRelease.resolve(); operationsRelease.resolve();});
  const polling = h.tick();
  await teamStarted.promise;
  await h.page.getByRole("button", {name: "关闭详情", exact: true}).click();
  h.team.requests = [{...h.team.requests[0], id: "request_replacement", title: "Edited requirement"}];
  teamRelease.resolve();
  await h.page.waitForFunction(() => snapshot.requests[0].id === "request_replacement");
  operationsRelease.resolve();
  await polling;
  assert.equal(await h.page.evaluate(() => selected), null);
  assert.equal(await h.page.locator("#detail").isVisible(), false);
});

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
  await h.page.getByRole("button", { name: "收集项目发现与失败经验", exact: true }).click();
  await started.promise;
  h.team.selected_project_id = "project_other";
  h.team.requests = [];
  await h.page.getByRole("tab", { name: "Other project", exact: true }).click();
  await h.page.waitForFunction(() => !refreshing && currentProjectId() === "project_other");
  await drain(h, "**/learnings/collect", release);
  assert.equal(await h.page.getByText("旧项目建议", { exact: true }).count(), 0);
  assert.equal(await h.page.locator("#notification").isVisible(), false);
});

test("learning provenance distinguishes discoveries and human resolutions without executing text", async t => {
  const h = await ui(t);
  await projectKnowledge(h);
  const proposal = {
    proposal_id: "learning_fixture", project_id: "project_fixture", title: "项目发现",
    observation: "Refunds use original payment identity.", proposed_improvement: "Reuse scoped background.",
    verification: "Verify the next candidate independently.", occurrence_count: 1,
  };
  await h.page.route("**/api/v1/admin/projects/*/learnings", route => route.fulfill({ json: [
    { proposal: { ...proposal, trigger: "PROJECT_OBSERVATION", evidence: [{
      repository_id: "repository_fixture", task_id: "task_fixture", artifact_id: "art_fixture",
      artifact_sha256: "a".repeat(64), role: "coder", source_revision: "candidate_exact",
      observation_id: "refund_identity", applicability: "Only this repository <script>throw 1</script>",
      evidence_uris: ["evidence://observed"],
    }] } },
    { proposal: { ...proposal, title: "人工确认", trigger: "KNOWLEDGE_RESOLUTION", evidence: [{
      requirement_id: "requirement_prior", gap_id: "gap_prior", resolution_id: "resolution_prior",
      previous_run_id: "run_prior", evidence_uris: ["human://approved-answer"],
    }] } },
  ] }));
  await h.page.getByRole("tab", { name: "学习改进", exact: true }).click();
  const cards = h.page.locator(".learning-card");
  await cards.nth(1).waitFor();
  const rendered = await cards.allTextContents();
  assert.match(rendered[0], /候选 candidate_exact/);
  assert.match(rendered[0], /适用范围.*<script>throw 1<\/script>/);
  assert.match(rendered[1], /需求 requirement_prior.*确认 resolution_prior/);
  assert.doesNotMatch(rendered.join(""), /undefined/);
  assert.equal(await cards.locator("script").count(), 0);
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
