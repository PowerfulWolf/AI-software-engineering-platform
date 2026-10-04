const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function setup() {
  const element = (tag) => ({tag, children: [], textContent: "", dataset: {},
    attributes: {}, append(...nodes) { this.children.push(...nodes.filter(Boolean)); },
    addEventListener() {}, setAttribute(name, value) {this.attributes[name] = value;},
    classList: {toggle() {}}});
  const context = vm.createContext({
    document: {getElementById: element, createElement: element, querySelectorAll: () => []},
    fetch: () => new Promise(() => {}), AbortController,
    setInterval() {}, setTimeout() {}, clearTimeout() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,
    "../../src/ai_software_engineer/team_view/app.js"), "utf8"), context);
  vm.runInContext(`
    snapshot = {selected_project_id: "p", requests: [], tasks: []};
    const execution = {state: "WAITING", responsibility: "engineering",
      reason_code: "WAITING_HUMAN", reason: "开发等待工程前提处理。",
      next_action: "工程团队处理，当前无需产品操作。", action_required: false,
      policy_id: "policy_engineering", receipt_uri: "receipt://technical-hash"};
    const request = {id: "r", project_id: "p", stage: "DELIVERING", scopes: [{delivery_id: "t"}],
      checkpoint_sha256: "current", next_action: "old next", execution, failed_stages: []};
    const task = {id: "t", request_id: "r", status: "IMPLEMENTING", terminal: false,
      last_activity: "2026-10-04T00:00:00Z", next_action: "old next", execution,
      role_queue: [{role: "coder", status: "WAITING_HUMAN", lease_liveness: "UNKNOWN"}]};
    snapshot.requests = [request]; snapshot.tasks = [task];
  `, context);
  return expression => vm.runInContext(expression, context);
}
function text(node) {
  return [node.textContent, ...node.children.map(text)].filter(Boolean).join(" ");
}

test("product sees stage, actual wait, responsible team and next step without technical identities", () => {
  const run = setup();
  const summary = run("productExecutionSummary(request)");
  assert.match(text(summary), /交付阶段 · 实现/);
  assert.match(text(summary), /当前执行 · 等待工程处理/);
  assert.match(text(summary), /处理方 · 工程团队/);
  assert.match(text(summary), /无需产品操作/);
  assert.doesNotMatch(text(summary), /receipt|policy_engineering|technical-hash|lease|租约/);
  assert.equal(run("requestPresentation(request).status"), "WAITING_ENGINEERING");
  assert.match(run('assignmentBadge(task, {role: "coder", current_stage: false}).textContent'), /等待工程处理/);
  assert.doesNotMatch(text(run("managerFlowStatus(request)")), /等待审批|请.*批准/);
});

test("scheduled retry stays in the implementation phase without animated execution", () => {
  const run = setup();
  run(`execution.state = "RETRY_SCHEDULED"; execution.responsibility = "team";
    execution.reason_code = "ROLE_RETRY_SCHEDULED";
    execution.available_at = "2026-10-04T00:00:45Z";
    execution.reason = "模型执行重试已排队。";
    task.role_queue[0].status = "RETRY_SCHEDULED";`);
  assert.equal(run("requestPresentation(request).group"), "active");
  assert.equal(run("requestPresentation(request).status"), "RETRY_SCHEDULED");
  assert.match(text(run("productExecutionSummary(request)")), /计划重试时间/);
  assert.equal(run("deliveryFlow(request).children[3].className"), "paused");
  assert.equal(run('deliveryFlow(request).children.some(step => step.className === "current")'), false);
  assert.equal(run("request.stage"), "DELIVERING");
});

test("only typed product responsibility asks a business decision", () => {
  const run = setup();
  run(`execution.responsibility = "product"; execution.action_required = true;
    execution.reason = "验收规则存在两种解释。"; execution.next_action = "请选择业务规则。";`);
  assert.match(text(run("productExecutionSummary(request)")), /需要你确认业务决定/);
  assert.equal(run("requestPresentation(request).status"), "WAITING_PRODUCT_DECISION");
});

test("closed Requirement keeps its closed group and has no pending coordination", () => {
  const run = setup();
  run('request.stage = "CLOSED"; execution.state = "STOPPED"');
  assert.equal(run("requestGroup(request)"), "closed");
  assert.equal(run("managerFlowStatus(request)"), null);
});

test("verified and superseded candidate history never requests engineering recovery", () => {
  const run = setup();
  run(`task.status = "VERIFIED"; task.terminal = true; task.role_queue = [];
    execution.state = "COMPLETED"; execution.responsibility = "team";
    execution.reason_code = "CANDIDATE_VERIFIED";
    execution.reason = "本次候选验证已通过; 整体交付以需求验收状态为准。";
    execution.next_action = "查看本次候选的 QA 与 Review 验收记录。";`);
  assert.match(text(run("productExecutionSummary(task)")), /当前执行 · 候选验证已通过/);
  assert.equal(run("taskGroup(task)"), "completed");
  run(`task.status = "VERIFICATION_SUPERSEDED"; execution.state = "SUPERSEDED";
    execution.reason_code = "VERIFICATION_SUPERSEDED";
    execution.reason = "本次历史验证已由后续计划替代, 记录保留用于审计。";
    execution.next_action = "查看后续验证计划与当前交付状态。";`);
  const summary = text(run("productExecutionSummary(task)"));
  assert.match(summary, /当前执行 · 历史验证已替代/);
  assert.doesNotMatch(summary, /交付已停止|工程团队|恢复/);
  assert.equal(run("taskGroup(task)"), "completed");
});

test("new stopped-work diagnostic remains Chinese engineering treatment", () => {
  const run = setup();
  const reason = run('humanizeBlockingText("WORK_INTERRUPTED: Coder failed at attempt 1: 工程执行已中断。草稿已保留。现场不满足自动继续条件。需要工程处理。")');
  assert.match(reason, /工程团队/);
  assert.doesNotMatch(reason, /等待精确恢复审批|WORK_INTERRUPTED/);
});

test("exact technical approval remains in explicit engineering management disclosure", () => {
  const run = setup();
  run(`consoleAvailable = true; operationsAvailable = true; consoleDeliveryReady = true;
    consoleTeamId = "team"; snapshot.team_id = "team";`);
  const approval = run('recoveryApprovalBox(request, {kind: "coder_recovery", title: "恢复计划", facts: ["SHA exact"], plan_sha256: "exact"})');
  assert.equal(approval.tag, "details");
  assert.equal(approval.children[0].tag, "summary");
  assert.match(approval.children[0].textContent, /工程管理/);
  assert.match(text(approval), /产品负责人无需决定技术恢复方式/);
  assert.match(text(approval), /SHA exact/);
});
