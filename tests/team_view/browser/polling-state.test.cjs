const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ui, operation } = require("./fixture.cjs");

test("a slow independent Operations read cannot hold updated Requirement text or its preserved document", async t => {
  const h = await ui(t);
  const request = h.team.requests[0];
  request.documents = [{name: "Saved document", source_uri: "artifact://saved",
    sha256: "d".repeat(64), content: "Retained evidence body"}];
  await h.tick();
  await h.requests();
  const document = h.page.locator('details[data-key="artifact://saved"]');
  await document.locator(":scope > summary").click();
  await document.evaluate(node => {window.savedReadDocument = node;});
  let release, started;
  const held = new Promise(resolve => {release = resolve;});
  const reading = new Promise(resolve => {started = resolve;});
  await h.page.route("**/api/v1/operations", async route => {
    started();
    await held;
    return route.fulfill({json: []});
  });
  t.after(() => release());
  request.title = "New Requirement text before history finishes";
  const polling = h.tick();
  await reading;
  await h.page.locator(".request-title-row").getByText(request.title, {exact: true}).waitFor();
  assert.equal(await h.page.evaluate(() => refreshing), true);
  assert.equal(await document.evaluate(node => node === window.savedReadDocument && node.open), true);
  release();
  await polling;
  assert.equal(await h.page.evaluate(() => refreshing), false);
});

test("a transient Operations outage keeps all history visible and disables stale execution authority", async t => {
  const records = Array.from({length: 12}, (_, index) => operation(index === 11 ? "RUNNING" : "SUCCEEDED",
    {operation_id: "operation_saved_" + index, updated_at: `2026-10-09T00:${String(index).padStart(2, "0")}:00Z`}));
  const h = await ui(t, {operations: records});
  await h.requests();
  await h.close();
  const history = h.page.locator('#detail details[data-key="operation-history:project_fixture/request_fixture"]');
  await history.locator(":scope > summary").click();
  assert.equal(await history.locator(".execution-history-entry").count(), records.length);
  await h.page.route("**/api/v1/operations", route => route.fulfill({status: 503,
    json: {error: {message: "fixture operation read unavailable"}}}));
  await h.tick();
  assert.equal(await history.locator(".execution-history-entry").count(), records.length);
  assert.match(await history.innerText(), /上次成功读取的完整历史，不能代表当前执行状态/);
  assert.equal(await h.page.evaluate(() => activeOperation("request_fixture")), undefined);
  assert.equal(await h.page.evaluate(() => canControlCurrentTeam()), false);
  assert.match(await h.page.locator("#connection").innerText(), /操作记录读取失败/);
});

test("unrelated polling preserves Settings inputs, focus and an open help popover", async t => {
  const h = await ui(t);
  await h.page.locator("#nav-settings").click();
  const form = h.page.locator(".settings-form");
  const input = form.getByRole("textbox", {name: "Codex 可执行文件", exact: true});
  await input.fill("/unsaved/codex");
  await form.getByRole("button", {name: "Manager 协调轮次说明"}).click();
  await input.focus();
  await input.evaluate(node => {
    node.setSelectionRange(2, 7);
    window.polledInput = node;
    window.polledSettingsForm = node.closest("form");
  });
  h.team.requests[0].title = "Another background update";
  await h.tick();
  assert.equal(await form.evaluate(node => node === window.polledSettingsForm), true);
  assert.equal(await input.evaluate(node => node === window.polledInput), true);
  assert.equal(await input.inputValue(), "/unsaved/codex");
  assert.deepEqual(await input.evaluate(node => [document.activeElement === node,
    node.selectionStart, node.selectionEnd]), [true, 2, 7]);
  assert.equal(await form.getByRole("dialog", {name: "Manager 协调轮次说明"}).isVisible(), true);
  const saved = await h.page.evaluate(() => structuredClone(settingsSnapshot));
  saved.restart_required = true;
  await h.page.route("**/api/v1/admin/settings", route => route.fulfill({json: saved}));
  await h.tick();
  assert.match(await h.page.locator(".settings-page-title-row").innerText(), /需要重启/);
  assert.equal(await input.evaluate(node => node === window.polledInput), true,
    "saved/process metadata changes must not replace the editable form");
  assert.equal(await input.inputValue(), "/unsaved/codex");
});

test("polling patches changed Requirement facts without collapsing diagnostics or documents", async t => {
  const h = await ui(t, {operations: [operation("SUCCEEDED")]});
  const request = h.team.requests[0];
  request.stage = "DESIGNING";
  request.dialogue = [{speaker: "user", text: "Original discussion"}];
  request.documents = [{name: "Design", source_uri: "artifact://design-one",
    sha256: "b".repeat(64), content: "Verified design body"}];
  let reads = 0;
  await h.page.route("**/operations/operation_fixture/model-calls", route => {
    reads++;
    return route.fulfill({json: []});
  });
  await h.tick();
  await h.requests();
  const detail = h.page.locator("#detail");
  await detail.locator('.request-history-fold[data-key^="discussion-history:"] > summary').click();
  const diagnostics = detail.locator(".model-call-diagnostics");
  await diagnostics.locator("summary").click();
  await diagnostics.getByText(/暂无已完成的阶段调用明细/).waitFor();
  const document = detail.locator('details[data-key="artifact://design-one"]');
  await document.locator(":scope > summary").click();
  await diagnostics.evaluate(node => { window.polledDiagnostics = node; });
  await document.evaluate(node => { window.polledDocument = node; });
  await h.page.locator(".request").evaluate(node => { window.polledRequestCard = node; });
  assert.equal(reads, 1);
  h.team.requests.push({...request, id: "request_other", title: "Another Requirement",
    dialogue: [], documents: []});
  await h.tick();
  assert.equal(await diagnostics.evaluate(node => node === window.polledDiagnostics && node.open), true);
  assert.equal(await document.evaluate(node => node === window.polledDocument && node.open), true);
  assert.equal(await h.page.locator(".request").first().evaluate(node => node === window.polledRequestCard), true);
  request.next_action = "Updated next action";
  await h.tick();
  assert.match(await detail.innerText(), /Updated next action/);
  assert.equal(await diagnostics.evaluate(node => node === window.polledDiagnostics && node.open), true);
  assert.equal(await document.evaluate(node => node === window.polledDocument && node.open), true);
  assert.equal(await diagnostics.getByText(/暂无已完成的阶段调用明细/).isVisible(), true);
  assert.equal(reads, 1, "unchanged diagnostic bodies must not be fetched again");
});

test("timestamp-only ticks do not mutate page content and changed facts retain scroll and text selection", async t => {
  const h = await ui(t);
  const request = h.team.requests[0];
  request.documents = [{name: "Long document", source_uri: "artifact://long",
    sha256: "c".repeat(64), content: "Selected evidence\n" + "Evidence line\n".repeat(120)}];
  await h.tick();
  await h.requests();
  const document = h.page.locator('details[data-key="artifact://long"]');
  await document.locator(":scope > summary").click();
  await h.page.setViewportSize({width: 1440, height: 600});
  await document.locator("pre").evaluate(node => {
    const range = document.createRange();
    range.setStart(node.firstChild, 0);
    range.setEnd(node.firstChild, 17);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    node.style.maxHeight = "120px";
    node.style.overflow = "auto";
    node.scrollTop = 180;
    window.selectedEvidenceNode = node;
    window.scrollTo(0, 400);
    window.polledScroll = {windowY: scrollY, evidenceY: node.scrollTop};
    window.pollMutations = [];
    const observer = new MutationObserver(records => window.pollMutations.push(...records));
    observer.observe(document.getElementById("content"), {childList: true, subtree: true});
    observer.observe(document.getElementById("detail"), {childList: true, subtree: true});
    window.pollObserver = observer;
  });
  h.team.as_of = "2026-10-02T09:00:00Z";
  await h.tick();
  assert.equal(await h.page.evaluate(() => pollMutations.length), 0);
  request.next_action = "New live fact";
  await h.tick();
  assert.match(await h.page.locator("#detail").innerText(), /New live fact/);
  assert.equal(await document.locator("pre").evaluate(node => node === window.selectedEvidenceNode), true);
  assert.deepEqual(await h.page.evaluate(() => ({windowY: scrollY, evidenceY: selectedEvidenceNode.scrollTop})),
    await h.page.evaluate(() => polledScroll));
  assert.equal(await h.page.evaluate(() => getSelection().toString()), "Selected evidence");
});

test("Knowledge polling detects inventory-only changes and retains another expanded Spec", async t => {
  const h = await ui(t);
  const specs = [{active: true, document: {spec_id: "spec_one", spec_key: "one", version: 1,
    title: "First rule", roles: ["coder"], stages: ["IMPLEMENTING"], repository_ids: [],
    path_globs: ["src/**"], verification: "unit tests", body_markdown: "Original rule body"}}];
  await h.page.route("**/api/v1/admin/team/specs", route => route.fulfill({json: specs}));
  await h.page.locator("#nav-knowledge").click();
  await h.page.getByRole("tab", {name: "开发规范", exact: true}).click();
  const document = h.page.locator('details[data-key="spec:team:project_fixture:spec_one"]');
  await document.locator(":scope > summary").click();
  await document.evaluate(node => { window.polledSpec = node; });
  specs.push({active: false, document: {...specs[0].document, spec_id: "spec_two", spec_key: "two",
    title: "New background rule", body_markdown: "Second rule body"}});
  await h.tick();
  await h.page.getByText("New background rule", {exact: true}).waitFor();
  assert.equal(await document.evaluate(node => node === window.polledSpec && node.open), true);
  assert.equal(await document.getByText("Original rule body").isVisible(), true);
});

test("Task updates retain expanded artifacts in the same modal", async t => {
  const h = await ui(t);
  const task = {id: "task_fixture", request_id: "request_fixture", title: "Task", status: "NEW",
    scope: {root: "/fixture", selected_paths: ["."]}, assignments: [], timeline: [], runs: [],
    documents: [{name: "Report", source_uri: "artifact://report", sha256: "d".repeat(64), content: "Task evidence"}]};
  h.team.tasks.push(task);
  await h.tick();
  await h.page.evaluate(() => showDetail("task", "task_fixture"));
  const document = h.page.locator('details[data-key="artifact://report"]');
  await document.locator(":scope > summary").click();
  await document.evaluate(node => { window.polledTaskDocument = node; });
  await h.page.locator(".task-detail-dialog").evaluate(node => { window.polledTaskDialog = node; });
  task.status = "QA";
  await h.tick();
  assert.equal(await h.page.locator(".task-detail-dialog").evaluate(node => node === window.polledTaskDialog), true);
  assert.equal(await document.evaluate(node => node === window.polledTaskDocument && node.open), true);
  assert.equal(await h.page.evaluate(() => snapshot.tasks.find(item => item.id === "task_fixture").status), "QA");
  assert.match(await h.page.locator(".task-detail-dialog").innerText(), /等待工程处理/);
});

test("a new checkpoint removes a stale exact approval instead of reusing its control", async t => {
  const h = await ui(t);
  h.team.requests[0].stage = "WAITING_HUMAN";
  h.state.operations.push(operation("SUCCEEDED", {result: {
    project_id: "project_fixture", delivery_id: "request_fixture", checkpoint_sha256: "a".repeat(64),
    stage: "WAITING_HUMAN", next_action: "Approve exact recovery",
    approval: {kind: "coder_recovery", plan_sha256: "b".repeat(64), title: "批准 Coder 恢复任务", facts: []},
  }}));
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const approve = h.page.locator("#detail").getByRole("button", {name: "批准并继续", exact: true});
  await h.page.getByText("工程管理 · 需工程授权者处理", {exact: true}).click();
  await approve.waitFor();
  await approve.evaluate(node => { window.staleApproval = node; });
  h.team.requests[0].checkpoint_sha256 = "e".repeat(64);
  await h.tick();
  assert.equal(await approve.count(), 0);
  assert.equal(await h.page.evaluate(() => staleApproval.isConnected), false);
  assert.equal(h.state.reads.includes("/api/v1/operations/operation_fixture/model-calls"), false);
});
