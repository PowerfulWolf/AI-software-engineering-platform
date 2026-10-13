const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  const context = vm.createContext({document: {}});
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  vm.runInContext(`snapshot = {tasks: [{id: "current", task_id: "task_current", request_id: "requirement",
    status: "IMPLEMENTING", terminal: false, task_revision: 2, task_intent_sha256: "a".repeat(64),
    role_queue: [{work_item_id: "work_current", role: "coder", status: "WAITING_DEPENDENCY",
      lease_liveness: "LEASE_RELEASED", wait_disposition: {responsibility: "engineering", facts: {
        task_id: "task_current", work_item_id: "work_current", role: "coder", checkpoint_sequence: 2,
        task_intent_sha256: "a".repeat(64), source_revision: "b".repeat(40)}}}]}],
    requests: [{id: "requirement", stage: "DELIVERING"}]};`, context);
  return {run: code => vm.runInContext(code, context), source};
}

test("stopped engineering wait offers close and retains terminal history", () => {
  const h = harness();
  h.run('snapshot.tasks.push({id: "historical", request_id: "requirement", terminal: true, status: "BLOCKED", role_queue: [{status: "CLOSED"}]})');
  assert.equal(h.run('canCloseRequirement(snapshot.requests[0])'), true);
  assert.match(h.source, /if \(canCloseRequirement\(item\)\)[\s\S]*?"关闭需求"/);
  assert.match(h.source, /核验工程执行已停止/);
});

for (const change of [
  'snapshot.tasks[0].role_queue[0].status = "READY"',
  'snapshot.tasks[0].role_queue[0].status = "RETRY_SCHEDULED"',
  'snapshot.tasks[0].role_queue[0].status = "RUNNING"',
  'snapshot.tasks[0].role_queue[0].lease_liveness = "LEASE_VALID"',
  'snapshot.tasks[0].role_queue[0].wait_disposition = null',
  'snapshot.tasks[0].role_queue[0].wait_disposition.responsibility = "product"',
  'snapshot.tasks[0].task_revision++',
  'snapshot.tasks[0].task_intent_sha256 = "c".repeat(64)',
  'snapshot.tasks[0].role_queue[0].role = "reviewer"',
  'snapshot.tasks[0].role_queue = []',
  'snapshot.tasks.push({id: "old", request_id: "requirement", terminal: false, role_queue: [{status: "RETRY_SCHEDULED"}]})',
]) test(`unverified or active delivery hides close: ${change}`, () => {
  const h = harness();
  h.run(change);
  assert.equal(h.run('canCloseRequirement(snapshot.requests[0])'), false);
});

test("blocked and idle product drafts offer close while active engineering stages remain guarded", () => {
  const h = harness();
  h.run('snapshot.requests[0].stage = "BLOCKED"; snapshot.tasks = []');
  assert.equal(h.run('canCloseRequirement(snapshot.requests[0])'), true);
  for (const stage of ["READY_FOR_DISCUSSION", "WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL"]) {
    h.run(`snapshot.requests[0].stage = ${JSON.stringify(stage)}`);
    assert.equal(h.run('canCloseRequirement(snapshot.requests[0])'), true);
  }
  for (const stage of ["DESIGNING", "PLANNING", "DONE", "CLOSED"]) {
    h.run(`snapshot.requests[0].stage = ${JSON.stringify(stage)}`);
    assert.equal(h.run('canCloseRequirement(snapshot.requests[0])'), false);
  }
});
