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
    document: {getElementById: element, createElement: element, createTextNode: text => ({textContent: text, children: []}), querySelectorAll: () => []},
    fetch: () => new Promise(() => {}), AbortController,
    setInterval() {}, setTimeout() {}, clearTimeout() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,
    "../../src/ai_software_engineer/team_view/app.js"), "utf8"), context);
  vm.runInContext(`
    // This harness represents a successfully read current Operations list.
    operationsAvailable = true;
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

test("legacy upstream actions render Chinese in execution and suggested-action regions without mutation", () => {
  const run = setup();
  run(`execution.reason = "Reply to the Product Agent questions.";
    execution.next_action = "Review product_spec and approve this exact checkpoint, or reply with revisions.";`);
  const summary = text(run("productExecutionSummary(request)"));
  assert.match(summary, /请回答 Product Agent 的问题/);
  assert.match(summary, /下一步 · 请审阅本版产品规格并批准，或回复需要修改的内容/);
  const blockers = text(run("requestBlockerSection(request)"));
  assert.match(blockers, /建议操作 请审阅本版产品规格并批准，或回复需要修改的内容/);
  assert.doesNotMatch(summary + blockers, /Review product_spec|Reply to the Product/);
  assert.equal(run("execution.next_action"), "Review product_spec and approve this exact checkpoint, or reply with revisions.");
  assert.equal(run("execution.reason"), "Reply to the Product Agent questions.");
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

test("exact technical approval and its facts are directly visible to the engineering authorizer", () => {
  const run = setup();
  run(`consoleAvailable = true; operationsAvailable = true; consoleDeliveryReady = true;
    consoleTeamId = "team"; snapshot.team_id = "team";`);
  const approval = run('recoveryApprovalBox(request, {kind: "coder_recovery", title: "恢复计划", facts: ["SHA exact"], plan_sha256: "exact"})');
  assert.equal(approval.tag, "section");
  assert.equal(approval.children[0].tag, "p");
  assert.match(approval.children[0].textContent, /当前需要工程授权者确认.*具体方案.*记录实际批准者/);
  const box = approval.children[1];
  assert.equal(box.tag, "div");
  assert.equal(box.children[0].tag, "h3");
  assert.equal(box.children[0].textContent, "恢复计划");
  assert.equal(box.children.at(-1).tag, "button");
  assert.equal(box.children.at(-1).textContent, "批准并继续");
  assert.match(text(approval), /SHA exact/);
});

test("recovery approval keeps human facts visible and technical facts grouped", () => {
  const run = setup();
  const approval = run('recoveryApprovalBox(request, {kind: "coder_recovery", title: "保留进度并继续原需求", facts: ["保留 4 个业务文件"], technical_facts: ["旧执行已由受控 runner 停止", ".venv 只保留在历史工作区审计，不会进入候选"], plan_sha256: "exact"})');
  const box = approval.children[1];
  assert.match(text(box), /保留 4 个业务文件/);
  assert.match(text(box), /技术核对信息/);
  assert.match(text(box), /旧执行已由受控 runner 停止/);
  assert.match(text(box), /批准并继续/);
  const details = box.children.find(child => child.tag === "details");
  assert.ok(details);
  assert.notEqual(details.open, true);
  assert.ok(details.children.every(child => child.tag !== "button"));
  assert.equal(box.children.at(-1).tag, "button");
});

test("an active upstream operation shows node processing while executor facts stay unknown", () => {
  const run = setup();
  for (const stage of ["PRODUCT_DISCOVERY", "DESIGNING", "PLANNING", "INTEGRATING"]) {
    run(`snapshot.tasks = []; request.stage = ${JSON.stringify(stage)};
      execution.state = "UNKNOWN"; execution.responsibility = "team";
      execution.reason_code = "EXECUTION_UNCONFIRMED"; execution.reason = "尚无执行器心跳。";
      operations = [{status: "RUNNING", requested_at: "2026-10-04T00:00:00Z",
        updated_at: "2026-10-04T00:00:00Z", intent: {action: "PRODUCT_APPROVAL", delivery_id: "r", project_id: "p"}}];`);
    assert.equal(run("requestNodeExecution(request).state"), "running", stage);
    assert.match(text(run("productExecutionSummary(request)")), /当前执行 · 执行中/);
    assert.doesNotMatch(text(run("managerFlowStatus(request)")), /待确认|阻塞/);
    assert.equal(run("execution.state"), "UNKNOWN");
    assert.match(run("requestNodeBadge(request).textContent"), /执行中/);
  }
});

test("retained upstream Operations cannot authorize running or queued nodes during a read failure", () => {
  const run = setup();
  run(`snapshot.tasks = []; request.stage = "DESIGNING"; request.scopes = [];
    execution.state = "UNKNOWN"; execution.responsibility = "team";
    execution.reason_code = "EXECUTION_UNCONFIRMED";
    operations = [{status: "RUNNING", updated_at: "2026-10-04T00:00:00Z",
      intent: {action: "PRODUCT_APPROVAL", delivery_id: "r", project_id: "p"}}];`);
  for (const [status, label] of [["RUNNING", "执行中"], ["QUEUED", "已排队"]]) {
    run(`operations[0].status = ${JSON.stringify(status)}; operationsAvailable = true`);
    const saved = run("JSON.stringify(operations)");
    assert.equal(run("requestNodeExecution(request).label"), label);
    run("operationsAvailable = false");
    assert.equal(run('activeOperation("r", "p")'), undefined);
    assert.notEqual(run("requestNodeExecution(request).state"), "running");
    assert.doesNotMatch(run("requestNodeExecution(request).label"), /执行中|已排队/);
    assert.equal(run('deliveryFlow(request).children.some(step => step.className === "current")'), false);
    assert.equal(run("JSON.stringify(operations)"), saved, "complete retained history remains unchanged");
    assert.equal(run("execution.state"), "UNKNOWN");
    run("operationsAvailable = true");
    assert.equal(run("requestNodeExecution(request).label"), label, "a fresh successful read restores current authority");
  }
});

test("delivery nodes name safe upstream continuation, queue and retry while durable waiting stays red", () => {
  const run = setup();
  run(`snapshot.tasks = []; request.stage = "DESIGNING"; request.scopes = [];
    execution.state = "UNKNOWN"; execution.responsibility = "team";
    operations = [];`);
  assert.equal(run("requestNodeExecution(request).state"), "paused");
  assert.equal(run("requestNodeExecution(request).label"), "待继续");
  assert.equal(run("deliveryFlow(request).children[1].className"), "paused");
  run(`operations = [{status: "QUEUED", updated_at: "2026-10-04T00:00:00Z",
    intent: {action: "PRODUCT_APPROVAL", delivery_id: "r", project_id: "p"}}]`);
  assert.equal(run("requestNodeExecution(request).label"), "已排队");
  assert.equal(run("deliveryFlow(request).children[1].className"), "paused");
  run('operations[0].status = "RUNNING"; execution.state = "QUEUED"');
  assert.equal(run("requestNodeExecution(request).label"), "已排队", "typed queued execution outranks the processing operation");
  run('operations[0].status = "RUNNING"; execution.state = "RETRY_SCHEDULED"');
  assert.equal(run("requestNodeExecution(request).label"), "待重试");
  run('execution.state = "WAITING"; execution.responsibility = "engineering"');
  assert.equal(run("requestNodeExecution(request).state"), "blocked");
  assert.equal(run("deliveryFlow(request).children[1].className"), "blocked");
  assert.equal(run("requestPresentation(request).group"), "blocked");
  run('execution.state = "UNKNOWN"; execution.reason_code = "EXECUTION_CLAIM_EXPIRED"');
  assert.equal(run("requestNodeExecution(request).state"), "blocked");
  assert.equal(run("deliveryFlow(request).children[1].className"), "blocked");
  run('execution.reason_code = "EXECUTION_UNCONFIRMED"; operations[0].intent.project_id = "other"');
  assert.equal(run("requestNodeExecution(request).label"), "等待工程处理");
});

test("product decisions remain red and completed delivery has seven green completed nodes", () => {
  const run = setup();
  run('snapshot.tasks = []; request.scopes = []; execution.state = "UNKNOWN"');
  for (const [stage, expected] of [["WAITING_PRODUCT_REPLY", "需确认"], ["WAITING_PRODUCT_APPROVAL", "待审批"]]) {
    run(`request.stage = ${JSON.stringify(stage)}; operations = [{status: "SUCCEEDED", updated_at: "2026-10-04T00:00:00Z",
      intent: {action: "PRODUCT_REPLY", delivery_id: "r", project_id: "p"}}]`);
    assert.equal(run("requestNodeExecution(request).label"), expected);
    assert.equal(run("deliveryFlow(request).children[0].className"), "blocked");
  }
  run('request.stage = "DONE"; execution.state = "COMPLETED"');
  assert.equal(run('deliveryFlow(request).children.every(step => step.className === "done")'), true);
  assert.match(text(run("deliveryFlow(request).children[6]")), /已完成/);
  run('request.stage = "CLOSED"; execution.state = "STOPPED"');
  assert.equal(run('deliveryFlow(request).children.some(step => step.className === "done")'), false);
});

test("typed unknown execution retains budget, recheck and exact-approval gates until a legal retry", () => {
  const run = setup();
  run(`snapshot.tasks = []; request.stage = "DESIGNING"; request.scopes = [];
    execution.state = "UNKNOWN"; execution.responsibility = "team"; operations = [];
    request.stage_budget = {role: "designer", exhausted: "work", attempts: 3, max_attempts: 3, transient_failures: 0, max_transient_failures: 5};`);
  assert.equal(run("requestNodeExecution(request).label"), "设计预算已用尽");
  assert.equal(run("requestPresentation(request).group"), "blocked");
  run('request.design_recovery_available = true');
  assert.equal(run("requestNodeExecution(request).label"), "设计待恢复");
  run('request.design_recovery_available = false; request.stage_budget = null; request.design_recheck_pending = true');
  assert.equal(run("requestNodeExecution(request).state"), "blocked");
  run(`request.design_recheck_pending = false;
    operations = [{status: "SUCCEEDED", updated_at: "2026-10-04T00:00:00Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r", project_id: "p"},
      result: {delivery_id: "r", checkpoint_sha256: "current", approval: {kind: "coder_scope", title: "新增文件范围", plan_sha256: "exact"}}}];`);
  assert.equal(run("requestNodeExecution(request).label"), "待工程确认");
  run(`operations = [{status: "RUNNING", updated_at: "2026-10-04T00:00:00Z",
    intent: {action: "CONTINUE_DELIVERY", delivery_id: "r", project_id: "p"}}];
    request.stage_budget = {role: "designer", exhausted: "work", attempts: 3, max_attempts: 3};`);
  assert.equal(run("requestNodeExecution(request).state"), "running", "a reserved final work attempt is still processing");
});

test("a current successor without a claim asks engineering to verify instead of showing historical failures or advice", () => {
  const run = setup();
  run(`execution.state = "UNKNOWN"; execution.responsibility = "team";
    request.coordination = null; task.role_queue = []; task.last_activity = "2026-10-04T00:02:00Z";
    operations = [{status: "FAILED", updated_at: "2026-10-04T00:01:00Z", result: null,
      error_code: "EXECUTION_FAILED", error_summary: "旧操作失败",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r", project_id: "p", expected_checkpoint_sha256: "old"}}];`);
  for (const status of ["NEW", "PLANNING", "IMPLEMENTING"]) {
    run(`task.status = "${status}"`);
    assert.equal(run("requestNodeExecution(request).state"), "blocked", status);
    assert.equal(run("requestNodeExecution(request).label"), "等待工程处理", status);
    assert.equal(run("requestPresentation(request).group"), "blocked", status);
    assert.equal(run("canContinueDelivery(request)"), false, status);
    assert.doesNotMatch(text(run("productExecutionSummary(request)")), /旧操作失败/, status);
  }
  run('operations = []; request.coordination = {draft: {action: "WAITING_HUMAN", summary: "旧协调建议"}}');
  assert.equal(run("requestNodeExecution(request).label"), "等待工程处理");
  assert.equal(run("requestPresentation(request).group"), "blocked");
  assert.doesNotMatch(text(run("productExecutionSummary(request)")), /旧协调建议|状态待核对/);
  run('task.blocker = "保留的旧阻塞文本"');
  assert.equal(run("requestNodeExecution(request).requiresEngineeringCheck"), true);
  assert.equal(run("canContinueDelivery(request)"), false, "retained blocker text does not authorize unknown execution");
  run('task.status = "IMPLEMENTING"; task.role_queue = [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID"}]');
  assert.equal(run("requestNodeExecution(request).state"), "running");
});

test("native unknown state agrees across task summary, assignment, card and member displays", () => {
  const run = setup();
  run(`execution.state = "UNKNOWN"; execution.responsibility = "engineering";
    execution.reason_code = "EXECUTION_NOT_OBSERVED"; execution.reason = "尚无执行事实";
    task.role_queue = []; task.assignments = [{role: "coder", current_stage: true, agent_id: "coder"}];`);
  assert.equal(run("taskGroup(task)"), "blocked");
  assert.equal(run("taskPresentationStatus(task)"), "WAITING_ENGINEERING");
  assert.match(run("assignmentBadge(task, task.assignments[0]).textContent"), /等待工程处理/);
  assert.match(text(run("productExecutionSummary(task)")), /等待工程处理/);
  assert.doesNotMatch(text(run("productExecutionSummary(task)")), /执行状态待确认|状态待核对/);
  run('task.role_queue = [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID"}]');
  assert.equal(run("taskGroup(task)"), "active");
  assert.equal(run("taskPresentationStatus(task)"), "RUNNING");
  assert.match(text(run("productExecutionSummary(task)")), /当前执行 · 执行中/);
  run('task.role_queue[0].status = "READY"; task.role_queue[0].lease_liveness = "UNKNOWN"');
  assert.equal(run("taskGroup(task)"), "active");
  assert.equal(run("taskPresentationStatus(task)"), "READY");
  assert.match(text(run("productExecutionSummary(task)")), /当前执行 · 等待调度/);
  assert.doesNotMatch(text(run("productExecutionSummary(task)")), /尚无执行事实|处理方 · 工程团队/);
  assert.doesNotMatch(run("assignmentBadge(task, task.assignments[0]).className"), /current|blocked/);
  run(`task.status = "QA"; task.assignments = [{role: "coder", current_stage: false}, {role: "qa", current_stage: true}, {role: "reviewer", current_stage: false}];
    task.role_queue = [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID"}, {role: "qa", status: "RUNNING", lease_liveness: "LEASE_VALID"}];`);
  assert.match(run("assignmentBadge(task, task.assignments[0]).textContent"), /本轮已完成/);
  assert.match(run("assignmentBadge(task, task.assignments[1]).textContent"), /执行中/);
  assert.doesNotMatch(run("assignmentBadge(task, task.assignments[2]).textContent"), /执行中/);
});

test("only live matching delivery work makes native bootstrap gray preparation", () => {
  const run = setup();
  run(`execution.state = "UNKNOWN"; execution.responsibility = "engineering"; execution.reason = "尚无执行事实";
    task.role_queue = []; task.execution = execution; task.blocker = null;
    operations = [{status: "RUNNING", updated_at: "2026-10-05T12:34:00Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r", project_id: "p"}}];`);
  for (const status of ["NEW", "PLANNING"]) {
    run(`task.status = "${status}"`);
    assert.equal(run("requestNodeExecution(request).label"), "准备执行", status);
    assert.equal(run("taskPresentationStatus(task)"), "PREPARING_EXECUTION", status);
    assert.equal(run("taskGroup(task)"), "active", status);
    assert.equal(run("requestNodeExecution(request).state"), "paused", status);
    assert.equal(run("canContinueDelivery(request)"), false, status);
    assert.doesNotMatch(text(run("productExecutionSummary(request)")), /尚无执行事实|处理方 · 工程团队/);
  }
  run('operations[0].intent.action = "INSPECT_DELIVERY_WAIT"');
  assert.equal(run("requestNodeExecution(request).label"), "等待工程处理");
  run('operations[0].intent.action = "CONTINUE_DELIVERY"; task.status = "IMPLEMENTING"');
  assert.equal(run("requestNodeExecution(request).label"), "等待工程处理");
  run('task.status = "NEW"; operations = []');
  assert.equal(run("taskPresentationStatus(task)"), "WAITING_ENGINEERING");
  assert.equal(run("canContinueDelivery(request)"), false);
});

test("retained delivery Operations cannot establish native preparation during a read failure", () => {
  const run = setup();
  run(`execution.state = "UNKNOWN"; execution.responsibility = "engineering";
    task.role_queue = []; task.blocker = null;
    operations = [{status: "RUNNING", updated_at: "2026-10-05T12:34:00Z",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r", project_id: "p"}}];`);
  for (const status of ["NEW", "PLANNING"]) {
    run(`task.status = ${JSON.stringify(status)}; operationsAvailable = true`);
    const saved = run("JSON.stringify(operations)");
    assert.equal(run("taskPresentationStatus(task)"), "PREPARING_EXECUTION");
    run("operationsAvailable = false");
    assert.equal(run("requestNodeExecution(request).label"), "等待工程处理");
    assert.equal(run("taskPresentationStatus(task)"), "WAITING_ENGINEERING");
    assert.equal(run("taskGroup(task)"), "blocked");
    assert.equal(run("canContinueDelivery(request)"), false);
    assert.equal(run("JSON.stringify(operations)"), saved);
    run("operationsAvailable = true");
    assert.equal(run("taskPresentationStatus(task)"), "PREPARING_EXECUTION");
  }
});

test("host interruption blocks the retained upstream stage and member queue without altering original facts", () => {
  const run = setup();
  const original = "The console host stopped before the operation completed.";
  run(`snapshot.tasks = []; request.stage = "DESIGNING"; request.scopes = [];
    execution.state = "UNKNOWN"; execution.responsibility = "team";
    snapshot.projects = [{id: "p", name: "项目"}];
    snapshot.agents = [{id: "designer", name: "设计", roles: ["designer"], enabled: true,
      max_parallel_assignments: 1, assigned_delivery_ids: ["r"], current_stage_delivery_ids: ["r"], history_delivery_ids: []}];
    selectedAgentId = "designer";
    operations = [{operation_id: "host-interrupted", status: "INTERRUPTED", result: null,
      updated_at: "2026-10-05T12:32:00Z", error_code: "HOST_INTERRUPTED",
      error_summary: ${JSON.stringify(original)},
      intent: {action: "PRODUCT_APPROVAL", delivery_id: "r", project_id: "p", expected_checkpoint_sha256: "before-attempt"}}];`);
  assert.equal(run("requestNodeExecution(request).state"), "blocked");
  assert.equal(run("requestNodeExecution(request).label"), "操作已中断");
  assert.equal(run("deliveryFlow(request).children[0].className"), "done");
  assert.equal(run("deliveryFlow(request).children[1].className"), "blocked");
  assert.match(text(run("productExecutionSummary(request)")), /服务在本次操作完成前已停止|继续设计/);
  assert.doesNotMatch(text(run("productExecutionSummary(request)")), /状态待核对|当前节点正在执行/);
  const team = run('(() => {const container = document.createElement("div"); renderTeam(container); return container;})()');
  assert.match(text(team), /已阻塞/);
  assert.doesNotMatch(text(team), /执行中/);
  assert.match(text(team), /操作已中断/);
  assert.equal(run("execution.state"), "UNKNOWN");
  assert.equal(run("operations[0].error_summary"), original);
  assert.equal(run("snapshot.agents[0].current_stage_delivery_ids.join()"), "r");
  assert.match(run("operationNoticeFor(operations[0]).message"), /服务在本次操作完成前已停止/);
  assert.match(run('badge("INTERRUPTED").className'), /blocked execution-interrupted/);
  assert.doesNotMatch(run('badge("INTERRUPTED").className'), /current/);
  run('operations[0].intent.action = "CLOSE_REQUIREMENT"');
  assert.equal(run("canResumeUpstreamStage(request)"), false, "lifecycle interruption cannot authorize a delivery continuation");
});

test("a failed upstream operation stays red after its stage attempt advances the input checkpoint", () => {
  const run = setup();
  run(`snapshot.tasks = []; request.stage = "DESIGNING"; request.coordination = null;
    request.checkpoint_sha256 = "after-stage-attempt";
    execution.state = "UNKNOWN"; execution.responsibility = "team";
    operations = [{status: "FAILED", requested_at: "2026-10-04T00:02:00Z",
      updated_at: "2026-10-04T00:03:00Z", result: null,
      error_code: "EXECUTION_FAILED", error_summary: "本轮失败",
      intent: {action: "PRODUCT_APPROVAL", delivery_id: "r", project_id: "p",
        expected_checkpoint_sha256: "before-stage-attempt"}}];`);
  for (const action of ["PRODUCT_APPROVAL", "CONTINUE_DELIVERY"]) {
    run(`operations[0].intent.action = "${action}"`);
    assert.equal(run("requestNodeExecution(request).state"), "blocked", action);
    assert.equal(run("requestNodeExecution(request).reason"), "本轮失败", action);
    assert.equal(run("requestPresentation(request).group"), "blocked", action);
  }
  run('operations[0].intent.project_id = "other-project"');
  assert.equal(run("requestNodeExecution(request).label"), "等待工程处理", "another project cannot establish this failure or authorize continuation");
  assert.notEqual(run("requestNodeExecution(request).reason"), "本轮失败");
});
