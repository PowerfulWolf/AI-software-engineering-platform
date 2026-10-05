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
    const request = {id: "r", project_id: "p", stage: "DELIVERING",
      checkpoint_sha256: "current", next_action: "Continue", failed_stages: [],
      coordination: {draft: {action: "PROPOSE_RECOVERY", summary: "old blocker"}}};
    const task = {id: "t", request_id: "r", status: "IMPLEMENTING", terminal: false,
      last_activity: "2026-10-01T00:00:00Z", next_action: "Continue",
      role_queue: [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID"}]};
    snapshot.requests = [request]; snapshot.tasks = [task];
  `, context);
  return expression => vm.runInContext(expression, context);
}

test("current recovery and terminal delivery do not show historical Manager approval", () => {
  const run = state();
  for (const status of ["IMPLEMENTING", "QA", "REVIEW"]) {
    run(`task.status = ${JSON.stringify(status)}`);
    assert.equal(run("requestPresentation(request).group"), "active");
    assert.equal(run("managerFlowStatus(request)"), null);
  }
  for (const stage of ["DONE", "CLOSED"]) {
    run(`request.stage = ${JSON.stringify(stage)}; snapshot.tasks = []`);
    assert.equal(run("managerFlowStatus(request)"), null);
  }
});

test("expired current lease interrupts presentation without changing delivery checkpoint", () => {
  const run = state();
  run('task.role_queue[0].lease_liveness = "LEASE_EXPIRED"');
  assert.equal(run("taskGroup(task)"), "blocked");
  assert.equal(run("requestPresentation(request).group"), "blocked");
  assert.match(run("requestPresentation(request).blocker"), /租约.*失效|租约.*过期/);
  assert.doesNotMatch(run("managerFlowStatus(request).textContent"), /等待恢复审批|old blocker/);
  assert.equal(run("task.status"), "IMPLEMENTING");
  run('task.role_queue[0].status = "CLOSED"; task.status = "DONE"; task.terminal = true');
  assert.equal(run("taskGroup(task)"), "completed");
});

test("Manager proposal alone is not an outstanding exact approval", () => {
  const run = state();
  run('snapshot.tasks = []; request.stage = "BLOCKED"');
  assert.doesNotMatch(run("managerFlowStatus(request).textContent"), /等待恢复审批/);
  assert.match(run("managerFlowStatus(request).textContent"), /等待恢复/);
});

test("expired lease remains interrupted while a Manager operation is still running", () => {
  const run = state();
  run(`task.role_queue[0].lease_liveness = "LEASE_EXPIRED";
    operations = [{status: "RUNNING", updated_at: "2026-10-01T00:01:00Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r"}}];
    task.assignments = [{role: "coder", current_stage: false}, {role: "qa", current_stage: false}];`);
  assert.equal(run("requestPresentation(request).status"), "EXECUTION_INTERRUPTED");
  assert.match(run("managerFlowStatus(request).textContent"), /处理中.*执行已中断/);
  assert.match(run("assignmentBadge(task, task.assignments[0]).textContent"), /执行中断/);
  assert.doesNotMatch(run("assignmentBadge(task, task.assignments[1]).textContent"), /执行中断/);
  run('task.role_queue[0].lease_liveness = "LEASE_VALID"');
  assert.equal(run("requestPresentation(request).group"), "active");
});

test("only current unconsumed exact approval is shown as awaiting approval", () => {
  const run = state();
  run(`snapshot.tasks = []; request.stage = "BLOCKED";
    const proposal = {status: "SUCCEEDED", updated_at: "2026-10-01T00:01:00Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r"},
      result: {delivery_id: "r", checkpoint_sha256: "current",
        approval: {kind: "coder_scope", title: "新增文件范围", plan_sha256: "exact"}}};
    operations = [proposal];`);
  assert.match(run("managerFlowStatus(request).textContent"), /等待审批.*新增文件范围/);
  run('proposal.result.checkpoint_sha256 = "old"');
  assert.doesNotMatch(run("managerFlowStatus(request).textContent"), /等待审批/);
  run(`proposal.result.checkpoint_sha256 = "current";
    operations.push({status: "FAILED", updated_at: "2026-10-01T00:02:00Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r", approved_scope_sha256: "exact"}});`);
  assert.doesNotMatch(run("managerFlowStatus(request).textContent"), /等待审批/);
});

test("current knowledge wait is not replaced by historical execution interruption", () => {
  const run = state();
  run(`request.stage = "WAITING_HUMAN"; request.knowledge_gap = {is_current: true};
    task.role_queue[0].lease_liveness = "LEASE_EXPIRED";`);
  assert.equal(run("interruptedRequestTask(request)"), null);
  assert.equal(run("requestPresentation(request).status"), "WAITING_HUMAN");
});

test("current Coder knowledge wait shows scheduling wait and preserves its checkpoint", () => {
  const run = state();
  run(`request.stage = "WAITING_HUMAN";
    request.knowledge_gap = {is_current: true};
    task.role_queue[0] = {role: "coder", status: "WAITING_HUMAN",
      lease_liveness: "UNKNOWN", wait_reason: "KNOWLEDGE_GAP:gap:route"};
    task.assignments = [{role: "coder", current_stage: false}];`);
  assert.equal(run("taskPresentationStatus(task)"), "WAITING_HUMAN");
  assert.equal(run("taskGroup(task)"), "blocked");
  assert.match(run("assignmentBadge(task, task.assignments[0]).textContent"), /等待人工/);
  assert.match(run("managerFlowStatus(request).textContent"), /等待知识确认/);
  assert.doesNotMatch(run("managerFlowStatus(request).textContent"), /old blocker|恢复审批/);
  run('request.knowledge_gap.resolution = {resolution_id: "approved"}');
  assert.match(run("managerFlowStatus(request).textContent"), /知识解答已批准.*等待继续/);
  assert.equal(run("task.status"), "IMPLEMENTING");
  run('task.status = "DONE"; task.terminal = true');
  assert.equal(run("taskPresentationStatus(task)"), "DONE");
});

test("Continue operation cannot mask a durable role wait or animate the blocked flow step", () => {
  const run = state();
  run(`request.stage = "WAITING_HUMAN"; request.coordination = null;
    request.knowledge_wait_stage = "DELIVERING";
    request.scopes = [{delivery_id: "t"}];
    request.knowledge_gap = {is_current: true};
    task.role_queue[0] = {role: "coder", status: "WAITING_HUMAN",
      lease_liveness: "UNKNOWN", wait_reason: "KNOWLEDGE_GAP:gap:route"};
    operations = [{status: "RUNNING", updated_at: "2026-10-01T00:01:00Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r"}}];`);
  assert.equal(run("requestPresentation(request).group"), "blocked");
  assert.equal(run("requestPresentation(request).status"), "WAITING_HUMAN");
  assert.match(run("managerFlowStatus(request).textContent"), /处理中.*等待知识确认/);
  assert.equal(run("deliveryFlow(request).children[3].className"), "blocked");
  assert.match(run("deliveryFlow(request).children[3].children[2].textContent"), /已阻塞/);
  run('task.role_queue[0].role = "qa"; task.status = "QA"; operations = []');
  assert.equal(run("deliveryFlow(request).children[4].className"), "blocked");
  assert.equal(run("deliveryFlow(request).children[5].className || ''"), "");
});

test("reaped lease keeps interruption and exact approval visible until a new claim", () => {
  const run = state();
  run(`task.role_queue[0] = {role: "coder", status: "RETRY_SCHEDULED",
    lease_liveness: "LEASE_EXPIRED", wait_reason: "lease_expired:lease_old"};`);
  assert.equal(run("requestPresentation(request).status"), "EXECUTION_INTERRUPTED");
  assert.match(run("managerFlowStatus(request).textContent"), /执行中断.*等待恢复/);
  run(`operations = [{status: "SUCCEEDED", updated_at: "2026-10-01T00:01:00Z",
    intent: {action: "CONTINUE_DELIVERY", delivery_id: "r"},
    result: {delivery_id: "r", checkpoint_sha256: "current",
      approval: {kind: "coder_interruption", title: "批准中断后的单次 Coder 续跑", plan_sha256: "exact"}}}];`);
  assert.match(run("managerFlowStatus(request).textContent"), /等待审批.*单次 Coder 续跑/);
  run(`operations.push({status: "RUNNING", updated_at: "2026-10-01T00:02:00Z",
    intent: {action: "CONTINUE_DELIVERY", delivery_id: "r", approved_plan_sha256: "exact"}});`);
  assert.equal(run("requestPresentation(request).status"), "EXECUTION_INTERRUPTED");
  assert.match(run("managerFlowStatus(request).textContent"), /处理中.*执行已中断/);
  run('task.role_queue[0] = {role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID"}');
  assert.equal(run("requestPresentation(request).group"), "active");
  assert.doesNotMatch(run("managerFlowStatus(request).textContent"), /执行已中断|等待审批/);
});

test("ordinary provider retry and closed expired claims are not interrupted execution", () => {
  const run = state();
  run(`task.role_queue[0] = {role: "coder", status: "RETRY_SCHEDULED",
    lease_liveness: "LEASE_EXPIRED", wait_reason: "provider_transient"};`);
  assert.equal(run("interruptedExecution(task)"), false);
  run('task.role_queue[0].status = "CLOSED"; task.role_queue[0].wait_reason = "lease_expired:lease_old"');
  assert.equal(run("interruptedExecution(task)"), false);
});

test("current terminal child blocker takes precedence over generic Manager advice", () => {
  const run = state();
  run(`request.stage = "BLOCKED"; request.scopes = [{delivery_id: "t"}];
    request.failed_stages = ["DELIVERING"];
    task.status = "BLOCKED"; task.terminal = true;
    task.blocker = "Coder provider route left repository changes";
    task.next_action = "Request exact Coder recovery";
    task.role_queue[0].status = "CLOSED";`);
  assert.equal(run("requestPresentation(request).blocker"), run("task.blocker"));
  assert.equal(run("requestPresentation(request).nextAction"), run("task.next_action"));
  assert.match(run("managerFlowStatus(request).textContent"), /当前角色已阻塞/);
  assert.doesNotMatch(run("managerFlowStatus(request).textContent"), /old blocker/);
  assert.equal(run("deliveryFlow(request).children[3].className"), "blocked");
});

for (const [role, index] of [["coder", 3], ["qa", 4], ["reviewer", 5]])
test(`new terminal ${role} failure remains blocked while its Continue operation is still running`, () => {
  const run = state();
  run(`request.scopes = [{delivery_id: "t"}];
    task.status = "BLOCKED"; task.terminal = true;
    task.blocker = "Fresh role failure"; task.role_queue[0] = {role: ${JSON.stringify(role)}, status: "CLOSED"};
    task.last_activity = "2026-10-01T00:02:00Z";
    operations = [{status: "RUNNING", requested_at: "2026-10-01T00:01:00Z",
      updated_at: "2026-10-01T00:01:01Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r"}}];`);
  assert.equal(run("requestPresentation(request).group"), "blocked");
  assert.equal(run("requestPresentation(request).blocker"), "Fresh role failure");
  assert.match(run("managerFlowStatus(request).textContent"), /处理中.*当前角色已阻塞/);
  assert.equal(run(`deliveryFlow(request).children[${index}].className`), "blocked");
  assert.equal(run('deliveryFlow(request).children.some(step => step.className === "current")'), false,
    "a blocked role cannot leave an earlier gate animating");
  run('task.role_queue = []');
  assert.equal(run('deliveryFlow(request).children[3].className'), "blocked",
    "without role facts, retain the aggregate delivery-stage fallback");
  assert.equal(run('deliveryFlow(request).children.some(step => step.className === "current")'), false);
  run('task.last_activity = "2026-10-01T00:00:00Z"');
  assert.equal(run("requestPresentation(request).group"), "active",
    "the previous terminal failure cannot mask preparation of a new authorized recovery");
  assert.doesNotMatch(run("managerFlowStatus(request).textContent"), /当前角色已阻塞/);
});

test("native flow uses the current claimed role after QA and review rework, not an older task", () => {
  const run = state();
  run(`request.coordination = null; request.scopes = [{delivery_id: "t"}];
    task.source_delivery_id = "t"; task.id = "candidate_verification";
    task.last_activity = "2026-10-01T00:02:00Z";
    snapshot.tasks.unshift({id: "t", request_id: "r", source_delivery_id: "t", status: "REVIEW", terminal: true,
      last_activity: "2026-10-01T00:00:00Z", role_queue: [], timeline: [{details: {kind: "qa-report", status: "PASS"}}]});`);
  for (const [status, role, index] of [["IMPLEMENTING", "coder", 3], ["QA", "qa", 4], ["REVIEW", "reviewer", 5]]) {
    run(`task.status = ${JSON.stringify(status)};
      task.role_queue[0] = {role: ${JSON.stringify(role)}, status: "RUNNING", lease_liveness: "LEASE_VALID"};
      task.execution_history = [{details: {kind: "qa-report", status: "FAIL"}}, {details: {kind: "review-report", verdict: "REJECT"}}];`);
    assert.equal(run(`deliveryFlow(request).children[${index}].className`), "current", status);
    assert.equal(run(`deliveryFlow(request).children.slice(${index + 1}).some(step => step.className === "done")`), false, status);
    if (index > 3) assert.equal(run("deliveryFlow(request).children[3].className"), "done");
  }
  run('task.role_queue[0].role = "coder"');
  assert.equal(run("deliveryFlow(request).children[5].className"), "paused", "a different role cannot prove Review is executing");
  run('request.stage = "DONE"');
  assert.equal(run('deliveryFlow(request).children.every(step => step.className === "done")'), true, "old/current task phases cannot override DONE");
  run('request.failed_stages = ["DESIGNING", "DELIVERING"]; task.role_queue[0].status = "WAITING_HUMAN"');
  assert.equal(run('deliveryFlow(request).children.every(step => step.className === "done")'), true, "retained waits and failures cannot turn DONE red");
});

test("native queue and expired-claim facts override a running manager operation with unknown execution", () => {
  const run = state();
  run(`request.scopes = [{delivery_id: "t"}];
    request.execution = {state: "UNKNOWN", responsibility: "team", reason_code: "EXECUTION_UNCONFIRMED", reason: "无心跳", next_action: "核验"};
    operations = [{status: "RUNNING", requested_at: "2026-10-01T00:01:00Z", updated_at: "2026-10-01T00:01:00Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r", project_id: "p"}}];`);
  for (const status of ["READY", "LEASED"]) {
    run(`task.role_queue[0].status = ${JSON.stringify(status)}`);
    assert.equal(run("deliveryFlow(request).children[3].className"), "paused");
  }
  for (const status of ["WAITING_HUMAN", "WAITING_DEPENDENCY"]) {
    run(`task.role_queue[0].status = ${JSON.stringify(status)}`);
    assert.equal(run("deliveryFlow(request).children[3].className"), "blocked");
    assert.equal(run("requestPresentation(request).group"), "blocked");
  }
  run('task.role_queue[0] = {role: "coder", status: "RETRY_SCHEDULED", lease_liveness: "LEASE_EXPIRED", wait_reason: "lease_expired:claim_old"}');
  assert.equal(run("deliveryFlow(request).children[3].className"), "blocked");
  assert.equal(run("requestPresentation(request).group"), "blocked");
  run('task.status = "BLOCKED"; task.terminal = true; task.blocker = "Fresh failure"; task.last_activity = "2026-10-01T00:02:00Z"; task.role_queue[0].status = "CLOSED"');
  assert.equal(run("requestPresentation(request).blocker"), "Fresh failure");
  assert.equal(run("deliveryFlow(request).children[3].className"), "blocked");
});

test("reader-shaped candidate verification keeps its current gate ahead of parent integration", () => {
  const run = state();
  run(`request.stage = "INTEGRATING"; request.coordination = null; request.scopes = [{delivery_id: "t"}];
    request.execution = {state: "UNKNOWN", responsibility: "team", reason_code: "EXECUTION_UNCONFIRMED", reason: "无心跳", next_action: "核验"};
    task.id = "verification_candidate"; task.source_delivery_id = "t"; task.work_kind = "candidate_verification";
    task.role_queue = []; task.last_activity = "2026-10-01T00:02:00Z";
    snapshot.tasks.unshift({id: "t", source_delivery_id: "t", request_id: "r", status: "REVIEW", terminal: true,
      last_activity: "2026-10-01T00:00:00Z", role_queue: []});
    operations = [{status: "RUNNING", requested_at: "2026-10-01T00:01:00Z", updated_at: "2026-10-01T00:01:00Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r", project_id: "p"}}];`);
  for (const [status, index] of [["VERIFY_QA", 4], ["VERIFY_REVIEW", 5]]) {
    run(`task.status = ${JSON.stringify(status)}`);
    assert.equal(run(`deliveryFlow(request).children[${index}].className`), "paused", status);
    assert.equal(run(`deliveryFlow(request).children.slice(${index}).some(step => step.className === "done")`), false, status);
    assert.equal(run("requestNodeExecution(request).state"), "paused", "parent Operation does not prove the verifier is running");
  }
});

test("a residual Coder claim cannot animate a queued or continuation-required checkpoint", () => {
  const run = state();
  run('request.coordination = null; request.scopes = [{delivery_id: "t"}]');
  for (const status of ["QUEUED", "CONTINUE_REQUIRED"]) {
    run(`task.status = ${JSON.stringify(status)}`);
    assert.equal(run("deliveryFlow(request).children[3].className"), "paused", status);
    assert.equal(run("requestNodeExecution(request).state"), "paused", status);
  }
  run('task.status = "IMPLEMENTING"');
  assert.equal(run("deliveryFlow(request).children[3].className"), "current");
});
