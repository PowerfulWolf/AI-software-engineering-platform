const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {ui, operation} = require("./fixture.cjs");

const scope = {operation_id: "operation_" + "1".repeat(32), team_id: "team_fixture", project_id: "project_fixture",
  delivery_id: "request_fixture", expected_checkpoint_sha256: "a".repeat(64), approved_plan_sha256: "e".repeat(64)};
const taskId = "task_recovery_" + scope.approved_plan_sha256.slice(0, 32);
function record(kind, evidence, index = 0) {
  return {kind, evidence, scope, observed_at: `2026-10-10T09:${String(index).padStart(2, "0")}:00Z`, record_sha256: String(index + 1).repeat(64)};
}
function records(inputMode = "preserve_draft") {
  return [record("AUTHORIZATION_RECORDED", {authorization_sha256: "b".repeat(64)}),
    record("TASK_SEALED", {task_id: taskId, task_record_sha256: "b".repeat(64), source_revision: "a".repeat(40)}, 1),
    record("DISPATCH_COMMITTED", {task_id: taskId, dispatch_id: "dispatch_commit_" + scope.approved_plan_sha256, dispatch_sha256: "b".repeat(64), task_record_sha256: "c".repeat(64)}, 2),
    record("SEED_VERIFIED", {task_id: taskId, seed_record_sha256: "b".repeat(64), dispatch_sha256: "c".repeat(64), input_mode: inputMode}, 3),
    record("EXECUTION_CLAIMED", {task_id: taskId, work_item_id: "work_test", lease_id: "lease_test", assignment_id: "assignment_test",
      claim_sha256: "b".repeat(64), dispatch_sha256: "c".repeat(64), source_revision: "a".repeat(40), role: "coder", attempt: 1}, 4)];
}
async function recoveryUi(t, initial = records().slice(0, 1)) {
  const h = await ui(t);
  const state = {records: initial, failure: null, reads: 0, writes: 0};
  h.page.on("request", request => {if (request.method() !== "GET") state.writes++;});
  await h.page.route("**/preparation-progress", route => {
    state.reads++;
    return state.failure ? route.fulfill({status: state.failure, json: {error: {message: "private provider secret"}}})
      : route.fulfill({json: {schema_version: "v0.1", scope, records: state.records}});
  });
  const request = h.team.requests[0];
  Object.assign(request, {title: "K1 自动知识采集首个闭环", stage: "BLOCKED", blocker: "原开发执行已停止，完整进度保留。",
    scopes: [{delivery_id: "native_test", root: "/fixture/repository", selected_paths: ["src/**"]}],
    documents: [{name: "已保存的开发方案", source_uri: "artifact://preparation-saved", sha256: "f".repeat(64), content: "保留正在阅读的工程正文与文本选择。"}],
    execution: {state: "STOPPED", responsibility: "engineering", reason: "原开发执行已停止，完整进度保留。", next_action: "查看恢复准备事实。", action_required: false}});
  h.team.tasks = [{id: "native_test", task_id: "task_original", project_id: request.project_id, request_id: request.id,
    title: request.title, status: "BLOCKED", terminal: true, blocker: request.blocker, scope: request.scopes[0],
    execution: request.execution, last_activity: "2026-10-10T07:00:00Z", role_queue: [], runs: [], timeline: [], documents: [], assignments: []}];
  h.state.operations = [operation("SUCCEEDED", {team_id: scope.team_id, requested_at: "2026-10-10T07:00:00Z", updated_at: "2026-10-10T07:00:00Z",
    intent: {action: "CONTINUE_DELIVERY", project_id: scope.project_id, delivery_id: scope.delivery_id, expected_checkpoint_sha256: scope.expected_checkpoint_sha256},
    result: {project_id: scope.project_id, delivery_id: scope.delivery_id, checkpoint_sha256: scope.expected_checkpoint_sha256, stage: "BLOCKED",
      approval: {kind: "coder_recovery", plan_sha256: scope.approved_plan_sha256, title: "保留进度并继续原需求", facts: []}}}),
    operation("RUNNING", {team_id: scope.team_id, operation_id: scope.operation_id, requested_at: "2026-10-10T08:00:00Z", updated_at: "2026-10-10T08:00:00Z",
      intent: {action: "CONTINUE_DELIVERY", project_id: scope.project_id, delivery_id: scope.delivery_id,
        expected_checkpoint_sha256: scope.expected_checkpoint_sha256, approved_plan_sha256: scope.approved_plan_sha256}})];
  await h.tick();
  await h.requests();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const section = h.page.locator("#detail .recovery-preparation");
  await section.getByText(initial.length ? "恢复授权已核验" : /本次操作没有已保存的准备明细/, {exact: Boolean(initial.length)}).waitFor();
  await h.page.waitForFunction(() => recoveryPreparationFlight === null);
  return {...h, progressState: state, section};
}

test("independent preparation polling updates during a held Team read and preserves reading state", async t => {
  const h = await recoveryUi(t);
  await h.section.locator(".preparation-milestones li").first().evaluate(node => {window.preparationFirstRecord = node;});
  const document = h.page.locator('details[data-key="artifact://preparation-saved"]');
  await document.locator(":scope > summary").click();
  await document.evaluate(node => {
    window.preparationDocument = node;
    const body = node.querySelector(".artifact-body") || node.querySelector("pre") || node.querySelector("p");
    window.preparationSelectedNode = body;
    const range = document.createRange(); range.selectNodeContents(body);
    getSelection().removeAllRanges(); getSelection().addRange(range);
    window.preparationSelectedText = getSelection().toString();
  });
  let release, started;
  const held = new Promise(resolve => {release = resolve;});
  const reading = new Promise(resolve => {started = resolve;});
  t.after(() => release());
  await h.page.route("**/api/v1/team?**", async route => {started(); await held; return route.fulfill({json: h.team});});
  const polling = h.tick();
  await reading;
  h.progressState.records = records();
  await h.page.evaluate(() => refreshRecoveryPreparationProgress());
  assert.equal(await h.page.evaluate(() => refreshing), true, "the independent lane settles before Team");
  assert.equal(await h.section.locator(".preparation-milestones li").count(), 5);
  assert.equal(await h.section.locator(".preparation-milestones li").first().evaluate(node => node === window.preparationFirstRecord), true);
  assert.match(await h.section.innerText(), /开发执行已领取（历史记录）/);
  assert.doesNotMatch(await h.section.innerText(), /正在执行|已通过|100%/);
  assert.equal(await document.evaluate(node => node === window.preparationDocument && node.open), true);
  assert.equal(await h.page.evaluate(() => preparationSelectedNode.isConnected && getSelection().toString() === preparationSelectedText), true);
  await h.section.evaluate(node => {window.preparationSavedSection = node;});
  await h.page.evaluate(() => refreshRecoveryPreparationProgress());
  assert.equal(await h.section.evaluate(node => node === window.preparationSavedSection), true, "unchanged reread retains the preparation DOM");
  assert.equal(await document.evaluate(node => node === window.preparationDocument && node.open), true);
  const history = h.page.locator('#detail details[data-key^="operation-history:"]');
  await history.locator(":scope > summary").click();
  assert.match(await history.innerText(), /最近准备记录.*开发执行已领取/);
  assert.equal(await history.locator(".preparation-milestones").count(), 0, "history reuses one latest-fact summary");
  release();
  await polling;
  await h.draft();
  h.progressState.failure = 409;
  await h.page.evaluate(() => refreshRecoveryPreparationProgress());
  assert.equal(await h.page.locator('#composer input[name="name"]').evaluate(node => node === window.draftInput), true);
  assert.equal(await h.page.locator('#composer input[name="name"]').inputValue(), "保留正在编辑的需求");
  assert.equal(h.progressState.writes, 0);
});

test("a delayed progress response cannot populate a different selected Requirement", async t => {
  const h = await recoveryUi(t);
  let release, started;
  const held = new Promise(resolve => {release = resolve;});
  const reading = new Promise(resolve => {started = resolve;});
  t.after(() => release());
  await h.page.route("**/preparation-progress", async route => {
    started(); await held;
    try {return await route.fulfill({json: {schema_version: "v0.1", scope, records: records()}});} catch { /* The scoped read was aborted. */ }
  });
  const progress = h.page.evaluate(() => refreshRecoveryPreparationProgress());
  await reading;
  await h.page.evaluate(() => {
    snapshot.requests.push({...snapshot.requests[0], id: "request_other", title: "其他需求", scopes: [], execution: null});
    showDetail("request", "request_other");
  });
  release(); await progress;
  assert.equal(await h.page.locator("#detail .recovery-preparation").count(), 0);
  assert.equal(await h.page.evaluate(() => recoveryPreparationObservation), null);
  assert.equal(h.progressState.writes, 0);
});

test("legacy, unavailable and corrupt preparation reads keep saved facts without enabling delivery", async t => {
  const h = await recoveryUi(t, []);
  assert.match(await h.section.innerText(), /本次操作没有已保存的准备明细/);
  h.progressState.failure = 404;
  await h.page.evaluate(() => refreshRecoveryPreparationProgress());
  assert.match(await h.section.innerText(), /当前服务不提供恢复准备明细/);
  h.progressState.failure = null;
  h.progressState.records = records("coder_reapply");
  await h.page.evaluate(() => refreshRecoveryPreparationProgress());
  assert.match(await h.section.innerText(), /旧进度交由开发继续适配/);
  assert.doesNotMatch(await h.section.innerText(), /改动已载入/);
  await h.page.route("**/api/v1/team?**", route => route.fulfill({status: 503,
    json: {error: {code: "TEAM_READ_IN_PROGRESS", message: "private provider secret"}}}));
  await h.tick();
  h.progressState.failure = 409;
  await h.page.evaluate(() => refreshRecoveryPreparationProgress());
  assert.match(await h.section.innerText(), /暂不可读取.*自动重试/);
  assert.match(await h.section.innerText(), /保留上次读取的明细/);
  assert.equal(await h.section.locator(".preparation-milestones li").count(), 5);
  assert.doesNotMatch(await h.section.innerText(), /private|secret/);
  assert.equal(await h.page.evaluate(() => canControlCurrentTeam()), false);
  assert.equal(await h.section.getByRole("button").count(), 0);
  h.progressState.failure = null;
  await h.page.evaluate(() => showDetail("task", "native_test"));
  await h.page.locator("#detail .recovery-preparation").getByRole("heading", {name: "当前需求的恢复准备明细", exact: true}).waitFor();
  assert.equal(await h.page.locator("#detail .preparation-milestones li").count(), 5);
  assert.equal(await h.page.evaluate(() => canControlCurrentTeam()), false);
  assert.equal(h.progressState.writes, 0);
});

test("preparation layout stays compact and readable at desktop, tablet and mobile widths", async t => {
  const h = await recoveryUi(t, records());
  const directory = process.env.ASE_UI_SCREENSHOT_DIR || "/tmp/ase-preparation-progress-20261010";
  fs.mkdirSync(directory, {recursive: true});
  for (const width of [1440, 1024, 390]) {
    await h.page.setViewportSize({width, height: 900});
    await h.section.scrollIntoViewIfNeeded();
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, `${width} page width`);
    assert.equal(await h.section.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true, `${width} section width`);
    const geometry = await h.section.evaluate(node => {
      const style = getComputedStyle(node), paragraph = getComputedStyle(node.querySelector("p"));
      return {font: parseFloat(paragraph.fontSize), line: parseFloat(paragraph.lineHeight), padding: parseFloat(style.paddingTop),
        folded: Boolean(node.closest("details")), rows: [...node.querySelectorAll("li")].map(row => row.getBoundingClientRect().height)};
    });
    assert.ok(geometry.font >= 13 && geometry.font <= 16);
    assert.ok(geometry.line >= geometry.font * 1.5);
    assert.ok(geometry.padding >= 12 && geometry.padding <= 20);
    assert.equal(geometry.folded, false);
    assert.ok(geometry.rows.every(height => height >= 20));
    assert.ok(geometry.rows.every(height => height <= 70), "milestones use compact paragraph spacing");
    await h.page.screenshot({path: `${directory}/preparation-progress-${width}.png`});
  }
  const navigation = h.page.locator("#detail .request-chapter-nav button").first();
  await navigation.focus();
  await h.page.keyboard.press("Enter");
  assert.equal(await navigation.evaluate(node => document.activeElement === node), true, "read-only chapter navigation remains keyboard usable");
  assert.equal(h.progressState.writes, 0);
});
