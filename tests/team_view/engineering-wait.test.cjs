const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

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
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  // Load the actual UI functions without starting navigation, polling or network work.
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  vm.runInContext(`snapshot = {team_id: "team_current", selected_project_id: "project_current",
    projects: [], agents: [], tasks: [data.task], requests: [data.request]};
    consoleTeamId = "team_current"; consoleAvailable = true; consoleDeliveryReady = true;
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
  assert.match(text(box), /重复调查不会补齐缺失记录/);
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
