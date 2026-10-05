const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute() {}
  addEventListener() {}
  set innerHTML(value) { throw new Error("Unsafe HTML: " + value); }
}
const descend = node => [node, ...node.children.filter(item => typeof item !== "string").flatMap(descend)];
const text = node => node.textContent + node.children.map(item => typeof item === "string" ? item : text(item)).join(" ");

function harness() {
  const data = {
    request: {id: "request_current", project_id: "project_current", stage: "DESIGNING", checkpoint_sha256: "b".repeat(64),
      scopes: [{delivery_id: "task_current"}], documents: [], next_action: "旧阶段提示", execution: {state: "UNKNOWN", responsibility: "team",
        reason: "尚无执行器心跳。", next_action: "核验执行事实。", action_required: false}},
    operation: {operation_id: "operation_current", status: "RUNNING", updated_at: "2026-10-05T12:44:30Z",
      intent: {action: "CONTINUE_DELIVERY", project_id: "project_current", delivery_id: "request_current",
        expected_checkpoint_sha256: "a".repeat(64)}, result: null},
  };
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  vm.runInContext(`snapshot = {team_id: "team_current", selected_project_id: "project_current", projects: [], agents: [],
    tasks: [], requests: [data.request]}; operations = [data.operation];`, context);
  const run = code => vm.runInContext(code, context);
  const render = () => run('(() => { const panel = el("section"); requestOperationHistory(panel, data.request); return panel; })()');
  return {data, context, run, render};
}
const rows = panel => descend(panel).filter(node => node.tagName === "LI");

test("unchanged current operation row follows stage and native role facts", () => {
  const h = harness();
  const original = JSON.stringify(h.data.operation);
  let previousSignature;
  for (const [stage, status, role, phase] of [["DESIGNING", null, null, "技术设计"], ["PLANNING", null, null, "计划编排"],
    ["DELIVERING", "IMPLEMENTING", "coder", "实现"], ["DELIVERING", "QA", "qa", "测试"], ["DELIVERING", "REVIEW", "reviewer", "评审"]]) {
    h.context.update = {stage, status, role};
    h.run(`data.request.stage = update.stage; snapshot.tasks = update.status ? [{id: "task_current", request_id: data.request.id,
      project_id: data.request.project_id, status: update.status, terminal: false, last_activity: "2026-10-05T13:00:00Z",
      role_queue: [{role: update.role, status: "RUNNING", lease_liveness: "LEASE_VALID"}]}] : [];`);
    const row = rows(h.render())[0];
    assert.equal(row.children[0].textContent, `当前阶段 · ${phase} · 执行中`);
    assert.match(text(row), /发起操作 · 继续交付/);
    assert.match(text(row), /操作目的 · 接续已保存的交付进度/);
    h.context.row = row;
    const signature = h.run("renderedBlocks.get(row).signature");
    assert.notEqual(signature, previousSignature, "phase facts participate in the keyed row signature");
    previousSignature = signature;
    assert.equal(JSON.stringify(h.data.operation), original);
  }
});

test("current blocked node explains responsibility and exact product next step despite RUNNING command", () => {
  const h = harness();
  Object.assign(h.data.request, {stage: "WAITING_PRODUCT_APPROVAL", next_action: "请批准本版产品规格。",
    execution: {state: "WAITING", responsibility: "product", reason: "本版产品规格等待确认。",
      next_action: "请批准本版产品规格。", action_required: true}});
  const row = rows(h.render())[0];
  assert.match(text(row), /当前阶段 · 等待产品批准 · 待审批/);
  assert.match(text(row), /当前原因 · 本版产品规格等待确认/);
  assert.match(text(row), /处理方 · 产品负责人/);
  assert.match(text(row), /下一步 · 请批准本版产品规格/);
  assert.doesNotMatch(text(row), /无需产品操作|请等待本轮/);
  h.data.request.stage = "PLANNING";
  h.data.request.execution = {state: "WAITING", responsibility: "engineering", reason: "执行结果待工程核验。",
    next_action: "工程团队核验保留现场后继续。", action_required: false};
  assert.match(text(rows(h.render())[0]), /当前阶段 · 计划编排 · 等待工程处理/);
  assert.match(text(rows(h.render())[0]), /工程团队核验保留现场后继续/);
});

test("only exact current running delivery work has live progress, never queued or sealed history", () => {
  const h = harness();
  h.run(`operations.push(...["SUCCEEDED", "FAILED", "INTERRUPTED", "QUEUED"].map((status, index) => ({
    ...data.operation, operation_id: "history_" + index, status})),
    {...data.operation, operation_id: "foreign_project", intent: {...data.operation.intent, project_id: "other_project"}},
    {...data.operation, operation_id: "foreign_request", intent: {...data.operation.intent, delivery_id: "other_request"}},
    {...data.operation, operation_id: "lifecycle", intent: {...data.operation.intent, action: "CLOSE_REQUIREMENT"}},
    {...data.operation, operation_id: "inspection", intent: {...data.operation.intent, action: "INSPECT_DELIVERY_WAIT"}});`);
  const rendered = rows(h.render());
  assert.equal(rendered.length, 7);
  assert.equal(rendered.filter(row => text(row).includes("当前阶段 ·")).length, 1);
  h.data.operation.status = "QUEUED";
  const queued = rows(h.render()).find(row => text(row).includes("operation_current"));
  assert.doesNotMatch(text(queued), /当前阶段 ·|技术设计/);
  assert.match(text(queued), /等待 Manager 处理/);
});

test("same delivery ID in another project cannot steal live progress from the exact operation", () => {
  const h = harness();
  h.run(`operations.unshift({...data.operation, operation_id: "foreign_project", intent: {...data.operation.intent,
    project_id: "other_project"}});`);
  assert.match(text(rows(h.render())[0]), /当前阶段 · 技术设计 · 执行中/);
  h.run(`data.request.stage = "DELIVERING"; snapshot.tasks = [{id: "task_current", request_id: data.request.id,
    project_id: data.request.project_id, status: "NEW", terminal: false, last_activity: "2026-10-05T13:00:00Z",
    role_queue: []}];`);
  assert.match(text(rows(h.render())[0]), /当前阶段 · 待启动 · 准备执行/);
  assert.match(text(rows(h.render())[0]), /平台正在准备已批准的执行计划/);
});

test("native unknown or queued role is never painted as running by the active command", () => {
  const h = harness();
  h.run(`data.request.stage = "DELIVERING"; snapshot.tasks = [{id: "task_current", request_id: data.request.id,
    project_id: data.request.project_id, status: "IMPLEMENTING", terminal: false, last_activity: "2026-10-05T13:00:00Z",
    role_queue: []}];`);
  assert.match(text(rows(h.render())[0]), /当前阶段 · 实现 · 等待工程处理/);
  assert.match(text(rows(h.render())[0]), /工程团队核验当前执行和现场后继续/);
  assert.doesNotMatch(rows(h.render())[0].children[0].textContent, /执行中/);
  h.run('snapshot.tasks[0].role_queue = [{role: "coder", status: "READY", lease_liveness: "UNKNOWN"}]');
  assert.match(text(rows(h.render())[0]), /当前阶段 · 实现 · 已排队/);
  assert.match(text(rows(h.render())[0]), /请等待团队领取当前工作/);
});

test("opaque identity and input version stay in labeled collapsed troubleshooting details", () => {
  const h = harness();
  const row = rows(h.render())[0];
  const technical = descend(row).find(node => node.tagName === "DETAILS");
  assert.equal(technical.children[0].textContent, "排障信息（供工程人员使用）");
  assert.notEqual(technical.open, true);
  assert.match(text(technical), /发起操作时的需求版本摘要/);
  assert.match(text(technical), new RegExp("a".repeat(64)));
  assert.doesNotMatch(text(technical), new RegExp("b".repeat(64)));
  assert.match(text(technical), /这些标识用于工程核验，无需产品负责人填写/);
});

test("active notice follows exact phase without changing its acknowledgement key", () => {
  const h = harness();
  const before = h.run("operationNoticeFor(data.operation)");
  assert.match(before.message, /当前阶段 · 技术设计 · 执行中/);
  h.data.request.stage = "PLANNING";
  const after = h.run("operationNoticeFor(data.operation)");
  assert.match(after.message, /当前阶段 · 计划编排 · 执行中/);
  assert.equal(after.key, before.key);
  h.data.operation.intent.project_id = "other_project";
  assert.doesNotMatch(h.run("operationNoticeFor(data.operation).message"), /当前阶段 ·|计划编排/);
});

test("succeeded delivery history reports its sealed blocked, waiting or done result instead of product success", () => {
  const h = harness();
  const titles = {BLOCKED: "操作已结束 · 当次交付已阻塞", WAITING_HUMAN: "操作已结束 · 当次交付等待处理",
    DONE: "操作已结束 · 当次需求已交付"};
  for (const [stage, expected] of Object.entries(titles)) {
    h.data.operation.status = "SUCCEEDED";
    h.data.operation.result = {stage, next_action: "查看当次执行记录。"};
    const original = JSON.stringify(h.data.operation);
    const row = rows(h.render())[0];
    assert.equal(row.children[0].textContent, expected);
    assert.match(text(row), /发起操作 · 继续交付/);
    assert.match(text(row), /命令已完成/);
    assert.equal(descend(row).find(node => node.textContent === "命令已完成").className, "badge", "completed commands have a static neutral badge");
    assert.doesNotMatch(text(row), /执行成功|当前阶段 ·/);
    assert.equal(JSON.stringify(h.data.operation), original);
    h.data.request.stage = "DONE";
    assert.equal(rows(h.render())[0].children[0].textContent, expected, "later Requirement facts never overwrite the sealed outcome");
  }
  h.data.operation.result = null;
  const noResult = text(rows(h.render())[0]);
  assert.match(noResult, /命令已完成/);
  assert.doesNotMatch(noResult, /当次需求已交付|当次交付已阻塞|当前阶段 ·|执行成功/);
  for (const stage of ["DESIGNING", "PLANNING", "CLOSED", "unknown_result", "toString"]) {
    h.data.operation.result = {stage, next_action: "查看当次记录。"};
    assert.doesNotMatch(text(rows(h.render())[0]), /当次需求已交付|当前阶段 ·/);
  }
  h.data.operation.result = {stage: "DONE", next_action: "项目操作完成。"};
  h.data.operation.intent.action = "CLOSE_REQUIREMENT";
  assert.doesNotMatch(text(rows(h.render())[0]), /当次需求已交付/);
});

test("sealed outcome diagnostic and current missing planning handoff render exact Chinese without altering facts", () => {
  const h = harness();
  const original = "Designer did not publish a verified planning handoff";
  h.data.operation.status = "SUCCEEDED";
  h.data.operation.result = {stage: "BLOCKED", diagnostic: original, next_action: "工程团队核验交接记录后继续。"};
  assert.match(text(rows(h.render())[0]), /当次原因 · 设计到计划的交接尚未通过校验，当前交付已阻塞/);
  assert.match(h.run('humanizeBlockingText(data.operation.result.diagnostic)'), /由工程团队核验具体原因并处理/);
  assert.equal(h.data.operation.result.diagnostic, original);
  h.context.quoted = `用户原文引用：${original}`;
  assert.equal(h.run("humanizeBlockingText(quoted)"), h.context.quoted);
});
