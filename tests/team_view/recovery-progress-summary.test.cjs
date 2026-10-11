const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
    this.textContent = ""; this.listeners = new Map(); this.className = "";
  }
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children = nodes;}
  setAttribute() {}
  addEventListener(event, handler) {this.listeners.set(event, handler);}
  set innerHTML(value) {throw new Error("Unsafe HTML: " + value);}
}
const digest = digit => digit.repeat(64);
const descend = node => [node, ...node.children.filter(child => typeof child !== "string").flatMap(descend)];
const text = node => node.textContent + node.children.map(child => typeof child === "string" ? child : text(child)).join(" ");
const rowFor = (panel, title) => descend(panel).find(node => node.tagName === "LI" && text(node).includes(title));

function harness({deliveryReady = true, resultStage = "BLOCKED", withApproval = true} = {}) {
  const scope = {operation_id: "operation_" + "1".repeat(32), team_id: "team_current",
    project_id: "project_current", delivery_id: "request_current",
    expected_checkpoint_sha256: digest("b"), approved_plan_sha256: digest("e")};
  const request = {id: scope.delivery_id, project_id: scope.project_id, checkpoint_sha256: scope.expected_checkpoint_sha256,
    stage: "BLOCKED", scopes: [{delivery_id: "task_original"}], documents: [],
    blocker: "原开发执行已停止，完整进度保留。", execution: {state: "STOPPED", responsibility: "engineering",
      reason: "原开发执行已停止，完整进度保留。", next_action: "查看保留进度的方案。"}};
  const active = {operation_id: scope.operation_id, team_id: scope.team_id, project_id: scope.project_id,
    delivery_id: scope.delivery_id, action: "CONTINUE_DELIVERY", status: "RUNNING", sequence: 2,
    requested_at: "2026-10-12T00:20:00Z", updated_at: "2026-10-12T00:20:01Z", operation_sha256: digest("a"),
    has_details: true, intent_checkpoint_sha256: scope.expected_checkpoint_sha256,
    submitted_approval_kind: "plan", submitted_approval_sha256: scope.approved_plan_sha256};
  const previous = {...active, operation_id: "operation_" + "2".repeat(32), status: "SUCCEEDED", sequence: 3,
    requested_at: "2026-10-12T00:10:00Z", updated_at: "2026-10-12T00:11:00Z", operation_sha256: digest("c"),
    submitted_approval_kind: null, submitted_approval_sha256: null, result_stage: resultStage,
    result_checkpoint_sha256: scope.expected_checkpoint_sha256,
    approval_kind: withApproval ? "coder_recovery" : null, approval_plan_sha256: withApproval ? scope.approved_plan_sha256 : null};
  const full = source => ({...source, intent: {action: source.action, project_id: source.project_id,
    delivery_id: source.delivery_id, expected_checkpoint_sha256: source.intent_checkpoint_sha256,
    ...(source === active ? {approved_plan_sha256: scope.approved_plan_sha256} : {})},
    result: source === active ? null : {delivery_id: scope.delivery_id, checkpoint_sha256: scope.expected_checkpoint_sha256,
      stage: resultStage, ...(withApproval ? {approval: {kind: "coder_recovery", title: "保留进度继续原需求",
        plan_sha256: scope.approved_plan_sha256, facts: ["完整进度已保留"]}} : {})}});
  const model = {manifest: {schema_version: "v0.2", team_id: scope.team_id, delivery_ready: deliveryReady,
    operation_contract_version: 6, supported_actions: ["CONTINUE_DELIVERY"], operation_summary_contract_version: "v0.1"},
    items: [active, previous], active: [active], full: new Map([[active.operation_id, full(active)], [previous.operation_id, full(previous)]]),
    inventory: digest("f"), records: [{kind: "TASK_SEALED", scope, observed_at: "2026-10-12T00:21:00Z", record_sha256: digest("d"),
      evidence: {task_id: "task_recovery_" + scope.approved_plan_sha256.slice(0, 32), task_record_sha256: digest("c"),
        source_revision: "a".repeat(40)}}]};
  const calls = [], timers = new Map();
  const context = vm.createContext({data: {scope, request}, TextEncoder, URLSearchParams, AbortController, Date,
    document: {createElement: tag => new Element(tag)}, setTimeout: (fn, ms) => {const id = timers.size + 1; timers.set(id, {fn, ms}); return id;},
    clearTimeout: id => timers.delete(id), fetch: async (url, options) => {
      calls.push({url, options});
      let body;
      if (url === "/api/v1/console") body = model.manifest;
      else if (url.startsWith("/api/v1/operation-summaries?")) {
        const query = new URLSearchParams(url.split("?")[1]);
        body = {schema_version: "v0.1", team_id: scope.team_id,
          scope: {project_id: query.get("project_id"), delivery_id: query.get("delivery_id")},
          inventory_sha256: model.inventory, items: model.items, total_count: model.items.length,
          active: model.active, active_complete: true, next_cursor: null};
      } else if (url.endsWith("/preparation-progress")) body = {schema_version: "v0.1", scope, records: model.records};
      else if (url.startsWith("/api/v1/operations/")) body = model.full.get(url.split("/").at(-1));
      else throw new Error("Unexpected HTTP route: " + url);
      return {ok: true, status: 200, headers: {get: () => '"summary"'}, json: async () => body};
    }});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  vm.runInContext(source.slice(source.indexOf("async function refreshConsoleInfo("), source.indexOf("async function refreshSettingsSnapshot(")), context);
  const run = expression => vm.runInContext(expression, context);
  run(`snapshot = {team_id: data.scope.team_id, selected_project_id: data.scope.project_id,
    projects: [], agents: [], requests: [data.request], tasks: [{id: "task_original", request_id: data.request.id,
      project_id: data.request.project_id, status: "BLOCKED", terminal: true, blocker: data.request.blocker,
      last_activity: "2026-10-12T00:00:00Z", role_queue: []}]}; page = "requests";
    selected = {kind: "request", id: data.request.id}; render = () => {};`);
  const render = () => run('(() => {const panel = el("section"); requestOperationHistory(panel, data.request); return panel;})()');
  const read = async () => {await run("refreshOperations()"); await run("refreshRecoveryPreparationProgress()");};
  return {scope, request, active, previous, model, calls, timers, context, run, render, read};
}

test("summary-mode public reads render current recovery and latest saved preparation without changing facts", async () => {
  const h = harness(); await h.read();
  const original = h.run("JSON.stringify([snapshot, operations])"), panel = h.render();
  const row = rowFor(panel, "本次恢复请求");
  assert.ok(row, "current preparation must appear through the shipped request history entry");
  assert.equal(row.children[0].textContent, "当前阶段 · 恢复准备 · 平台正在处理恢复");
  assert.match(text(row), /发起操作 · 继续交付/);
  assert.match(text(row), /最近准备记录 · 恢复任务输入已封存/);
  assert.doesNotMatch(row.children[0].textContent, /已阻塞|执行中/);
  assert.equal(h.run("JSON.stringify([snapshot, operations])"), original);
  assert.equal(h.calls.some(call => call.url === "/api/v1/operations" || call.options?.method === "POST"), false);
});

test("summary SUCCEEDED shows neutral command completion and the sealed delivery outcome", async () => {
  const h = harness(); await h.read();
  const panel = h.render(), row = rowFor(panel, "操作已结束 · 当次交付已阻塞");
  assert.ok(row, "BLOCKED result_stage must not disappear behind command SUCCEEDED");
  const badge = descend(row).find(node => node.textContent === "命令已完成");
  assert.ok(badge); assert.equal(badge.className, "badge");
  assert.doesNotMatch(text(row), /执行成功|需求已交付|当前阶段/);
});

for (const unavailable of ["runtime", "detail"]) {
  test(`exact recovery reading remains current while the ${unavailable} write gate is unavailable`, async () => {
    const h = harness({deliveryReady: unavailable !== "runtime"}); await h.read();
    if (unavailable === "detail") h.run("operationDetailReadyScope = null");
    assert.equal(h.run("teamReadIssue"), null);
    assert.equal(h.run("canControlCurrentTeam()"), false);
    assert.equal(h.run("requestNodeExecution(data.request).label"), "平台正在处理恢复");
    assert.equal(h.run("requestPresentation(data.request).group"), "active");
    assert.equal(h.run("requestNodeBadge(data.request).textContent"), "平台正在处理恢复");
    assert.equal(h.run("requestRecoveryDecision(data.request)"), null);
    assert.equal(h.run("canControlCurrentTeam()"), false, "reading cannot restore write authority");
  });
}

test("summary progress signatures follow actual successor roles and new waiting or failure facts", async () => {
  const h = harness(); await h.read();
  let priorSignature;
  for (const [status, role, phase] of [["IMPLEMENTING", "coder", "实现"], ["QA", "qa", "测试"], ["REVIEW", "reviewer", "评审"]]) {
    h.context.update = {status, role};
    h.run(`snapshot.tasks = [{id: "task_successor", source_delivery_id: "task_original", request_id: data.request.id, project_id: data.request.project_id,
      status: update.status, terminal: false, blocker: null, last_activity: "2026-10-12T00:22:00Z",
      execution: {state: "RUNNING", responsibility: "team", reason_code: "ROLE_RUNNING"},
      role_queue: [{role: update.role, status: "RUNNING", lease_liveness: "LEASE_VALID"}]}];`);
    const row = rowFor(h.render(), "当前阶段");
    assert.ok(row); assert.equal(row.children[0].textContent, `当前阶段 · ${phase} · 执行中`);
    h.context.row = row;
    const signature = h.run("renderedBlocks.get(row).signature");
    assert.notEqual(signature, priorSignature); priorSignature = signature;
  }
  h.run('snapshot.tasks[0].terminal = true; snapshot.tasks[0].status = "BLOCKED"; snapshot.tasks[0].blocker = "本轮验证发现新的问题。"');
  assert.match(text(rowFor(h.render(), "当前阶段")), /本轮验证发现新的问题/);
  assert.doesNotMatch(text(rowFor(h.render(), "当前阶段")), /恢复准备/);
  h.run('snapshot.tasks[0].terminal = false; snapshot.tasks[0].status = "IMPLEMENTING"; snapshot.tasks[0].execution = {state: "WAITING", responsibility: "engineering", reason: "本轮等待工程决定。"}; snapshot.tasks[0].role_queue = [{role: "coder", status: "WAITING_HUMAN"}]');
  assert.equal(h.run("requestNodeExecution(data.request).state"), "blocked");
  assert.doesNotMatch(text(rowFor(h.render(), "当前阶段")), /恢复准备/);
  h.run('snapshot.tasks[0].blocker = null; snapshot.tasks[0].execution = {state: "RUNNING", responsibility: "team"}; snapshot.tasks[0].role_queue = [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_EXPIRED"}]');
  assert.equal(h.run("requestNodeExecution(data.request).status"), "EXECUTION_INTERRUPTED");
  assert.doesNotMatch(text(rowFor(h.render(), "当前阶段")), /恢复准备|平台正在处理恢复/);
});

test("untrusted, unavailable, mismatched and foreign recovery facts never mask STOPPED", async () => {
  for (const change of [
    'operationsAvailable = false',
    'operations = operations.filter(item => item.status !== "SUCCEEDED")',
    'operations.find(item => item.status === "RUNNING").intent.approved_plan_sha256 = "f".repeat(64)',
    'data.request.checkpoint_sha256 = "f".repeat(64)',
    'consoleTeamId = "team_other"',
    'requestedProjectId = "project_other"',
    'snapshot.selected_project_id = "project_other"',
  ]) {
    const h = harness({deliveryReady: false}); await h.read(); h.run(change);
    assert.equal(h.run("requestNodeExecution(data.request).platformProcessing || false"), false, change);
    assert.equal(h.run("canControlCurrentTeam()"), false, change);
  }
  const h = harness({deliveryReady: false}); await h.read();
  h.model.previous = {...h.previous, operation_sha256: digest("d")};
  h.model.items = [h.active, h.model.previous]; h.model.inventory = digest("9");
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  await h.run('readOperationSummaryPage("project_current", null)');
  assert.equal(h.run("requestNodeExecution(data.request).platformProcessing || false"), false,
    "a stale full approval with a changed summary digest cannot establish current recovery");
});

test("summary-only RUNNING and UNKNOWN execution do not fabricate a role or recovery", async () => {
  const h = harness({deliveryReady: false, withApproval: false}); await h.read();
  h.run('operations = []; operationDetailCache.clear(); data.request.execution = {state: "UNKNOWN", responsibility: "engineering"}');
  const node = h.run("requestNodeExecution(data.request)");
  assert.equal(node.state, "blocked"); assert.equal(node.platformProcessing, undefined);
  assert.equal(node.label, "等待工程处理");
  assert.equal(h.run("canControlCurrentTeam()"), false);
});

test("sealed summary stages stay historical and only DONE states that the requirement was delivered", async () => {
  for (const [stage, expected] of [["WAITING_HUMAN", "当次交付等待处理"], ["DONE", "当次需求已交付"],
    ["CLOSED", "当次需求已关闭"], ["PLANNING", "当次停留阶段 · 计划编排"]]) {
    const h = harness({resultStage: stage, withApproval: false}); await h.read();
    const row = rowFor(h.render(), "操作已结束 · " + expected);
    assert.ok(row, stage); assert.doesNotMatch(text(row), /当前阶段|执行成功/);
    if (stage !== "DONE") assert.doesNotMatch(text(row), /需求已交付/);
  }
});

test("retained or drifted history rows never attach current recovery to their old RUNNING source", async () => {
  const h = harness(); await h.read(); h.render();
  h.model.items = [{...h.active, operation_sha256: digest("7"), sequence: 3}, h.previous];
  h.model.active = [h.model.items[0]]; h.model.inventory = digest("8");
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  const panel = h.render();
  assert.match(text(panel), /记录已有更新，当前页保留供阅读/);
  assert.doesNotMatch(text(panel), /当前阶段|最近准备记录|平台正在处理恢复/);
  h.run('operationHistoryPage("project_current", "request_current").changed = false');
  assert.doesNotMatch(text(h.render()), /当前阶段|最近准备记录|平台正在处理恢复/,
    "a digest-drifted row cannot be considered current even without the retained-page notice");
  assert.equal(h.run("canControlCurrentTeam()"), false);
});

test("a single fresh scope cannot be overridden by another cached scope's conflicting recovery summary", async () => {
  for (const order of ["project-first", "requirement-first"]) {
    for (const changedScope of ["project", "requirement"]) {
      for (const [which, changes] of [
        ["active", {status: "SUCCEEDED", sequence: 3, operation_sha256: digest("7"), result_stage: "BLOCKED"}],
        ["active", {sequence: 3}],
        ["active", {operation_sha256: digest("7")}],
        ["prepared", {operation_sha256: digest("7")}],
      ]) {
        const h = harness({deliveryReady: false});
        if (order === "requirement-first") {
          await h.run("refreshConsoleInfo()");
          await h.run('readOperationSummaryPage("project_current", "request_current")');
        }
        await h.read();
        assert.equal(h.run("requestNodeExecution(data.request).platformProcessing"), true);
        const changed = {...(which === "active" ? h.active : h.previous), ...changes};
        h.model.items = which === "active" ? [changed, h.previous] : [h.active, changed];
        h.model.active = which === "active" && changed.status !== "RUNNING" ? [] : [which === "active" ? changed : h.active];
        h.model.inventory = digest("8");
        await h.run(`readOperationSummaryPage("project_current", ${changedScope === "project" ? "null" : '"request_current"'})`);
        assert.equal(h.run("requestNodeExecution(data.request).platformProcessing || false"), false,
          `${order}/${changedScope}/${which}/${Object.keys(changes).join(",")}`);
        assert.equal(h.run("canControlCurrentTeam()"), false);
        assert.equal(h.calls.some(call => call.options?.method === "POST"), false);
        h.model.items = [h.active, h.previous]; h.model.active = [h.active]; h.model.inventory = digest("9");
        await h.run('readOperationSummaryPage("project_current", null)');
        await h.run('readOperationSummaryPage("project_current", "request_current")');
        assert.equal(h.run("requestNodeExecution(data.request).platformProcessing"), true,
          "matching fresh scopes restore reading, not the runtime write gate");
        assert.equal(h.run("canControlCurrentTeam()"), false);
      }
    }
  }
});

test("conflicting items and active locators within one verified page cannot establish recovery", async () => {
  const h = harness({deliveryReady: false}); await h.read();
  h.model.items = [{...h.active, status: "SUCCEEDED", sequence: 3, operation_sha256: digest("7"), result_stage: "BLOCKED"}, h.previous];
  h.model.active = [h.active]; h.model.inventory = digest("8");
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  assert.equal(h.run("requestNodeExecution(data.request).platformProcessing || false"), false);
  assert.equal(h.run("canControlCurrentTeam()"), false);
  h.model.items = [h.active, h.previous]; h.model.inventory = digest("9");
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  assert.equal(h.run("requestNodeExecution(data.request).platformProcessing"), true);
  assert.equal(h.run("canControlCurrentTeam()"), false);
});

for (const ready of [true, false]) {
  test(`conflicting active summaries refuse recovery presentation while controls are ${ready ? "available" : "unavailable"}`, async () => {
    const h = harness({deliveryReady: ready}); await h.read();
    h.run("selected = null"); // The Request list has no exact detail gate; this is ordinary readable list state.
    assert.equal(h.run("canControlCurrentTeam()"), ready);
    h.model.items = [{...h.active, status: "SUCCEEDED", sequence: 3, operation_sha256: digest("7"), result_stage: "BLOCKED"}, h.previous];
    h.model.active = []; h.model.inventory = digest("8");
    await h.run('readOperationSummaryPage("project_current", null)');
    assert.equal(h.run("canControlCurrentTeam()"), ready, "presentation checks never change control policy");
    assert.equal(h.run("requestNodeExecution(data.request).platformProcessing || false"), false);
    assert.equal(h.calls.some(call => call.options?.method === "POST"), false);
  });
}

test("consistent ordinary Continue presentation does not require a new approved-plan field", async () => {
  const h = harness({withApproval: false});
  delete h.model.full.get(h.active.operation_id).intent.approved_plan_sha256;
  h.active.submitted_approval_kind = null; h.active.submitted_approval_sha256 = null;
  await h.read();
  assert.equal(h.run("canControlCurrentTeam()"), true);
  assert.equal(h.run("requestNodeExecution(data.request).platformProcessing"), true);
  assert.equal(h.calls.some(call => call.options?.method === "POST"), false);
});

test("a newer Team-wide summary cannot be hidden by cached Project recovery pages", async () => {
  const h = harness({deliveryReady: false});
  await h.run("refreshConsoleInfo()");
  await h.run("readOperationSummaryPage(null, null)");
  await h.read();
  assert.equal(h.run("requestNodeExecution(data.request).platformProcessing"), true);
  h.model.items = [{...h.active, status: "SUCCEEDED", sequence: 3, operation_sha256: digest("7"), result_stage: "BLOCKED"}, h.previous];
  h.model.active = []; h.model.inventory = digest("8");
  await h.run("readOperationSummaryPage(null, null)");
  assert.equal(h.run("requestNodeExecution(data.request).platformProcessing || false"), false);
  assert.equal(h.run("canControlCurrentTeam()"), false);
});
