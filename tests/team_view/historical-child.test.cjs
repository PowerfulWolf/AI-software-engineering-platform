const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function state() {
  const element = () => ({children: [], textContent: "", dataset: {},
    append(...nodes) { this.children.push(...nodes); }, addEventListener() {},
    setAttribute() {}, classList: {toggle() {}}});
  const context = vm.createContext({
    document: {getElementById: element, createElement: element, querySelectorAll: () => []},
    fetch: () => new Promise(() => {}), AbortController,
    setInterval() {}, setTimeout() {}, clearTimeout() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,
    "../../src/ai_software_engineer/team_view/app.js"), "utf8"), context);
  vm.runInContext(`
    snapshot = {selected_project_id: "p", requests: [], tasks: []};
    const request = {id: "delivery_multi_original", project_id: "p", title: "K1",
      stage: "PLANNING", checkpoint_sha256: "current", scopes: [{root: "/repo"}],
      next_action: "继续计划", failed_stages: []};
    const old = {id: "delivery_old", request_id: request.id, title: "K1", project_id: "p",
      status: "BLOCKED", terminal: true, last_activity: "2026-10-01T00:00:00Z",
      blocker: "历史设计被拒绝", next_action: "历史恢复建议", role_queue: []};
    snapshot.requests = [request]; snapshot.tasks = [old];
  `, context);
  return expression => vm.runInContext(expression, context);
}

test("cleared current child scopes retain audit history without a current blocker or task", () => {
  const run = state();
  assert.equal(run("requestTasks(request).length"), 1);
  assert.equal(run("currentRequestTasks(request).length"), 0);
  for (const stage of ["PLANNING", "DELIVERING"]) {
    run(`request.stage = ${JSON.stringify(stage)}`);
    assert.equal(run("terminalBlockedRequestTask(request)"), null);
    assert.doesNotMatch(run("requestPresentation(request).blocker || ''"), /历史/);
    if (stage === "PLANNING")
      assert.equal(run("deliveryFlow(request).children.some(step => step.className === 'blocked')"), false);
  }
  run(`old.terminal = false; old.status = "IMPLEMENTING";
    old.blocker = null; old.role_queue = [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_EXPIRED"}];`);
  assert.equal(run("interruptedRequestTask(request)"), null);
  run('old.role_queue[0].lease_liveness = "LEASE_VALID"');
  assert.equal(run("activeRequestTask(request)"), null);
  run('old.role_queue[0].status = "WAITING_HUMAN"');
  assert.equal(run("waitingRequestTask(request)"), null);
  assert.equal(run("requestTasks(request).length"), 1);
});

test("current source identity selects its newest verifier and excludes an old active child", () => {
  const run = state();
  run(`request.stage = "DELIVERING"; request.scopes[0].delivery_id = "delivery_new";
    old.terminal = false; old.status = "IMPLEMENTING"; old.blocker = null;
    old.last_activity = "2026-10-01T00:04:00Z";
    const current = {...old, id: "delivery_new", terminal: true, status: "DONE",
      last_activity: "2026-10-01T00:01:00Z"};
    const verifier = {...old, id: "verification_new", source_delivery_id: "delivery_new",
      status: "QA", work_kind: "candidate_verification", last_activity: "2026-10-01T00:02:00Z",
      role_queue: [{role: "qa", status: "RUNNING", lease_liveness: "LEASE_VALID"}]};
    snapshot.tasks.push(current, verifier);`);
  assert.equal(run("currentRequestTasks(request).length"), 1);
  assert.equal(run("currentRequestTasks(request)[0].id"), "verification_new");
  assert.equal(run("activeRequestTask(request).id"), "verification_new");
  assert.equal(run("requestTasks(request).length"), 3);
  run(`const standalone = {...request, id: "delivery_standalone", scopes: [{delivery_id: "delivery_standalone"}]};
    snapshot.requests.push(standalone);
    snapshot.tasks.push({...verifier, id: "delivery_standalone", source_delivery_id: null, request_id: standalone.id});`);
  assert.equal(run("currentRequestTasks(standalone).length"), 1);
  assert.equal(run("currentRequestTasks(request)[0].id"), "verification_new");
});
