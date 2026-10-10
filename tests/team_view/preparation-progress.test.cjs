const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) {this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.textContent = "";}
  append(...nodes) {this.children.push(...nodes);}
  setAttribute() {}
  addEventListener() {}
  set innerHTML(value) {throw new Error("Unsafe HTML: " + value);}
}
const text = node => node.textContent + node.children.map(item => typeof item === "string" ? item : text(item)).join(" ");
const deferred = () => {let resolve, reject; const promise = new Promise((done, fail) => {resolve = done; reject = fail;}); return {promise, resolve, reject};};
function harness() {
  const scope = {operation_id: "operation_" + "1".repeat(32), team_id: "team_test", project_id: "project_test",
    delivery_id: "request_test", expected_checkpoint_sha256: "a".repeat(64), approved_plan_sha256: "e".repeat(64)};
  const request = {id: scope.delivery_id, project_id: scope.project_id, checkpoint_sha256: scope.expected_checkpoint_sha256,
    stage: "BLOCKED", scopes: [], execution: {state: "STOPPED", responsibility: "engineering"}};
  const operation = {operation_id: scope.operation_id, team_id: scope.team_id, status: "RUNNING", updated_at: "2026-10-10T08:00:00Z",
    intent: {action: "CONTINUE_DELIVERY", ...scope}};
  const calls = [], timers = new Map();
  const context = vm.createContext({data: {scope, request, operation}, AbortController, Date,
    document: {createElement: tag => new Element(tag)}, setTimeout: (fn, ms) => {const id = timers.size + 1; timers.set(id, {fn, ms}); return id;},
    clearTimeout: id => timers.delete(id), fetch: async (url, options) => {const value = deferred(); calls.push({url, options, ...value}); return value.promise;}});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  const run = code => vm.runInContext(code, context);
  run(`snapshot = {team_id: data.scope.team_id, selected_project_id: data.scope.project_id,
    requests: [data.request], tasks: [], projects: [], agents: []}; page = "requests";
    selected = {kind: "request", id: data.request.id}; operations = [data.operation]; operationsAvailable = true;
    render = () => {}; consoleAvailable = true; consoleDeliveryReady = true; consoleTeamId = data.scope.team_id;`);
  const record = (kind = "AUTHORIZATION_RECORDED", evidence = {authorization_sha256: "b".repeat(64)}) => ({kind, scope,
    observed_at: "2026-10-10T09:00:00Z", record_sha256: "c".repeat(64), evidence});
  const response = (records = [], overrides = {}) => ({ok: true, status: 200,
    json: async () => ({schema_version: "v0.1", scope, records, ...overrides})});
  return {scope, calls, timers, run, record, response, context};
}

test("preparation reads have a separate serial lane while Team refresh is held", async () => {
  const h = harness();
  h.run('refreshFlight = new Promise(() => {}); teamReadIssue = "busy"');
  const first = h.run("refreshRecoveryPreparationProgress()");
  const second = h.run("refreshRecoveryPreparationProgress()");
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, `/api/v1/operations/${h.scope.operation_id}/preparation-progress`);
  assert.equal(h.calls[0].options.method, undefined);
  assert.equal(h.calls[0].options.cache, "no-store");
  assert.equal([...h.timers.values()][0].ms, 8000);
  h.calls[0].resolve(h.response([h.record()]));
  await Promise.all([first, second]);
  assert.match(text(h.run("recoveryPreparationSection(data.request)")), /恢复授权已核验/);
  assert.equal(h.run("teamReadIssue"), "busy");
  assert.equal(h.run("canControlCurrentTeam()"), false);
  assert.equal(h.timers.size, 0);
});

test("changed Project, selection, Operation or plan rejects a delayed response", async () => {
  for (const change of [
    'snapshot.selected_project_id = "project_other"',
    'selectionIntentRevision++',
    'data.operation.operation_id = "operation_" + "2".repeat(32)',
    'data.operation.intent.approved_plan_sha256 = "f".repeat(64)',
    'selected = null',
  ]) {
    const h = harness();
    const reading = h.run("refreshRecoveryPreparationProgress()");
    h.run(change);
    h.calls[0].resolve(h.response([h.record()]));
    await reading;
    assert.equal(h.run("recoveryPreparationFacts(data.request)?.records.length || 0"), 0, change);
  }
});

test("empty, old-service and invalid observations use fixed Chinese without authority changes", async () => {
  for (const response of [
    h => h.response(),
    () => ({ok: false, status: 404, json: async () => ({error: {message: "private provider secret"}})}),
    h => h.response([h.record("UNKNOWN", {text: "private provider secret"})]),
    h => h.response([h.record()], {scope: {...h.scope, approved_plan_sha256: "f".repeat(64)}}),
  ]) {
    const h = harness(), before = h.run("JSON.stringify([snapshot, operations])");
    const reading = h.run("refreshRecoveryPreparationProgress()");
    h.calls[0].resolve(response(h));
    await reading;
    const shown = text(h.run("recoveryPreparationSection(data.request)"));
    assert.match(shown, /本次操作没有已保存的准备明细|当前服务不提供恢复准备明细|恢复准备明细暂不可读取/);
    assert.doesNotMatch(shown, /private|secret|已完成全部|正在执行/);
    assert.equal(h.run("JSON.stringify([snapshot, operations])"), before);
  }
});

test("a read failure retains same-scope facts and their saved observation time", async () => {
  const h = harness();
  const first = h.run("refreshRecoveryPreparationProgress()");
  h.calls[0].resolve(h.response([h.record()]));
  await first;
  const second = h.run("refreshRecoveryPreparationProgress()");
  h.calls[1].resolve({ok: false, status: 409});
  await second;
  const shown = text(h.run("recoveryPreparationSection(data.request)"));
  assert.match(shown, /恢复授权已核验/);
  assert.match(shown, /上次读取|已保存/);
  assert.equal(h.run("recoveryPreparationFacts(data.request).records.length"), 1);
  assert.equal(h.run("operationsAvailable"), true);
});

test("claim remains a historical fact and reapplication does not claim a patch was applied", async () => {
  const h = harness(), taskId = "task_recovery_" + h.scope.approved_plan_sha256.slice(0, 32);
  const seed = h.record("SEED_VERIFIED", {task_id: taskId, seed_record_sha256: "b".repeat(64), dispatch_sha256: "d".repeat(64), input_mode: "coder_reapply"});
  const claim = h.record("EXECUTION_CLAIMED", {task_id: taskId, work_item_id: "work_test", lease_id: "lease_test", assignment_id: "assignment_test",
    claim_sha256: "b".repeat(64), dispatch_sha256: "d".repeat(64), source_revision: "a".repeat(40), role: "coder", attempt: 1});
  const reading = h.run("refreshRecoveryPreparationProgress()");
  h.calls[0].resolve(h.response([seed, claim]));
  await reading;
  const shown = text(h.run("recoveryPreparationSection(data.request)"));
  assert.match(shown, /旧进度交由开发继续适配/);
  assert.match(shown, /开发执行已领取.*历史记录/);
  assert.doesNotMatch(shown, /改动已载入|正在执行|心跳|100%|已通过/);
  assert.equal(h.run("recoveryPreparationFacts(data.request).records.length"), 2, "missing intermediate milestones are not fabricated");
});

test("parent Task selection uses the same exact recovery scope, unrelated work does not", () => {
  const h = harness();
  h.run('snapshot.tasks = [{id: "task_view", request_id: data.request.id, project_id: data.request.project_id}]; selected = {kind: "task", id: "task_view"}');
  assert.equal(h.run("currentRecoveryPreparationScope().operation_id"), h.scope.operation_id);
  h.run('data.operation.intent.action = "HANDLE_DELIVERY_WAIT"');
  assert.equal(h.run("currentRecoveryPreparationScope()"), null);
});

test("the short deadline covers a stalled JSON body and releases the lane without retrying delivery", async () => {
  const h = harness(), body = deferred(), started = deferred();
  const reading = h.run("refreshRecoveryPreparationProgress()");
  h.calls[0].resolve({ok: true, status: 200, json: () => {started.resolve(); return body.promise;}});
  await started.promise;
  [...h.timers.values()][0].fn();
  assert.equal(h.calls[0].options.signal.aborted, true);
  body.reject(new Error("private provider secret"));
  await reading;
  assert.equal(h.run("recoveryPreparationFlight"), null);
  assert.equal(h.calls.length, 1);
  assert.match(text(h.run("recoveryPreparationSection(data.request)")), /暂不可读取.*自动重试/);
  assert.equal(h.timers.size, 0);
});

test("a delayed JSON body cannot publish after the user switches Project", async () => {
  const h = harness(), body = deferred(), started = deferred();
  const reading = h.run("refreshRecoveryPreparationProgress()");
  h.calls[0].resolve({ok: true, status: 200, json: () => {started.resolve(); return body.promise;}});
  await started.promise;
  h.run('requestedProjectId = "project_other"; selectionIntentRevision++; syncRecoveryPreparationTarget()');
  assert.equal(h.calls[0].options.signal.aborted, true);
  body.resolve({schema_version: "v0.1", scope: h.scope, records: [h.record()]});
  await reading;
  assert.equal(h.run("recoveryPreparationObservation"), null);
});

test("unchanged rereads retain display signatures while missing or malformed evidence retains saved facts", async () => {
  const h = harness();
  const initial = h.run("refreshRecoveryPreparationProgress()");
  h.calls[0].resolve(h.response([h.record()])); await initial;
  const signature = h.run("JSON.stringify(recoveryPreparationDisplayFacts())");
  const reread = h.run("refreshRecoveryPreparationProgress()");
  h.calls[1].resolve(h.response([h.record()])); await reread;
  assert.equal(h.run("JSON.stringify(recoveryPreparationDisplayFacts())"), signature);
  const changed = h.run("refreshRecoveryPreparationProgress()");
  h.calls[2].resolve(h.response([])); await changed;
  assert.equal(h.run("recoveryPreparationFacts(data.request).records.length"), 1);
  for (const invalid of [
    h.record("DISPATCH_COMMITTED", {task_id: "task_recovery_" + h.scope.approved_plan_sha256.slice(0, 32),
      dispatch_id: "dispatch_commit_" + "f".repeat(64), dispatch_sha256: "b".repeat(64), task_record_sha256: "b".repeat(64)}),
    {...h.record(), observed_at: "2026-10-10T09:00:00"},
    h.record("AUTHORIZATION_RECORDED", {authorization_sha256: ["b".repeat(64)]}),
    h.record("EXECUTION_CLAIMED", {task_id: "task_recovery_" + h.scope.approved_plan_sha256.slice(0, 32), work_item_id: "", lease_id: "lease_", assignment_id: "assignment_",
      claim_sha256: "b".repeat(64), dispatch_sha256: "d".repeat(64), source_revision: "a".repeat(40), role: "coder", attempt: 1}),
  ]) {
    assert.throws(() => h.run(`verifiedPreparationRecords(${JSON.stringify({schema_version: "v0.1", scope: h.scope, records: [invalid]})}, data.scope)`), /invalid preparation/);
  }
});

test("full 64-character Git revisions are accepted and latest means actual observation time", async () => {
  const h = harness(), taskId = "task_recovery_" + h.scope.approved_plan_sha256.slice(0, 32);
  const sealed = {...h.record("TASK_SEALED", {task_id: taskId, task_record_sha256: "b".repeat(64), source_revision: "a".repeat(64)}),
    observed_at: "2026-10-10T09:30:00+02:00"};
  const claim = {...h.record("EXECUTION_CLAIMED", {task_id: taskId, work_item_id: "work_test", lease_id: "lease_test", assignment_id: "assignment_test",
    claim_sha256: "b".repeat(64), dispatch_sha256: "d".repeat(64), source_revision: "a".repeat(64), role: "coder", attempt: 1}),
    observed_at: "2026-10-10T08:00:00Z"};
  const reading = h.run("refreshRecoveryPreparationProgress()");
  h.calls[0].resolve(h.response([sealed, claim]));
  await reading;
  assert.equal(h.run("recoveryPreparationFacts(data.request).records.length"), 2);
  assert.match(h.run("preparationLatestSummary(data.request)"), /开发执行已领取/);
});
