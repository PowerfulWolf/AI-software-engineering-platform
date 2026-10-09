const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { supportedActions } = require("./console-capabilities-fixture.cjs");

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.events = {};
    this.dataset = {};
    this.attributes = {};
    this.textContent = "";
  }
  append(...nodes) { this.children.push(...nodes); }
  get classList() {
    return {add: (...tokens) => {
      this.className = [...new Set([...(this.className || "").split(/\s+/).filter(Boolean), ...tokens])].join(" ");
    }};
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, fn) { this.events[key] = fn; }
  set innerHTML(value) { throw new Error("Unsafe HTML: " + value); }
}
const descend = node => [node, ...node.children.filter(item => typeof item !== "string").flatMap(descend)];
const text = node => node.textContent + node.children.map(item => typeof item === "string" ? item : text(item)).join(" ");
const control = (node, name) => descend(node).find(item => item.tagName === "BUTTON" && item.textContent === name);
const digest = value => value.repeat(64);

function fixture() {
  const facts = {task_id: "task_current", work_item_id: "work_current", role: "coder",
    task_intent_sha256: digest("b"), source_revision: digest("c"), checkpoint_sequence: 4};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_HUMAN",
    wait_disposition_sha256: digest("d"), wait_disposition: {facts, responsibility: "engineering",
      reason: "执行结果待核验，现场保留。", next_action: "工程授权者调查原执行。"}};
  const request = {id: "requirement_current", project_id: "project_current", title: "交付需求",
    checkpoint_sha256: digest("a"), stage: "DELIVERING", scopes: [{delivery_id: "delivery_current"}], documents: [],
    execution: {state: "WAITING", responsibility: "engineering", reason_code: "EXECUTION_UNCERTAIN",
      reason: step.wait_disposition.reason, next_action: step.wait_disposition.next_action}};
  const task = {id: "delivery_current", task_id: facts.task_id, request_id: request.id,
    status: "IMPLEMENTING", terminal: false, last_activity: "2026-10-05T00:00:00Z", role_queue: [step]};
  return {request, task, step};
}

function harness() {
  const data = fixture();
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data, supportedActions});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  // Load the actual UI functions without starting navigation, polling or network work.
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  vm.runInContext(`snapshot = {team_id: "team_current", selected_project_id: "project_current",
    projects: [], agents: [], tasks: [data.task], requests: [data.request]};
    consoleTeamId = "team_current"; consoleAvailable = true; consoleDeliveryReady = true;
    consoleOperationContractVersion = 1; consoleSupportedActions = [...supportedActions];
    operationsAvailable = true; globalThis.submitted = [];
    submitOperation = async intent => { submitted.push(intent); return {operation_id: "accepted"}; };
    renderDetail = () => {}; renderNotification = () => {};`, context);
  return {context, ...data, run: code => vm.runInContext(code, context)};
}

function investigation(h, missing = []) {
  const proof = {task_id: h.task.task_id, work_item_id: h.step.work_item_id,
    disposition_sha256: h.step.wait_disposition_sha256, task_intent_sha256: digest("b"),
    source_revision: digest("c"), checkpoint_sequence: 4, proof_sha256: digest("e"),
    missing, permitted_resolutions: missing.length ? [] : ["RETRY_FROM_CHECKPOINT"],
    inspected_at: "2026-10-05T01:00:00Z", next_action: "按已封存现场继续原交付。"};
  h.context.proof = proof;
  h.run(`operations = [{operation_id: "inspect_current", status: "SUCCEEDED",
    updated_at: "2026-10-05T01:00:00Z",
    intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
    result: {engineering_wait_investigation: proof, checkpoint_sha256: data.request.checkpoint_sha256}}];`);
  return proof;
}
function handling(h, status = "PLATFORM_ATTENTION", missing = ["STOP_UNRECORDED"], manual = false) {
  const proof = investigation(h, missing);
  const result = {kind: "delivery_wait_handling", schema_version: "v1", task_id: proof.task_id,
    work_item_id: proof.work_item_id, disposition_sha256: proof.disposition_sha256,
    task_intent_sha256: proof.task_intent_sha256, source_revision: proof.source_revision,
    checkpoint_sequence: proof.checkpoint_sequence, investigation: proof, status,
    manual_resolution_allowed: manual, handling_sha256: digest("f"), handled_at: "2026-10-05T02:00:00Z",
    summary: "平台未找到原执行的完整结束记录，当前不能安全继续。",
    user_action: "将处理报告交给平台维护者，无需自行确认内部执行记录。",
    recheck_when: "平台补齐结束记录后再检查。"};
  h.context.handling = result;
  h.run(`operations[0].intent.action = "HANDLE_DELIVERY_WAIT";
    operations[0].result = {engineering_wait_handling: handling, checkpoint_sha256: data.request.checkpoint_sha256};`);
  return result;
}

test("product handling submits the exact wait without supplying engineering authority or stop facts", async () => {
  const h = harness();
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /发生了什么/);
  assert.match(text(box), /开发进度/);
  assert.match(text(box), /平台可以做什么/);
  assert.match(text(box), /你需要做什么/);
  await control(box, "让平台处理中断").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[0])"));
  assert.deepEqual(intent, {...JSON.parse(h.run("JSON.stringify(engineeringWaitIntent(data.request, data.step))")),
    action: "HANDLE_DELIVERY_WAIT"});
  assert.deepEqual(Object.keys(intent).sort(), ["action", "project_id", "delivery_id", "expected_checkpoint_sha256",
    "work_item_id", "expected_disposition_sha256", "expected_task_intent_sha256", "expected_source_revision",
    "expected_checkpoint_sequence"].sort());
});

test("handling with missing records names the platform owner and meaningful recheck without claiming repair", () => {
  const h = harness();
  handling(h);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /平台未找到原执行的完整结束记录/);
  assert.match(text(box), /处理方 · 平台执行服务或维护者/);
  assert.match(text(box), /平台补齐结束记录后再检查/);
  assert.equal(control(box, "重新检查状态").className, "secondary");
  assert.equal(control(box, "复制处理报告").textContent, "复制处理报告");
  assert.equal(control(box, "继续原交付"), undefined);
  assert.equal(control(box, "让平台处理中断"), undefined, "unchanged maintenance failures do not encourage repeated handling");
  assert.doesNotMatch(text(box), /Manager.*(?:正在|已经)|平台已修复|确认.*可信停止/);
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
});

test("retained complete proof cannot present readiness after platform collection is rejected", async () => {
  const h = harness();
  const result = handling(h, "PLATFORM_ATTENTION", [], false);
  result.collection_failed = true;
  result.summary = "平台未通过执行事实收集校验，需要维护者处理，原工作区和记录已保留。";
  result.user_action = "复制处理报告交给平台维护者。";
  Object.assign(result.investigation, {interruption_receipt_sha256: digest("1"),
    process_stop_sha256: digest("2"), workspace_inventory_sha256: digest("3")});
  const before = JSON.stringify(result.investigation);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /部分执行事实已核验，但收集校验失败，当前不能继续/);
  assert.doesNotMatch(text(box), /检查已通过，可按以下方案继续/);
  assert.equal(control(box, "继续原交付"), undefined);
  assert.equal(JSON.stringify(result.investigation), before, "presentation does not modify the sealed proof");
  h.context.navigator = {clipboard: {writeText: async value => {h.context.copiedReport = value;}}};
  await control(box, "复制处理报告").events.click();
  assert.match(h.context.copiedReport, /收集校验失败，当前不能继续/);
  assert.doesNotMatch(h.context.copiedReport, /检查已通过|已恢复|已交付/);
  assert.match(h.context.copiedReport, /任务 · task_current/);
  assert.match(h.context.copiedReport, /工作项 · work_current/);
  assert.match(h.context.copiedReport, /处理报告摘要 · f{64}/);
  const panel = new Element("section");
  h.context.panel = panel;
  h.run("requestOperationHistory(panel, data.request)");
  assert.match(text(panel), /当次调查/);
  assert.match(text(panel), /按已封存现场继续原交付/);
  assert.doesNotMatch(text(panel), /检查已通过，可按以下方案继续/);
});

test("copied maintenance report includes Chinese missing items and exact diagnostic identities", async () => {
  const h = harness();
  const result = handling(h);
  result.investigation.original_run_id = "run_original";
  h.context.navigator = {clipboard: {writeText: async value => {h.context.copiedReport = value;}}};
  await control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "复制处理报告").events.click();
  assert.match(h.context.copiedReport, /待处理事项 · 原执行是否已结束还没有可靠记录/);
  assert.match(h.context.copiedReport, /处理方 · 平台执行服务或维护者/);
  assert.match(h.context.copiedReport, /具体处理 · 平台需记录原执行的实际结束情况/);
  assert.match(h.context.copiedReport, /原执行 · run_original/);
  assert.doesNotMatch(h.context.copiedReport, /STOP_UNRECORDED/);
});

test("manual resolution requires a current complete handling proof and explicit engineering permission", async () => {
  for (const allowed of [false, true]) {
    const h = harness();
    const result = handling(h, "NEEDS_AUTHORIZATION", [], allowed);
    result.summary = "已完成检查，继续前需要工程授权者确认所列方案。";
    result.user_action = "请工程授权者确认按页面所列方案继续。";
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    assert.match(text(box), /确认按页面所列方案继续/);
    if (!allowed) {
      assert.equal(control(box, "继续原交付"), undefined);
      h.run(`operations.push({...operations[0], operation_id: "newer_inspection", updated_at: "2026-10-05T03:00:00Z",
        intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
        result: {engineering_wait_investigation: proof, checkpoint_sha256: data.request.checkpoint_sha256}});`);
      assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "继续原交付"), undefined,
        "a fresh investigation cannot restore engineering permission that the handler explicitly denied");
      continue;
    }
    await control(box, "继续原交付").events.click();
    assert.equal(h.run("submitted[0].action"), "RESOLVE_DELIVERY_WAIT");
    assert.equal(h.run("submitted[0].proof_sha256"), digest("e"));
    assert.equal(h.run("submitted[0].resolution_kind"), "RETRY_FROM_CHECKPOINT");
  }
});

test("unknown missing and resolution kinds remain Chinese and cannot become an approval", () => {
  const h = harness();
  investigation(h, ["FUTURE_UNRECOGNIZED_CHECK"]);
  let box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /平台返回了未识别的检查项/);
  assert.match(text(box), /平台维护者/);
  assert.doesNotMatch(text(box), /FUTURE_UNRECOGNIZED_CHECK/);
  assert.equal(control(box, "继续原交付"), undefined);
  const proof = investigation(h);
  proof.permitted_resolutions.push("FUTURE_UNRECOGNIZED_RESOLUTION");
  box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /当前没有可安全执行的继续方案/);
  assert.equal(control(box, "继续原交付"), undefined, "an unknown resolution invalidates the approval set");
});

test("newer failed handling or investigation invalidates a previously usable proof", async () => {
  for (const action of ["INSPECT_DELIVERY_WAIT", "HANDLE_DELIVERY_WAIT"]) {
    const h = harness();
    investigation(h);
    const old = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    h.context.failureAction = action;
    h.run(`operations.push({operation_id: "failed_newer", status: "FAILED", updated_at: "2026-10-05T02:00:00Z",
      intent: {...engineeringWaitIntent(data.request, data.step), action: failureAction}});`);
    assert.equal(h.run("engineeringWaitProof(data.request, data.step)"), null);
    assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "继续原交付"), undefined);
    await control(old, "继续原交付").events.click();
    assert.equal(h.run("submitted.length"), 0, "old proof closures cannot submit after the new failure");
  }
});

test("handling progress only claims work for the exact active wait and reports preservation from receipts", () => {
  const h = harness();
  h.run(`operations = [{operation_id: "active_handle", status: "RUNNING", updated_at: "2026-10-05T02:00:00Z",
    intent: {...engineeringWaitIntent(data.request, data.step), action: "HANDLE_DELIVERY_WAIT"}}];`);
  assert.match(text(h.run("engineeringWaitBox(data.request, data.task, data.step)")), /平台正在处理中断/);
  h.run('operations[0].intent.expected_disposition_sha256 = "f".repeat(64)');
  assert.doesNotMatch(text(h.run("engineeringWaitBox(data.request, data.task, data.step)")), /平台正在处理中断/);
  h.run('operations[0].intent.project_id = "foreign_project"');
  assert.ok(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "让平台处理中断"));
  const proof = investigation(h);
  assert.doesNotMatch(text(h.run("engineeringWaitBox(data.request, data.task, data.step)")), /已记录可核验的开发进度/);
  Object.assign(proof, {interruption_receipt_sha256: digest("1"), process_stop_sha256: digest("2"),
    workspace_inventory_sha256: digest("3")});
  assert.match(text(h.run("engineeringWaitBox(data.request, data.task, data.step)")), /已记录可核验的开发进度/);
});

test("handling decisions preserve the durable wait and history labels investigations as past facts", () => {
  const h = harness();
  const result = handling(h, "RESOLVED", []);
  result.resolution = {kind: "delivery_wait_resolution", resolution_kind: "RETRY_FROM_CHECKPOINT",
    proof_sha256: result.investigation.proof_sha256, authorization_source: "organization_engineering_policy"};
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /继续决定已记录/);
  assert.equal(control(box, "继续原交付"), undefined);
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
  h.context.panel = new Element("section");
  h.run("requestOperationHistory(panel, data.request)");
  assert.match(text(h.context.panel), /当次平台处理/);
  assert.match(text(h.context.panel), /当次调查/);
  assert.doesNotMatch(text(h.context.panel), /当前尚未解决的事项/);
  h.run(`operations.push({operation_id: "inspect_after_decision", status: "SUCCEEDED",
    updated_at: "2026-10-05T03:00:00Z",
    intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
    result: {engineering_wait_investigation: {...proof, inspected_at: "2026-10-05T03:00:00Z",
      proof_sha256: "1".repeat(64)}, checkpoint_sha256: data.request.checkpoint_sha256}});`);
  const refreshed = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(refreshed), /继续决定已记录/);
  assert.equal(control(refreshed, "让平台处理中断"), undefined,
    "a timestamp-only investigation cannot invite repeating a recorded decision");
});

test("a later investigation with identical facts and a new timestamp keeps the handling explanation", () => {
  const h = harness();
  const result = handling(h, "NEEDS_AUTHORIZATION", [], true);
  result.summary = "平台已完成检查，等待工程授权者决定。";
  result.user_action = "请工程授权者确认所列方案。";
  h.run(`operations.push({operation_id: "inspect_after_handling", status: "SUCCEEDED",
    updated_at: "2026-10-05T03:00:00Z",
    intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
    result: {engineering_wait_investigation: {...proof, inspected_at: "2026-10-05T03:00:00Z",
      proof_sha256: "1".repeat(64), prerequisite_receipt_sha256: "2".repeat(64)},
      checkpoint_sha256: data.request.checkpoint_sha256}});`);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /平台已完成检查，等待工程授权者决定/);
  assert.match(text(box), /请工程授权者确认所列方案/);
  assert.match(text(box), /等待工程授权者决定/);
});

test("a changed or failed later investigation keeps old handling in history and removes current advice", () => {
  for (const newerStatus of ["SUCCEEDED", "FAILED"]) {
    const h = harness();
    const result = handling(h, "NEEDS_AUTHORIZATION", [], false);
    result.summary = "旧处理已核验全部条件。";
    result.user_action = "按旧方案继续。";
    result.recheck_when = "旧方案授权后复查。";
    h.context.newerStatus = newerStatus;
    h.run(`operations.push({operation_id: "inspect_changed", status: newerStatus,
      updated_at: "2026-10-05T03:00:00Z",
      intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
      result: {engineering_wait_investigation: {...proof, inspected_at: "2026-10-05T03:00:00Z",
        proof_sha256: "1".repeat(64), missing: ["CHECKPOINT_DRIFT"], permitted_resolutions: []},
        checkpoint_sha256: data.request.checkpoint_sha256}});`);
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    assert.equal(h.run("engineeringWaitHandling(data.request, data.step)"), null);
    assert.doesNotMatch(text(box), /旧处理已核验全部条件|按旧方案继续|旧方案授权后复查/);
    assert.equal(control(box, "继续原交付"), undefined);
    if (newerStatus === "SUCCEEDED") assert.match(text(box), /保留的工作区已经变化/);

    const panel = new Element("section");
    h.context.panel = panel;
    h.run("requestOperationHistory(panel, data.request)");
    assert.match(text(panel), /旧处理已核验全部条件/);
    assert.match(text(panel), /按旧方案继续/);

    h.run(`operations.push({operation_id: "inspect_complete_again", status: "SUCCEEDED",
      updated_at: "2026-10-05T04:00:00Z",
      intent: {...engineeringWaitIntent(data.request, data.step), action: "INSPECT_DELIVERY_WAIT"},
      result: {engineering_wait_investigation: {...proof, inspected_at: "2026-10-05T04:00:00Z",
        proof_sha256: "3".repeat(64), workspace_inventory_sha256: "4".repeat(64)},
        checkpoint_sha256: data.request.checkpoint_sha256}});`);
    assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "继续原交付"), undefined,
      "changed facts cannot restore permission that handling denied");
  }
});

test("accepted inconclusive QA retains safe environment reason without findings", () => {
  const h = harness();
  h.context.qaEntry = {id: "art_qa_wait", details: {kind: "qa-report", status: "FAIL",
    findings: [], environment: {reason: "增量测试入口尚未执行。", diagnostic: "<script>unsafe</script>"}}};
  const box = h.run('(() => { const target = el("section"); appendExecutionArtifactDetails(target, qaEntry); return target; })()');
  assert.match(text(box), /QA 验证环境与未完成原因/);
  assert.match(text(box), /增量测试入口尚未执行/);
  assert.match(text(box), /<script>unsafe<\/script>/);
  assert.equal(descend(box).some(node => node.tagName === "SCRIPT"), false);
  const fold = descend(box).find(node => node.tagName === "DETAILS");
  assert.notEqual(fold.open, true);
});

test("engineering wait controls submit exact facts and only the sealed permitted resolution", async () => {
  const h = harness();
  let box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  await control(box, "调查工程等待").events.click();
  assert.deepEqual(JSON.parse(h.run("JSON.stringify(submitted[0])")), {
    action: "INSPECT_DELIVERY_WAIT", project_id: h.request.project_id, delivery_id: h.request.id,
    expected_checkpoint_sha256: digest("a"), work_item_id: "work_current",
    expected_disposition_sha256: digest("d"), expected_task_intent_sha256: digest("b"),
    expected_source_revision: digest("c"), expected_checkpoint_sequence: 4,
  });
  investigation(h);
  box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  await control(box, "继续原交付").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[1])"));
  assert.equal(intent.action, "RESOLVE_DELIVERY_WAIT");
  assert.equal(intent.proof_sha256, digest("e"));
  assert.equal(intent.resolution_kind, "RETRY_FROM_CHECKPOINT");
  assert.equal(Object.hasOwn(intent, "process_stopped"), false);
  assert.equal(Object.hasOwn(intent, "operator_id"), false);
  assert.equal(Object.hasOwn(intent, "retry_cause"), false);
});

test("unknown stop proof remains an engineering wait with explicit missing facts and no resolution", () => {
  const h = harness();
  investigation(h, ["STOP_UNRECORDED", "PROCESS_LIVE_OR_UNKNOWN"]);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /原执行是否已结束还没有可靠记录/);
  assert.match(text(box), /原工作可能仍在运行/);
  assert.match(text(box), /处理方 · 平台执行服务/);
  assert.match(text(box), /重复调查不会补齐旧执行记录/);
  assert.equal(control(box, "继续原交付"), undefined);
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
  h.run('operations[0].status = "RUNNING"');
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
});

test("rejected recorded outcomes show a Chinese engineering action without replay controls", () => {
  const h = harness();
  investigation(h, ["OUTCOME_REJECTED", "STOP_UNRECORDED"]);
  h.context.proof.next_action = "原产出已被拒绝，工程团队需修复契约并核验真实停机现场。";
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /原产出已被拒绝/);
  assert.match(text(box), /不能重复接纳/);
  assert.match(text(box), /修复契约并核验真实停机现场/);
  assert.equal(control(box, "使用已保存结果继续"), undefined);
  assert.equal(control(box, "继续原交付"), undefined);
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
});

test("recorded result replay and unused preflight resume expose only the service-permitted kind", async () => {
  const names = {REPLAY_RECORDED_RESULT: "使用已保存结果继续", RESUME_UNINVOKED: "继续未开始的工作",
    REVERIFY_CANDIDATE: "重新测试当前候选",
    RETRY_VERIFIER_PREPARATION: "重试验证准备"};
  for (const [kind, name] of Object.entries(names)) {
    const h = harness();
    const proof = investigation(h);
    proof.permitted_resolutions = [kind];
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    assert.equal(control(box, "继续原交付"), undefined);
    await control(box, name).events.click();
    assert.equal(h.run("submitted[0].resolution_kind"), kind);
    h.run('operations.push({operation_id: "running", status: "RUNNING", intent: {delivery_id: data.request.id, project_id: data.request.project_id}})');
    assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), name), undefined);
    assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
  }
});

test("stale checkpoint, disposition or proof cannot be submitted through an old control", async () => {
  for (const mutation of [
    'data.request.checkpoint_sha256 = "f".repeat(64)',
    'data.step.wait_disposition_sha256 = "f".repeat(64)',
    'operations[0].result.engineering_wait_investigation.proof_sha256 = "f".repeat(64)',
  ]) {
    const h = harness();
    investigation(h);
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    h.run(mutation);
    await control(box, "继续原交付").events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
    if (!mutation.includes("proof_sha256"))
      assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "继续原交付"), undefined);
  }
});

test("engineering decision keeps the durable wait visible and all operation records beyond eight", () => {
  const h = harness();
  investigation(h);
  h.run(`operations.push({operation_id: "resolve_current", status: "SUCCEEDED",
    updated_at: "2026-10-05T02:00:00Z",
    intent: {...engineeringWaitIntent(data.request, data.step), action: "RESOLVE_DELIVERY_WAIT", proof_sha256: proof.proof_sha256},
    result: {engineering_wait_resolution: {kind: "delivery_wait_resolution", resolution_kind: "RETRY_FROM_CHECKPOINT", proof_sha256: proof.proof_sha256,
      authorization_source: "engineering_operator_decision", operator_principal: {operator_id: "operator:actual"}}}});
    for (let index = 0; index < 10; index++) operations.push({operation_id: "old_" + index,
      status: "SUCCEEDED", updated_at: "2026-10-04T00:00:00Z", intent: {delivery_id: data.request.id,
      project_id: data.request.project_id, action: "CONTINUE_DELIVERY"}, result: {next_action: "<img onerror=evil>"}});`);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /决定已记录/);
  assert.equal(control(box, "继续原交付"), undefined);
  assert.match(text(h.run("productExecutionSummary(data.request)")), /等待工程处理/);
  const panel = new Element("div");
  h.context.panel = panel;
  h.run("requestOperationHistory(panel, data.request)");
  assert.match(text(panel), /共 12 条操作/);
  assert.match(text(panel), /operator:actual/);
  assert.match(text(panel), /<img onerror=evil>/);
  assert.equal(descend(panel).filter(node => node.tagName === "LI").length, 12);
});

test("task execution history renders investigation and handling facts in Chinese", () => {
  const h = harness();
  const target = new Element("ol");
  h.context.target = target;
  h.run(`appendExecutionEntry(target, {id: "entry_investigation", task_id: data.task.task_id,
    summary: "平台调查工程等待", occurred_at: "2026-10-05T02:00:00Z", source_uri: "sidecar://events/1",
    details: {kind: "delivery_wait_investigation", missing: ["STOP_UNRECORDED", "FUTURE_UNKNOWN"]}}, data.task.task_id);`);
  assert.match(text(target), /原执行是否已结束还没有可靠记录/);
  assert.match(text(target), /平台返回了未识别的检查项/);
  assert.doesNotMatch(text(target), /FUTURE_UNKNOWN/);

  h.run(`appendExecutionEntry(target, {id: "entry_handling", task_id: data.task.task_id,
    summary: "平台处理中断", occurred_at: "2026-10-05T03:00:00Z", source_uri: "sidecar://events/2",
    details: {kind: "delivery_wait_handling", status: "NEEDS_AUTHORIZATION",
      summary: "已完成检查，继续前需要工程授权者确认。", user_action: "请工程授权者确认所列方案。",
      recheck_when: "授权记录保存后再检查。", authorization_source: "organization_engineering_policy",
      handling_sha256: "f".repeat(64)}}, data.task.task_id);`);
  assert.match(text(target), /等待工程决定/);
  assert.match(text(target), /当次用户操作/);
  assert.match(text(target), /平台按已授权组织工程策略继续（不是人工批准）/);

  h.run(`appendExecutionEntry(target, {id: "entry_unknown_resolution", task_id: data.task.task_id,
    summary: "工程处理结果", occurred_at: "2026-10-05T04:00:00Z", source_uri: "sidecar://events/3",
    details: {kind: "delivery_wait_resolution", resolution_kind: "FUTURE_RESOLUTION"}}, data.task.task_id);`);
  assert.match(text(target), /平台返回了未识别的继续方案，不能据此执行/);
  assert.doesNotMatch(text(target), /FUTURE_RESOLUTION/);
});

function baselineFixture(h) {
  h.task.task_revision = 4;
  h.task.task_intent_sha256 = digest("b");
  h.step.wait_disposition.facts.source_revision = "c".repeat(40);
}
function baselinePlan(h, conflicted = false, mode = "preserve_draft") {
  const plan = {plan_sha256: digest("e"), target_base_ref: "f".repeat(40), input_mode: mode,
    conflicted, dirty_capture: {source_revision: "c".repeat(40)},
    facts: {task: {id: h.task.task_id, branch_name: "ai/feature/original"}, task_revision: 4,
      work_item_id: h.step.work_item_id}};
  h.context.baselinePlan = plan;
  h.run(`operations = [{operation_id: "baseline_proposal", status: "SUCCEEDED", updated_at: "2026-10-05T01:00:00Z",
    intent: {...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE",
      target_base_ref: baselinePlan.target_base_ref, input_mode: baselinePlan.input_mode},
    result: {checkpoint_sha256: data.request.checkpoint_sha256, execution_baseline_plan: baselinePlan}}];`);
  return plan;
}

test("baseline engineering controls bind original task and sealed exact plan", async () => {
  const h = harness();
  baselineFixture(h);
  let box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.equal(control(box, "批准并更新原分支基线"), undefined);
  const input = descend(box).find(node => node.tagName === "INPUT");
  input.value = "f".repeat(40);
  await control(box, "调查并保留原草稿").events.click();
  assert.deepEqual(JSON.parse(h.run("JSON.stringify(submitted[0])")), {
    action: "PROPOSE_EXECUTION_BASELINE", project_id: h.request.project_id, delivery_id: h.request.id,
    expected_checkpoint_sha256: digest("a"), task_id: h.task.task_id,
    expected_task_intent_sha256: digest("b"), expected_task_revision: 4,
    expected_work_item_id: h.step.work_item_id, expected_source_revision: "c".repeat(40),
    target_base_ref: "f".repeat(40), input_mode: "preserve_draft",
  });
  baselinePlan(h);
  box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /ai\/feature\/original/);
  await control(box, "批准并更新原分支基线").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[1])"));
  assert.equal(intent.action, "EXECUTE_EXECUTION_BASELINE");
  assert.equal(intent.expected_plan_sha256, digest("e"));
  assert.equal(intent.expected_checkpoint_sha256, digest("a"));
  assert.equal(Object.hasOwn(intent, "operator_id"), false);
  assert.equal(Object.hasOwn(intent, "process_stopped"), false);
});

test("baseline conflicts require a new explicit coder reapply plan before execution", async () => {
  const h = harness();
  baselineFixture(h);
  baselinePlan(h, true);
  let box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.equal(control(box, "批准并更新原分支基线"), undefined);
  await control(box, "提出 Coder 适配完整旧补丁的计划").events.click();
  assert.equal(h.run("submitted[0].input_mode"), "coder_reapply");
  assert.equal(h.run("submitted[0].action"), "PROPOSE_EXECUTION_BASELINE");
  baselinePlan(h, false, "coder_reapply");
  box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /读取完整旧补丁并适配/);
  await control(box, "批准并更新原分支基线").events.click();
  assert.equal(h.run("submitted[1].action"), "EXECUTE_EXECUTION_BASELINE");
});

test("stale baseline plans and QA stages cannot update the original coder branch", async () => {
  for (const mutation of [
    'data.request.checkpoint_sha256 = "f".repeat(64)',
    'data.task.task_revision = 5',
    'operations[0].result.execution_baseline_plan.plan_sha256 = "f".repeat(64)',
  ]) {
    const h = harness();
    baselineFixture(h);
    baselinePlan(h);
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    h.run(mutation);
    await control(box, "批准并更新原分支基线").events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
  const h = harness();
  baselineFixture(h);
  h.task.status = "QA";
  h.step.role = "qa";
  assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "调查并保留原草稿"), undefined);
});

function legacyRescueFixture(h) {
  baselineFixture(h);
  const result = handling(h, "PLATFORM_ATTENTION", ["OUTCOME_UNKNOWN", "STOP_UNRECORDED", "CHECKPOINT_UNAVAILABLE"]);
  result.source_revision = "c".repeat(40);
  result.investigation.source_revision = "c".repeat(40);
  result.investigation.original_run_id = "run_original";
  h.run("consoleOperationContractVersion = 2");
  return result;
}
function legacyRescuePlan(h) {
  const plan = {plan_sha256: digest("1"), purpose: "legacy_workspace_rescue",
    target_base_ref: "c".repeat(40), input_mode: "preserve_draft", conflicted: false,
    dirty_capture: {source_revision: "c".repeat(40)}, facts: {task: {id: h.task.task_id,
      branch_name: "ai/feature/original"}, task_revision: 4, work_item_id: h.step.work_item_id,
      legacy_containment: {original_start: {request: {run_id: "run_original"}, work_item_id: h.step.work_item_id,
        started_at: "2026-10-05T01:00:00Z", start_sha256: digest("2")},
        boot: {booted_at: "2026-10-06T01:00:00Z", machine_sha256: digest("3"), boot_session_sha256: digest("4")},
        containment_sha256: digest("5")}}};
  h.context.rescuePlan = plan;
  h.run(`operations.push({operation_id: "legacy_proposal", status: "SUCCEEDED", updated_at: "2026-10-06T02:00:00Z",
    intent: {...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE",
      purpose: "legacy_workspace_rescue", target_base_ref: rescuePlan.target_base_ref, input_mode: "preserve_draft"},
    result: {checkpoint_sha256: data.request.checkpoint_sha256, execution_baseline_plan: rescuePlan}});`);
  return plan;
}

test("legacy unknown execution offers a visible precise preservation path without asking for a SHA", async () => {
  const h = harness();
  const result = legacyRescueFixture(h);
  const original = JSON.stringify(result);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const rescue = descend(box).find(node => (node.className || "").includes("engineering-rescue-panel"));
  assert.equal(rescue.tagName, "SECTION");
  assert.match(text(rescue), /不会新建需求或丢弃原分支的合法草稿/);
  assert.match(text(rescue), /旧执行结果仍未知/);
  assert.match(text(rescue), /下一轮使用剩余工作额度/);
  assert.match(text(rescue), /先由平台检查当前本机执行和保留进度/);
  assert.equal(descend(rescue).some(node => node.tagName === "INPUT"), false);
  await control(rescue, "准备保留进度的恢复方案").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[0])"));
  assert.equal(intent.purpose, "legacy_workspace_rescue");
  assert.equal(intent.target_base_ref, h.step.wait_disposition.facts.source_revision);
  assert.equal(intent.input_mode, "preserve_draft");
  assert.equal(intent.expected_task_revision, 4);
  assert.equal(Object.hasOwn(intent, "confirm_legacy_containment"), false, "preparation cannot attest for the user");
  assert.equal(JSON.stringify(result), original, "current advice never rewrites a historical handling report");
});

test("engineering approval requires the explicit same computer and whole computer restart confirmation", async () => {
  const h = harness();
  legacyRescueFixture(h);
  legacyRescuePlan(h);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const rescue = descend(box).find(node => (node.className || "").includes("engineering-rescue-panel"));
  assert.match(text(rescue), /原执行开始/);
  assert.match(text(rescue), /方案核验的整机启动/);
  assert.match(text(rescue), /工程授权者身份/);
  assert.match(text(rescue), /未迁移或远程执行/);
  const approve = control(rescue, "批准保留进度并继续原需求");
  const checkbox = descend(rescue).find(node => node.tagName === "INPUT" && node.type === "checkbox");
  assert.equal(approve.disabled, true);
  await approve.events.click();
  assert.equal(h.run("submitted.length"), 0, "even a retained closure cannot bypass unchecked confirmation");
  checkbox.checked = true;
  checkbox.events.change();
  assert.equal(approve.disabled, false);
  await approve.events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[0])"));
  assert.equal(intent.action, "EXECUTE_EXECUTION_BASELINE");
  assert.equal(intent.confirm_legacy_containment, true);
  assert.equal(intent.expected_plan_sha256, digest("1"));
  assert.equal(Object.hasOwn(intent, "booted_at"), false, "the browser never supplies OS facts");
  assert.equal(Object.hasOwn(intent, "operator_id"), false);
  assert.equal(h.run("engineeringBaselinePlan(data.request, data.task, data.step)"), null,
    "legacy preservation plans cannot become source update approvals");
});

test("source update plans cannot become rescue approvals and incorrect containment remains unapproved", () => {
  for (const mutate of [
    plan => {plan.purpose = "source_rebind";},
    plan => {plan.facts.legacy_containment.original_start.request.run_id = "run_foreign";},
    plan => {plan.facts.legacy_containment.boot.booted_at = "2026-10-04T01:00:00Z";},
    plan => {plan.facts.legacy_containment.containment_sha256 = "invalid";},
    plan => {plan.input_mode = "coder_reapply";},
  ]) {
    const h = harness();
    legacyRescueFixture(h);
    mutate(legacyRescuePlan(h));
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    assert.equal(control(box, "批准保留进度并继续原需求"), undefined);
  }
});

test("legacy rescue old controls cannot submit after exact facts or capability changes", async () => {
  for (const mutation of [
    'data.request.checkpoint_sha256 = "6".repeat(64)',
    'data.task.task_revision = 5',
    'data.step.wait_disposition_sha256 = "6".repeat(64)',
    'operations[0].result.engineering_wait_handling.investigation.proof_sha256 = "6".repeat(64)',
    'consoleOperationContractVersion = 1',
    'consoleSupportedActions = ["PROPOSE_EXECUTION_BASELINE"]',
  ]) {
    const h = harness();
    legacyRescueFixture(h);
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    const prepare = control(box, "准备保留进度的恢复方案");
    h.run(mutation);
    await prepare.events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});

test("legacy rescue approvals cannot resubmit a consumed plan or a changed original run", async () => {
  for (const mutation of [
    'rescuePlan.plan_sha256 = "6".repeat(64)',
    'rescuePlan.facts.legacy_containment.original_start.request.run_id = "run_foreign"',
    'operations.push({operation_id: "rescue_approved", status: "SUCCEEDED", intent: {action: "EXECUTE_EXECUTION_BASELINE", project_id: data.request.project_id, delivery_id: data.request.id, task_id: data.task.task_id, expected_plan_sha256: rescuePlan.plan_sha256}})',
  ]) {
    const h = harness();
    legacyRescueFixture(h);
    legacyRescuePlan(h);
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    const checkbox = descend(box).find(node => node.tagName === "INPUT" && node.type === "checkbox");
    checkbox.checked = true;
    const approval = control(box, "批准保留进度并继续原需求");
    h.run(mutation);
    await approval.events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});

test("current rescue advice and copied report replace vague maintenance requests while history remains honest", async () => {
  const h = harness();
  const result = legacyRescueFixture(h);
  h.context.navigator = {clipboard: {writeText: async value => {h.context.copiedReport = value;}}};
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.doesNotMatch(text(box), /将处理报告交给平台维护者/);
  const currentNotice = h.run("operationNoticeFor(operations[0]).message");
  assert.match(currentNotice, /准备保留进度的恢复方案/);
  assert.doesNotMatch(currentNotice, /将处理报告交给平台维护者/);
  await control(box, "复制处理报告").events.click();
  assert.match(h.context.copiedReport, /准备保留进度的恢复方案/);
  assert.match(h.context.copiedReport, /先看平台检查结果/);
  assert.doesNotMatch(h.context.copiedReport, /将处理报告交给平台维护者/);
  h.context.panel = new Element("section");
  h.run("requestOperationHistory(panel, data.request)");
  assert.match(text(h.context.panel), /当次用户操作 · 将处理报告交给平台维护者/);
  assert.equal(result.user_action, "将处理报告交给平台维护者，无需自行确认内部执行记录。");
  h.request.checkpoint_sha256 = digest("6");
  assert.equal(h.run("currentEngineeringRescueAdvice(operations[0], data.request)"), null,
    "a historical handling from an old checkpoint cannot gain current rescue advice");
  h.request.checkpoint_sha256 = digest("a");
  result.collection_failed = true;
  assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "准备保留进度的恢复方案"), undefined,
    "collection rejection cannot be transformed into a salvage approval");
});

function failedRescueProposal(h, status = "FAILED") {
  h.run(`operations.push({operation_id: "failed_rescue_proposal", status: ${JSON.stringify(status)},
    updated_at: "2026-10-07T02:00:00Z", error_code: "MANAGER_FAILURE",
    error_summary: "Manager 执行异常(WorktreeCaptureRejected); 尚未获得具体原因。请提供此操作编号排查, 不要反复重试。",
    intent: {...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE",
      purpose: "legacy_workspace_rescue", target_base_ref: "c".repeat(40), input_mode: "preserve_draft"}});`);
}

test("failed or interrupted rescue preparation stays visible and in copied reports after a later wait handling", async () => {
  for (const status of ["FAILED", "INTERRUPTED"]) {
    const h = harness();
    legacyRescueFixture(h);
    failedRescueProposal(h, status);
    h.run(`operations[0].updated_at = "2026-10-08T02:00:00Z";`);
    h.context.navigator = {clipboard: {writeText: async value => {h.context.copiedReport = value;}}};
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    assert.match(text(box), /恢复方案准备(?:失败|被中断)/);
    assert.match(text(box), /平台维护者/);
    assert.match(text(box), /MANAGER_FAILURE/);
    assert.match(text(box), /WorktreeCaptureRejected/);
    assert.equal(control(box, "准备保留进度的恢复方案"), undefined);
    assert.equal(control(box, "批准保留进度并继续原需求"), undefined);
    await control(box, "复制处理报告").events.click();
    assert.match(h.context.copiedReport, /恢复方案准备(?:失败|被中断)/);
    assert.match(h.context.copiedReport, /恢复准备操作 · failed_rescue_proposal/);
    assert.match(h.context.copiedReport, /错误编号 · MANAGER_FAILURE/);
    assert.match(h.context.copiedReport, /WorktreeCaptureRejected/);
    assert.doesNotMatch(h.context.copiedReport, /在当前需求详情点击“准备保留进度的恢复方案”/);
    assert.match(h.run("operationNoticeFor(operations[0]).message"), /平台维护者/);
  }
});

test("rescue failure exact scope prevents foreign and stale operations from changing current preparation", () => {
  for (const [key, value] of Object.entries({project_id: "project_other", delivery_id: "requirement_other",
    task_id: "task_other", expected_checkpoint_sha256: digest("9"), expected_task_revision: 5,
    expected_task_intent_sha256: digest("9"), expected_work_item_id: "work_other",
    expected_source_revision: "9".repeat(40), purpose: "source_rebind", target_base_ref: "9".repeat(40),
    input_mode: "coder_reapply"})) {
    const h = harness();
    legacyRescueFixture(h);
    legacyRescuePlan(h);
    failedRescueProposal(h);
    h.context.changedValue = value;
    h.run(`operations[2].intent[${JSON.stringify(key)}] = changedValue;`);
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    assert.doesNotMatch(text(box), /MANAGER_FAILURE/, key);
    assert.ok(control(box, "批准保留进度并继续原需求"), key);
  }
});

test("a newer failed proposal removes a previous rescue approval and its retained callback", async () => {
  const h = harness();
  legacyRescueFixture(h);
  legacyRescuePlan(h);
  const oldBox = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const checkbox = descend(oldBox).find(node => node.tagName === "INPUT" && node.type === "checkbox");
  checkbox.checked = true;
  const oldApprove = control(oldBox, "批准保留进度并继续原需求");
  failedRescueProposal(h);
  assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "批准保留进度并继续原需求"), undefined);
  await oldApprove.events.click();
  assert.equal(h.run("submitted.length"), 0);
});

test("a repaired platform can recheck the same failed rescue without approval or a new demand", async () => {
  const h = harness();
  legacyRescueFixture(h);
  failedRescueProposal(h);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  await control(box, "修复后重新检查恢复前提").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[0])"));
  assert.equal(intent.action, "PROPOSE_EXECUTION_BASELINE");
  assert.equal(intent.delivery_id, h.request.id);
  assert.equal(intent.task_id, h.task.task_id);
  assert.equal(intent.expected_work_item_id, h.step.work_item_id);
  assert.equal(intent.purpose, "legacy_workspace_rescue");
  assert.equal(intent.input_mode, "preserve_draft");
  assert.equal(Object.hasOwn(intent, "confirm_local_execution_stopped"), false);
  assert.equal(Object.hasOwn(intent, "confirm_legacy_containment"), false);
});

test("typed capture waiting stays distinct from internal failure and drives the copied next step", async () => {
  const h = harness();
  legacyRescueFixture(h);
  legacyRescuePlan(h);
  const preparation = {status: "WAITING", task_id: h.task.task_id, work_item_id: h.step.work_item_id,
    source_revision: "c".repeat(40), code: "LEGACY_WORKSPACE_CAPTURE_REJECTED",
    summary: "保留进度的完整草稿暂时无法封存, 原文件与开发进度已保留。",
    next_action: "请由平台维护者检查草稿捕获的文件格式、权限和敏感信息校验；处理后重新准备恢复方案，不要清空工作区或重建需求。",
    responsible_party: "平台执行服务"};
  h.context.preparation = preparation;
  h.run(`operations.push({operation_id: "capture_waiting", status: "SUCCEEDED", updated_at: "2026-10-07T02:00:00Z",
    intent: {...engineeringBaselineFacts(data.request, data.task, data.step), action: "PROPOSE_EXECUTION_BASELINE",
      purpose: "legacy_workspace_rescue", target_base_ref: "c".repeat(40), input_mode: "preserve_draft"},
    result: {checkpoint_sha256: data.request.checkpoint_sha256, legacy_rescue_preparation: preparation}});`);
  h.context.navigator = {clipboard: {writeText: async value => {h.context.copiedReport = value;}}};
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /恢复前提尚未满足/);
  assert.doesNotMatch(text(box), /恢复方案准备失败|内部异常/);
  assert.equal(control(box, "批准保留进度并继续原需求"), undefined);
  assert.ok(control(box, "重新检查恢复前提"));
  await control(box, "复制处理报告").events.click();
  assert.ok(h.context.copiedReport.includes("用户操作 · " + preparation.next_action));
  assert.doesNotMatch(h.context.copiedReport, /在当前需求详情点击“准备保留进度的恢复方案”/);
});
