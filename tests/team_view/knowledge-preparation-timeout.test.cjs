const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function fixture(role = "coder") {
  const context = vm.createContext({document: {getElementById: () => ({addEventListener() {}}),
    querySelectorAll: () => []}, fetch: () => new Promise(() => {}), AbortController,
    setInterval() {}, setTimeout() {}, clearTimeout() {}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,
    "../../src/ai_software_engineer/team_view/app.js"), "utf8"), context);
  const run = expression => vm.runInContext(expression, context);
  run(`consoleAvailable = true; consoleDeliveryReady = true; consoleTeamId = "team";
    consoleOperationContractVersion = 4; consoleSupportedActions = ["CONTINUE_DELIVERY"];
    operationsAvailable = true; operations = [];
    const reason = "TRANSIENT_INFRA: ${role} knowledge preparation reached local time limit";
    const execution = {state: "STOPPED", responsibility: "engineering", reason,
      next_action: "由工程团队核对停止原因和安全恢复路径; 当前无需产品操作。", action_required: false};
    const request = {id: "r", project_id: "p", stage: "BLOCKED", blocker: reason,
      checkpoint_sha256: "current", execution, scopes: [{delivery_id: "t"}], failed_stages: ["DELIVERING"]};
    const task = {id: "t", task_id: "task_t", request_id: "r", project_id: "p",
      status: "BLOCKED", terminal: true, blocker: reason, execution, role_queue: [],
      last_activity: "2026-10-10T11:31:30Z", next_action: execution.next_action};
    snapshot = {team_id: "team", selected_project_id: "p", requests: [request], tasks: [task]};`);
  return run;
}

for (const role of ["coder", "qa", "reviewer"]) test(`${role} knowledge timeout explains preparation before confirmation without inventing a ready plan`, () => {
  const run = fixture(role);
  const before = run("JSON.stringify({snapshot, operations})");
  const summary = run("requestBlockingSummary(request)");
  if (role === "coder") {
    assert.match(summary.suggestedAction, /点击本页“继续交付”.*准备.*恢复方案.*准备好后.*批准继续/);
    assert.doesNotMatch(summary.suggestedAction, /核对停止原因|无需产品操作|重建需求|kill|重启电脑/);
  } else assert.doesNotMatch(summary.suggestedAction, /点击本页“继续交付”/);
  assert.match(run("humanizeBlockingText(reason)"), /本次执行时限.*本轮尚未开始/);
  assert.doesNotMatch(run("humanizeBlockingText(reason)"), /请.*批准.*计划|停止.*未知|模型服务.*故障/);
  assert.equal(summary.approval, null);
  assert.equal(run("JSON.stringify({snapshot, operations})"), before);
});

test("read outage and missing Continue capability never recommend an unavailable click", () => {
  const run = fixture();
  run('teamReadIssue = "busy"');
  assert.match(run("requestBlockingSummary(request).suggestedAction"), /读取/);
  assert.doesNotMatch(run("requestBlockingSummary(request).suggestedAction"), /点击本页“继续交付”/);
  run('teamReadIssue = null; consoleSupportedActions = []');
  assert.match(run("requestBlockingSummary(request).suggestedAction"), /当前服务.*不支持.*继续交付/);
  assert.doesNotMatch(run("requestBlockingSummary(request).suggestedAction"), /点击本页“继续交付”/);
});

test("an exact prepared approval keeps its existing priority over the historical knowledge timeout", () => {
  const run = fixture();
  run(`operations = [{operation_id: "prepared", team_id: "team", status: "SUCCEEDED",
    requested_at: "2026-10-10T11:32:00Z", updated_at: "2026-10-10T11:32:00Z",
    intent: {action: "CONTINUE_DELIVERY", project_id: "p", delivery_id: "r", expected_checkpoint_sha256: "current"},
    result: {delivery_id: "r", checkpoint_sha256: "current", approval: {kind: "coder_recovery",
      title: "保留进度继续", plan_sha256: "e".repeat(64)}}}];`);
  assert.equal(run("requestBlockingSummary(request).currentApproval"), true);
  assert.doesNotMatch(run("requestBlockingSummary(request).suggestedAction"), /点击本页“继续交付”/);
});

for (const status of ["QUEUED", "RUNNING"]) test(`an exact ${status} Continue request has waiting guidance without a duplicate click`, () => {
  const run = fixture();
  run(`operations = [{operation_id: "active", status: ${JSON.stringify(status)},
    requested_at: "2026-10-10T11:30:00Z", updated_at: "2026-10-10T11:30:00Z",
    intent: {action: "CONTINUE_DELIVERY", project_id: "p", delivery_id: "r"}}];`);
  assert.match(run("requestBlockingSummary(request).suggestedAction"), /排队|正在处理/);
  assert.doesNotMatch(run("requestBlockingSummary(request).suggestedAction"), /点击本页“继续交付”/);
  for (const change of ['operations[0].intent.project_id = "other"', 'operations[0].intent.project_id = "p"; operations[0].intent.delivery_id = "other"']) {
    run(change);
    assert.match(run("requestBlockingSummary(request).suggestedAction"), /点击本页“继续交付”/);
  }
});

test("approximate prose and a genuine engineering wait retain their own routing", () => {
  const run = fixture();
  const near = "coder knowledge preparation reached local time limit; unknown call";
  assert.equal(run(`humanizeBlockingText(${JSON.stringify(near)})`), near);
  run(`execution.state = "WAITING"; execution.reason = "原执行停止证据未知。";
    execution.next_action = "等待平台核验。"; task.terminal = false; task.status = "IMPLEMENTING";
    task.role_queue = [{role: "coder", status: "WAITING_HUMAN", lease_liveness: "UNKNOWN"}];`);
  assert.doesNotMatch(run("requestBlockingSummary(request).suggestedAction"), /点击本页“继续交付”/);
});
