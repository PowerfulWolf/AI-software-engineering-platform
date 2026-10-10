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
  append(...nodes) {
    this.children.push(...nodes);
    for (const node of nodes) if (typeof node !== "string") node.parentNode = this;
  }
  get childNodes() { return this.children; }
  get lastChild() { return this.children.at(-1); }
  insertBefore(node, reference) {
    if (node === reference) return;
    node.remove();
    const index = reference === null ? this.children.length : this.children.indexOf(reference);
    this.children.splice(index, 0, node);
    node.parentNode = this;
  }
  moveBefore(node, reference) { this.insertBefore(node, reference); }
  remove() {
    if (!this.parentNode) return;
    const children = this.parentNode.children;
    children.splice(children.indexOf(this), 1);
    this.parentNode = null;
  }
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
const visibleDescend = node => [node, ...node.children.filter(item => typeof item !== "string" && !item.hidden &&
  (node.tagName !== "DETAILS" || node.open === true || item.tagName === "SUMMARY")).flatMap(visibleDescend)];
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

test("platform repair retry handles the exact original wait instead of only inspecting it", async () => {
  const h = harness();
  const result = handling(h, "PLATFORM_ATTENTION", ["OUTCOME_UNKNOWN", "CHECKPOINT_UNAVAILABLE"]);
  result.collection_failed = true;
  result.collection_failure = "WORKSPACE_CAPTURE_REJECTED";
  result.investigation.process_stop_sha256 = digest("2");
  result.investigation.retry_cause = "local_execution_limit";
  result.summary = "原 Coder 已到本地执行时限并停止，但保留进度的完整封存未通过平台校验。";
  result.user_action = "平台维护者修复完整进度封存问题后，点击“平台修复后重新处理”。";
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /原 Coder 已到本地执行时限并停止/);
  assert.match(text(box), /已核验原执行停止/);
  assert.doesNotMatch(text(box), /原执行是否已结束还没有可靠记录/);
  assert.equal(control(box, "继续原交付"), undefined);
  const retry = control(box, "平台修复后重新处理");
  assert.ok(retry, "fixed platform must be able to reconcile preserved facts through HANDLE");
  await retry.events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[0])"));
  assert.deepEqual(intent, {...JSON.parse(h.run("JSON.stringify(engineeringWaitIntent(data.request, data.step))")),
    action: "HANDLE_DELIVERY_WAIT"});
  h.context.navigator = {clipboard: {writeText: async value => {h.context.copiedReport = value;}}};
  await control(box, "复制处理报告").events.click();
  assert.match(h.context.copiedReport, /进度封存校验未通过/);
  assert.doesNotMatch(h.context.copiedReport, /WORKSPACE_CAPTURE_REJECTED|STOP_UNRECORDED/);
});

test("incremental wait rendering refreshes changed capture diagnosis with the same proof", () => {
  const h = harness();
  const result = handling(h, "PLATFORM_ATTENTION", ["OUTCOME_UNKNOWN", "CHECKPOINT_UNAVAILABLE"]);
  result.collection_failed = true;
  result.investigation.process_stop_sha256 = digest("2");
  const first = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const firstProof = descend(first).find(node => node.className === "engineering-investigation-result");
  const heading = descend(first).find(node => node.className === "engineering-wait-heading");
  assert.match(text(firstProof), /部分执行事实已核验，但收集校验失败/);
  const proofBytes = JSON.stringify(result.investigation);
  result.collection_failure = "WORKSPACE_CAPTURE_REJECTED";
  h.context.currentWait = first;
  h.run("reconcileViewChildren(currentWait, engineeringWaitBox(data.request, data.task, data.step))");
  const updatedProof = descend(first).find(node => node.className === "engineering-investigation-result");
  assert.notEqual(updatedProof, firstProof, "changed diagnostic must invalidate retained result DOM");
  assert.equal(descend(first).find(node => node.className === "engineering-wait-heading"), heading,
    "unaffected keyed blocks are preserved during the same incremental update");
  assert.match(text(updatedProof), /已核验原执行停止，但进度封存校验未通过/);
  assert.doesNotMatch(text(updatedProof), /部分执行事实已核验，但收集校验失败/);
  assert.equal(JSON.stringify(result.investigation), proofBytes);
  h.run(`consoleSupportedActions = consoleSupportedActions.filter(action => action !== "HANDLE_DELIVERY_WAIT");
    reconcileViewChildren(currentWait, engineeringWaitBox(data.request, data.task, data.step));`);
  const unavailableProof = descend(first).find(node => node.className === "engineering-investigation-result");
  assert.notEqual(unavailableProof, updatedProof, "capability changes also refresh retry guidance");
  assert.doesNotMatch(text(unavailableProof), /点击“平台修复后重新处理”/);
});

test("unavailable platform retry does not promise a hidden action or let an old retry submit", async () => {
  const h = harness();
  const result = handling(h, "PLATFORM_ATTENTION", ["OUTCOME_UNKNOWN", "CHECKPOINT_UNAVAILABLE"]);
  result.collection_failed = true;
  result.collection_failure = "WORKSPACE_CAPTURE_REJECTED";
  result.investigation.process_stop_sha256 = digest("2");
  result.user_action = "修复后点击“平台修复后重新处理”。";
  const old = control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "平台修复后重新处理");
  h.run(`consoleSupportedActions = consoleSupportedActions.filter(action => action !== "HANDLE_DELIVERY_WAIT")`);
  await old.events.click();
  assert.equal(h.run("submitted.length"), 0);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.equal(control(box, "平台修复后重新处理"), undefined);
  const user = descend(box).find(node => node.tagName === "DIV" &&
    node.children.some(child => child.tagName === "DT" && child.textContent === "你需要做什么"));
  assert.match(text(user), /版本不匹配.*重启/);
  assert.doesNotMatch(text(user), /点击“平台修复后重新处理”/);
  h.context.navigator = {clipboard: {writeText: async value => {h.context.copiedReport = value;}}};
  await control(box, "复制处理报告").events.click();
  assert.doesNotMatch(h.context.copiedReport, /用户操作 · .*点击“平台修复后重新处理”/);
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
  h.run("consoleOperationContractVersion = 4");
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
  assert.equal(control(box, "批准更新基线，保持暂停"), undefined);
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
  await control(box, "批准更新基线，保持暂停").events.click();
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
  assert.equal(control(box, "批准更新基线，保持暂停"), undefined);
  await control(box, "提出 Coder 适配完整旧补丁的计划").events.click();
  assert.equal(h.run("submitted[0].input_mode"), "coder_reapply");
  assert.equal(h.run("submitted[0].action"), "PROPOSE_EXECUTION_BASELINE");
  baselinePlan(h, false, "coder_reapply");
  box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /读取完整旧补丁并适配/);
  await control(box, "批准更新基线，保持暂停").events.click();
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
    await control(box, "批准更新基线，保持暂停").events.click();
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
  h.run("consoleOperationContractVersion = 4");
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

test("engineering controls explain every unavailable gate without promising hidden recovery actions", async () => {
  for (const [mutation, reason, nextStep] of [
    ["consoleAvailable = false", /当前服务未提供交付控制接口/, /连接后台 Web Console/],
    ["consoleAvailable = null; consoleConnectionFailed = true", /无法连接或确认后台 Web Console/, /恢复连接/],
    ["operationsAvailable = false", /无法读取已保存的交付操作记录/, /修复操作记录读取/],
    ["consoleDeliveryReady = false", /交付运行时尚未就绪/, /设置或状态页查看未就绪原因/],
    ["consoleTeamId = 'team_other'", /Team 绑定不一致/, /当前 Team/],
    ["requestedProjectId = 'project_other'", /正在切换项目/, /目标项目加载完成/],
  ]) {
    const h = harness();
    legacyRescueFixture(h);
    legacyRescuePlan(h);
    h.run(mutation);
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    const notices = descend(box).filter(node => (node.className || "").includes("engineering-controls-unavailable"));
    assert.equal(notices.length, 2, mutation + " leaves a visible reason in both the wait and rescue panels");
    for (const notice of notices) {
      assert.match(text(notice), reason, mutation);
      assert.match(text(notice), nextStep, mutation);
    }
    const userRow = descend(box).find(node => node.tagName === "DIV" &&
      node.children.some(child => child.tagName === "DT" && child.textContent === "你需要做什么"));
    assert.match(text(userRow), nextStep, mutation);
    assert.doesNotMatch(text(userRow), /点击“准备保留进度的恢复方案”/, mutation);
    for (const name of ["让平台处理中断", "调查工程等待", "准备保留进度的恢复方案", "批准保留进度，保持暂停"])
      assert.equal(control(box, name), undefined, mutation);
    assert.equal(descend(box).some(node => node.tagName === "INPUT" && node.type === "checkbox"), false, mutation);
    assert.equal(h.run("canControlCurrentTeam()"), false, mutation);
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});

test("unready runtime and unavailable team data do not invent an unavailable configuration or team mismatch", () => {
  const h = harness();
  h.run("consoleDeliveryReady = false");
  let reason = JSON.parse(h.run("JSON.stringify(deliveryControlUnavailableReason())"));
  assert.match(reason.next_action, /设置或状态页查看未就绪原因，按页面提示处理/);
  assert.doesNotMatch(reason.next_action, /完成配置|应用配置|重启/);
  h.run("consoleDeliveryReady = true; snapshot = null");
  reason = JSON.parse(h.run("JSON.stringify(deliveryControlUnavailableReason())"));
  assert.match(reason.title, /团队数据暂不可读取/);
  assert.match(reason.next_action, /待团队数据恢复/);
  assert.doesNotMatch(reason.reason, /绑定不一致/);
  assert.equal(h.run("canControlCurrentTeam()"), false);
});

test("stale Team facts invalidate retained engineering callbacks and show the read-only next step", async () => {
  for (const issue of ["busy", "unavailable", "timeout"]) {
    for (const kind of ["handling", "proposal", "preservation", "continuation", "approval"]) {
      const h = harness();
      let name = "让平台处理中断";
      if (kind === "proposal" || kind === "preservation") {
        legacyRescueFixture(h);
        if (kind === "preservation") legacyRescuePlan(h);
        name = kind === "proposal" ? "准备保留进度的恢复方案" : "批准保留进度，保持暂停";
      } else if (kind === "continuation") {
        baselineFixture(h);
        Object.assign(h.step.wait_disposition.facts, {classification: "EXECUTION_BASELINE_PAUSED", execution_baseline_sha256: digest("8")});
        h.step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
        name = "继续原需求";
      } else if (kind === "approval") {
        stoppedRecoveryFixture(h);
        name = "批准并继续";
      }
      const build = kind === "approval" ? "requestBlockerSection(data.request)"
        : "engineeringWaitBox(data.request, data.task, data.step)";
      const box = h.run(build);
      const old = control(box, name);
      assert.ok(old, kind);
      const checkbox = descend(box).find(node => node.tagName === "INPUT" && node.type === "checkbox");
      if (checkbox) {checkbox.checked = true; checkbox.events.change?.();}
      const originalFacts = JSON.stringify(h.step.wait_disposition);
      h.context.readFailure = issue;
      h.run("teamReadIssue = readFailure");
      await old.events.click();
      assert.equal(h.run("submitted.length"), 0, issue + ": old " + name + " must not submit");
      const reason = h.run("deliveryControlUnavailableReason()");
      assert.match(reason.reason, /最新.*团队数据|团队数据.*最新|当前团队数据/);
      assert.match(reason.next_action, /自动.*重试|恢复.*重新核对|重新读取/);
      assert.doesNotMatch(reason.next_action, /重启|重建需求|批准|停止旧执行/);
      const current = h.run(build);
      assert.equal(control(current, name), undefined, issue + ": fresh render must not promise an unavailable action");
      assert.equal(JSON.stringify(h.step.wait_disposition), originalFacts);
      h.run("teamReadIssue = null");
      const recovered = h.run(build);
      assert.ok(control(recovered, name), "reading the same current facts restores " + kind);
      assert.equal(h.run("submitted.length"), 0, "read recovery itself does not approve or resume");
    }
  }
});

test("Team freshness reconciliation retains open saved documents and removes obsolete controls", async () => {
  const h = harness();
  baselineFixture(h);
  Object.assign(h.step.wait_disposition.facts, {classification: "EXECUTION_BASELINE_PAUSED", execution_baseline_sha256: digest("8")});
  h.step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
  h.run(`function fixtureDetail() {
    const root = viewGroup(el('section'), 'fixture-current-detail');
    root.append(engineeringWaitBox(data.request, data.task, data.step));
    documentList(root, [{name: '已保存的计划', content: '保留当前阅读的完整内容',
      source_uri: 'artifact://saved-plan', sha256: 'f'.repeat(64)}]);
    return root;
  }
  globalThis.retainedDetail = fixtureDetail();`);
  const root = h.context.retainedDetail;
  const document = descend(root).find(node => node.className === "artifact-document");
  const source = descend(root).find(node => node.className === "engineering-paused-source");
  document.open = true;
  const old = control(root, "继续原需求");
  const signature = h.run("JSON.stringify(pollingDetailFacts())");
  h.run("teamReadIssue = 'busy'; reconcileViewChildren(retainedDetail, fixtureDetail())");
  assert.notEqual(h.run("JSON.stringify(pollingDetailFacts())"), signature, "Team freshness invalidates actual scoped detail facts");
  assert.equal(descend(root).find(node => node.className === "artifact-document"), document);
  assert.equal(document.open, true);
  assert.equal(descend(root).find(node => node.className === "engineering-paused-source"), source);
  assert.equal(control(root, "继续原需求"), undefined);
  assert.match(text(root), /最新的团队数据，当前操作已暂停/);
  await old.events.click();
  assert.equal(h.run("submitted.length"), 0);
  h.run("teamReadIssue = null; reconcileViewChildren(retainedDetail, fixtureDetail())");
  assert.equal(descend(root).find(node => node.className === "artifact-document"), document);
  assert.equal(document.open, true);
  assert.ok(control(root, "继续原需求"));
  assert.doesNotMatch(text(root), /最新的团队数据，当前操作已暂停/);
  assert.equal(h.run("submitted.length"), 0);
});

test("operation read failure stays explicit when cached proofs are absent and never changes the original wait", () => {
  const h = harness();
  const original = JSON.stringify(h.step.wait_disposition);
  h.run("operationsAvailable = false; operations = [];");
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /交付操作记录读取失败/);
  assert.match(text(box), /不能确认当前恢复方案与审批状态/);
  assert.match(text(box), /不要重复准备方案或重建需求/);
  assert.doesNotMatch(text(box), /你可以点击“让平台处理中断”/);
  assert.equal(JSON.stringify(h.step.wait_disposition), original);
  assert.equal(h.run("submitted.length"), 0);
});

test("copied current report names unavailable controls instead of directing the user to a hidden action", async () => {
  const h = harness();
  legacyRescueFixture(h);
  legacyRescuePlan(h);
  h.context.navigator = {clipboard: {writeText: async value => {h.context.copiedReport = value;}}};
  h.run("operationsAvailable = false");
  await control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "复制处理报告").events.click();
  assert.match(h.context.copiedReport, /交付操作记录读取失败/);
  assert.match(h.context.copiedReport, /用户操作 · .*修复操作记录读取/);
  assert.doesNotMatch(h.context.copiedReport, /使用需求详情中的“准备保留进度的恢复方案”|在当前需求详情点击“准备保留进度的恢复方案”/);
  assert.match(h.run("currentEngineeringRescueAdvice(operations[0], data.request)"), /修复操作记录读取/);
});

test("a checked recovery approval removed during unreadable facts cannot revive after the same plan is read again", async () => {
  const h = harness();
  legacyRescueFixture(h);
  legacyRescuePlan(h);
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const checkbox = descend(box).find(node => node.tagName === "INPUT" && node.type === "checkbox");
  checkbox.checked = true;
  const oldApprove = control(box, "批准保留进度，保持暂停");
  h.run("operationsAvailable = false");
  await oldApprove.events.click();
  assert.equal(h.run("submitted.length"), 0);
  oldApprove.isConnected = false;
  h.run("operationsAvailable = true");
  await oldApprove.events.click();
  assert.equal(h.run("submitted.length"), 0, "the disconnected approval cannot reuse its old checked confirmation");
  const current = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const currentCheckbox = descend(current).find(node => node.tagName === "INPUT" && node.type === "checkbox");
  assert.equal(currentCheckbox.checked, false);
  currentCheckbox.checked = true;
  currentCheckbox.events.change();
  await control(current, "批准保留进度，保持暂停").events.click();
  assert.equal(h.run("submitted.length"), 1);
});

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
  const approve = control(rescue, "批准保留进度，保持暂停");
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
    assert.equal(control(box, "批准保留进度，保持暂停"), undefined);
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
    const approval = control(box, "批准保留进度，保持暂停");
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
    assert.equal(control(box, "批准保留进度，保持暂停"), undefined);
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
    assert.ok(control(box, "批准保留进度，保持暂停"), key);
  }
});

test("a newer failed proposal removes a previous rescue approval and its retained callback", async () => {
  const h = harness();
  legacyRescueFixture(h);
  legacyRescuePlan(h);
  const oldBox = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const checkbox = descend(oldBox).find(node => node.tagName === "INPUT" && node.type === "checkbox");
  checkbox.checked = true;
  const oldApprove = control(oldBox, "批准保留进度，保持暂停");
  failedRescueProposal(h);
  assert.equal(control(h.run("engineeringWaitBox(data.request, data.task, data.step)"), "批准保留进度，保持暂停"), undefined);
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
  assert.equal(control(box, "批准保留进度，保持暂停"), undefined);
  assert.ok(control(box, "重新检查恢复前提"));
  await control(box, "复制处理报告").events.click();
  assert.ok(h.context.copiedReport.includes("用户操作 · " + preparation.next_action));
  assert.doesNotMatch(h.context.copiedReport, /在当前需求详情点击“准备保留进度的恢复方案”/);
});

test("preserved progress pause separates baseline preparation from exact explicit continuation", async () => {
  const h = harness();
  baselineFixture(h);
  Object.assign(h.step.wait_disposition.facts, {classification: "EXECUTION_BASELINE_PAUSED", execution_baseline_sha256: digest("8")});
  h.step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(box), /进度已保留 · 交付暂停/);
  assert.match(text(box), /没有启动新的 Coder/);
  const steps = descend(box).find(node => node.tagName === "OL" && node.className === "engineering-guidance-list");
  assert.equal(steps.children.length, 3);
  assert.equal(steps.children.some(node => /^\d+[.、]/u.test(node.textContent)), false, "the list owns the numbering");
  assert.match(steps.children[1].textContent, /批准基线更新；更新后仍保持暂停/);
  assert.equal(control(box, "调查工程等待"), undefined);
  assert.equal(control(box, "让平台处理中断"), undefined);
  assert.ok(control(box, "调查并保留原草稿"));
  assert.equal(h.run("submitted.length"), 0);
  await control(box, "继续原需求").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[0])"));
  assert.equal(intent.action, "RESUME_EXECUTION_BASELINE");
  assert.equal(intent.expected_execution_baseline_sha256, digest("8"));
  assert.equal(intent.expected_disposition_sha256, digest("d"));
  assert.equal(intent.expected_work_item_id, h.step.work_item_id);
  assert.equal(Object.hasOwn(intent, "approved_plan_sha256"), false);
  assert.equal(Object.hasOwn(intent, "attempt"), false);
});

test("pause continuation rejects stale source, binding, disposition and old service capabilities", async () => {
  for (const mutation of [
    'data.step.wait_disposition.facts.source_revision = "e".repeat(40)',
    'data.step.wait_disposition.facts.execution_baseline_sha256 = "e".repeat(64)',
    'data.step.wait_disposition_sha256 = "e".repeat(64)',
    'data.task.task_revision += 1',
    'consoleOperationContractVersion = 3',
    'consoleSupportedActions = consoleSupportedActions.filter(action => action !== "RESUME_EXECUTION_BASELINE")',
  ]) {
    const h = harness();
    baselineFixture(h);
    Object.assign(h.step.wait_disposition.facts, {classification: "EXECUTION_BASELINE_PAUSED", execution_baseline_sha256: digest("8")});
    h.step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
    const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
    const previous = control(box, "继续原需求");
    assert.ok(previous);
    h.run(mutation);
    await previous.events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});

test("source update keeps pause and native rule approval requires actual complete review", async () => {
  const h = harness();
  baselineFixture(h);
  const plan = baselinePlan(h);
  plan.facts.native_rule_change = {change_sha256: digest("9"), changes: [
    {path: "AGENTS.md", change: "modified", before: {sha256: digest("2")}, after: {sha256: digest("3")}},
  ]};
  let box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const approve = control(box, "批准更新基线，保持暂停");
  const confirmation = descend(box).find(node => node.tagName === "INPUT" && node.type === "checkbox");
  assert.equal(confirmation.disabled, true);
  assert.equal(approve.disabled, true);
  assert.ok(control(box, "查看规范变更 · AGENTS.md"));
  confirmation.checked = true;
  await approve.events.click();
  assert.equal(h.run("submitted.length"), 0, "forged check cannot bypass complete review");
  h.run(`saveNativeRuleReview(baselinePlan, "AGENTS.md", {status: "READY", inspection: {unified_diff: "complete rule: -old rule +new rule"}})`);
  box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const checked = descend(box).find(node => node.tagName === "INPUT" && node.type === "checkbox");
  assert.equal(checked.disabled, false);
  assert.equal(checked.checked, false, "loading review never grants consent");
  checked.checked = true;
  await control(box, "批准更新基线，保持暂停").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[0])"));
  assert.equal(intent.continuation_mode, "pause");
  assert.equal(intent.approved_native_rule_change_sha256, digest("9"));
  assert.match(text(box), /new rule/);
});

test("native rule review retains every current repository plan and prunes removed plans once per detail", () => {
  const h = harness();
  baselineFixture(h);
  const first = baselinePlan(h);
  first.facts.native_rule_change = {change_sha256: digest("9"), changes: [{path: "AGENTS.md", change: "modified"}]};
  const otherTask = structuredClone(h.task);
  otherTask.id = "delivery_other";
  otherTask.task_id = "task_other";
  const otherStep = otherTask.role_queue[0];
  otherStep.work_item_id = "work_other";
  Object.assign(otherStep.wait_disposition.facts, {task_id: otherTask.task_id, work_item_id: otherStep.work_item_id});
  const otherPlan = structuredClone(first);
  otherPlan.plan_sha256 = digest("8");
  otherPlan.facts.task.id = otherTask.task_id;
  otherPlan.facts.work_item_id = otherStep.work_item_id;
  Object.assign(h.context, {otherTask, otherStep, otherPlan});
  h.run(`snapshot.tasks.push(otherTask); data.request.scopes.push({delivery_id: otherTask.id});
    selected = {kind: "request", id: data.request.id};
    operations.push({operation_id: "baseline_other", status: "SUCCEEDED", updated_at: "2026-10-05T02:00:00Z",
      intent: {...engineeringBaselineFacts(data.request, otherTask, otherStep), action: "PROPOSE_EXECUTION_BASELINE",
        target_base_ref: otherPlan.target_base_ref, input_mode: otherPlan.input_mode},
      result: {checkpoint_sha256: data.request.checkpoint_sha256, execution_baseline_plan: otherPlan}});
    saveNativeRuleReview(baselinePlan, "AGENTS.md", {status: "READY", inspection: {unified_diff: "first complete rules"}});`);
  h.run("engineeringWaitBox(data.request, data.task, data.step); engineeringWaitBox(data.request, otherTask, otherStep)");
  assert.equal(h.run("nativeRulePlanReviewed(baselinePlan)"), true, "rendering the other plan cannot erase first review");
  h.run(`saveNativeRuleReview(otherPlan, "AGENTS.md", {status: "READY", inspection: {unified_diff: "other complete rules"}});
    pruneNativeRuleReviews();
    engineeringWaitBox(data.request, data.task, data.step); engineeringWaitBox(data.request, otherTask, otherStep);`);
  assert.equal(h.run("nativeRulePlanReviewed(baselinePlan) && nativeRulePlanReviewed(otherPlan)"), true);
  assert.equal(h.run("nativeRuleReviews.size"), 2);
  h.task.last_activity = "2026-10-06T00:00:00Z";
  h.run("pruneNativeRuleReviews()");
  assert.equal(h.run("nativeRuleReviews.size"), 2, "unrelated polling keeps all current plans");
  h.run("snapshot.tasks = [data.task]; pruneNativeRuleReviews()");
  assert.equal(h.run("nativeRuleReviews.size"), 1);
  assert.equal(h.run("nativeRulePlanReviewed(baselinePlan)"), true);
  assert.equal(h.run("nativeRulePlanReviewed(otherPlan)"), false);
  h.run("selected = null; pruneNativeRuleReviews()");
  assert.equal(h.run("nativeRuleReviews.size"), 0, "closed detail releases retained rule bodies");
});

function pendingContinuationFixture(h) {
  baselineFixture(h);
  h.step.status = "READY";
  h.step.wait_disposition = null;
  h.step.wait_disposition_sha256 = null;
  const authority = {scope: {team_id: "team_current", project_id: h.request.project_id},
    task_id: h.task.task_id, task_intent_sha256: h.task.task_intent_sha256, task_revision: h.task.task_revision,
    checkpoint_sequence: h.task.task_revision, work_item_id: h.step.work_item_id,
    expected_source_revision: "c".repeat(40), execution_baseline_sha256: digest("8"),
    expected_disposition_sha256: digest("d"), authorization_sha256: digest("7"),
    reference: "原工程授权者明确继续的决定"};
  h.step.pending_baseline_continuation = authority;
  h.task.execution = h.request.execution = {state: "WAITING", responsibility: "engineering", action_required: true,
    reason_code: "BASELINE_CONTINUATION_PENDING", reason: "已授权的执行尚未启动。", next_action: "继续已授权执行"};
  return authority;
}

test("committed but unstarted continuation exposes exact replay without another approval", async () => {
  const h = harness();
  const authority = pendingContinuationFixture(h);
  assert.equal(h.run("engineeringPendingBaselineSteps(data.request).length"), 1);
  assert.equal(h.run("canContinueDelivery(data.request)"), false, "generic continuation cannot conceal exact replay");
  const box = h.run("engineeringAuthorizedContinuationBox(data.request, data.task, data.step)");
  assert.match(text(box), /无需再次批准/);
  assert.equal(descend(box).filter(node => node.tagName === "INPUT").length, 0);
  h.request.checkpoint_sha256 = digest("6");
  await control(box, "继续已授权执行").events.click();
  const intent = JSON.parse(h.run("JSON.stringify(submitted[0])"));
  assert.equal(intent.action, "RESUME_EXECUTION_BASELINE");
  assert.equal(intent.expected_checkpoint_sha256, digest("6"), "outer checkpoint refreshed; semantic authorization preserved");
  assert.equal(intent.reference, authority.reference);
  assert.equal(intent.expected_execution_baseline_sha256, authority.execution_baseline_sha256);
  assert.equal(intent.expected_disposition_sha256, authority.expected_disposition_sha256);
});

test("old continuation retry cannot start changed work or an ordinary ready queue", async () => {
  for (const mutation of [
    'data.step.pending_baseline_continuation = null',
    'data.step.status = "RUNNING"',
    'data.task.status = "QA"',
    'data.task.task_revision += 1',
    'data.step.pending_baseline_continuation.expected_source_revision = "e".repeat(40)',
    'data.step.pending_baseline_continuation.execution_baseline_sha256 = "e".repeat(64)',
    'data.step.pending_baseline_continuation.reference = "different decision"',
    'consoleOperationContractVersion = 3',
  ]) {
    const h = harness();
    pendingContinuationFixture(h);
    const old = control(h.run("engineeringAuthorizedContinuationBox(data.request, data.task, data.step)"), "继续已授权执行");
    assert.ok(old);
    h.run(mutation);
    await old.events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});

function currentApprovalFixture(h, kind = "coder_recovery") {
  const approval = {kind, plan_sha256: digest("e"), title: "确认保留进度的继续方案",
    facts: ["保留原需求和开发进度，按精确方案继续独立验收。"],
    ...(kind === "coder_scope" ? {coder_scope_request: {paths: ["tests/test_contract.py"],
      progress_artifact_id: "art_progress", progress_sha256: digest("f"), reason: "调整本需求测试"}} : {})};
  h.context.approval = approval;
  h.run(`operations = [{operation_id: "current_approval", status: "SUCCEEDED", updated_at: "2026-10-05T01:00:00Z",
    intent: {action: "CONTINUE_DELIVERY", project_id: data.request.project_id, delivery_id: data.request.id,
      expected_checkpoint_sha256: data.request.checkpoint_sha256},
    result: {delivery_id: data.request.id, checkpoint_sha256: data.request.checkpoint_sha256, approval}}];`);
  return approval;
}

function stoppedRecoveryFixture(h, kind = "coder_recovery") {
  currentApprovalFixture(h, kind);
  h.request.stage = "BLOCKED";
  h.request.failed_stages = ["DELIVERING"];
  h.request.blocker = "Coder 第 8 次执行失败：原始诊断与现场保留。";
  h.request.next_action = "需要人工处理后再继续交付。";
  h.request.execution = {state: "STOPPED", responsibility: "engineering",
    reason: "当前交付已停止，历史与工作现场保留。",
    next_action: "由工程团队核对停止原因和安全恢复路径；当前无需产品操作。"};
  Object.assign(h.task, {status: "BLOCKED", terminal: true, blocker: h.request.blocker});
  h.step.status = "CLOSED";
  h.step.wait_disposition = null;
}

test("a current exact recovery decision replaces stopped-work advice while retaining original execution history", () => {
  const h = harness();
  stoppedRecoveryFixture(h);
  const durable = h.run("JSON.stringify([data.request, data.task, operations])");
  const node = h.run("requestNodeExecution(data.request)");
  assert.equal(node.label, "待工程确认");
  assert.equal(node.state, "blocked");
  assert.equal(node.status, "WAITING_ENGINEERING");
  assert.equal(h.run("requestNodeBadge(data.request).textContent"), "待工程确认");
  assert.match(h.run("requestNodeBadge(data.request).className"), /blocked/);
  assert.match(node.reason, /尚未.*执行/);
  assert.doesNotMatch(node.reason, /第 8 次|已完成|正在执行/);
  const presented = h.run("requestPresentation(data.request)");
  assert.match(presented.nextAction, /工程授权者.*批准并继续/);
  assert.doesNotMatch(presented.nextAction, /无需产品操作|核对停止原因/);
  const box = h.run("requestBlockerSection(data.request)");
  const visible = visibleDescend(box).map(node => node.textContent).join(" ");
  assert.match(visible, /待工程确认|尚未.*执行/);
  assert.match(visible, /批准并继续/);
  assert.match(visible, /原执行历史/);
  assert.doesNotMatch(visible, /第 8 次|无需产品操作/);
  assert.match(text(box), /第 8 次执行失败/);
  const approve = control(box, "批准并继续");
  assert.equal(approve.disabled, false);
  const history = descend(box).find(node => node.tagName === "DETAILS" && text(node).includes("第 8 次"));
  assert.ok(history);
  assert.notEqual(history.open, true);
  const flow = h.run("deliveryFlow(data.request)");
  assert.match(text(flow.children[3]), /待工程确认/);
  assert.doesNotMatch(text(flow.children[3]), /已阻塞/);
  assert.equal(h.run("JSON.stringify([data.request, data.task, operations])"), durable,
    "presentation must not reset the terminal Task or rewrite any approval/history");
  assert.equal(h.run("submitted.length"), 0);
});

test("a stopped-work decision cannot use stale foreign unreadable consumed or busy approvals", () => {
  for (const mutation of [
    'operations[0].result.checkpoint_sha256 = "old"',
    'operations[0].intent.project_id = "other_project"',
    'snapshot.selected_project_id = "other_project"',
    'teamReadIssue = "busy"',
    'operationsAvailable = false',
    'consoleSupportedActions = []',
    'operations = []',
    `operations.push({status: "SUCCEEDED", updated_at: "2026-10-05T02:00:00Z",
      intent: {action: "CONTINUE_DELIVERY", project_id: data.request.project_id,
        delivery_id: data.request.id, approved_plan_sha256: approval.plan_sha256}})`,
  ]) {
    const h = harness();
    stoppedRecoveryFixture(h);
    h.run(mutation);
    const node = h.run("requestNodeExecution(data.request)");
    assert.notEqual(node.label, "待工程确认", mutation);
    assert.equal(node.state, "blocked", mutation);
    assert.match(h.run("data.task.blocker"), /第 8 次/);
    assert.equal(h.run("submitted.length"), 0);
  }
});

test("a new platform recovery operation explains handling without claiming Coder execution or hiding a newer failure", () => {
  const h = harness();
  stoppedRecoveryFixture(h);
  h.run(`operations.push({operation_id: "current_work", status: "RUNNING",
    requested_at: "2026-10-05T02:00:00Z", updated_at: "2026-10-05T02:00:00Z",
    intent: {action: "CONTINUE_DELIVERY", project_id: data.request.project_id, delivery_id: data.request.id}})`);
  const durable = h.run("JSON.stringify([data.request, data.task, operations])");
  const node = h.run("requestNodeExecution(data.request)");
  assert.equal(node.label, "平台正在处理恢复");
  assert.equal(node.state, "paused", "platform handling is not a live Coder claim");
  assert.equal(h.run("requestNodeBadge(data.request).textContent"), "平台正在处理恢复");
  assert.match(h.run("requestNodeBadge(data.request).className"), /paused/);
  assert.match(node.nextAction, /等待.*平台/);
  assert.doesNotMatch(node.reason + node.nextAction, /无需产品操作|已经启动 Coder|正在开发|已接纳/);
  assert.equal(h.run("requestPresentation(data.request).group"), "active");
  assert.equal(h.run("requestBlockerSection(data.request)"), null);
  const flow = h.run("deliveryFlow(data.request)");
  assert.equal(flow.children[3].className, "paused");
  assert.match(text(flow.children[3]), /平台正在处理恢复/);
  assert.doesNotMatch(text(flow.children[3]), /已阻塞|执行中/);
  assert.equal(h.run("JSON.stringify([data.request, data.task, operations])"), durable);
  h.task.last_activity = "2026-10-05T03:00:00Z";
  h.task.blocker = "本次平台处理后发生新的执行失败。";
  assert.equal(h.run("requestNodeExecution(data.request).state"), "blocked");
  assert.match(h.run("requestPresentation(data.request).blocker"), /新的执行失败/);
  assert.match(h.run("requestNodeBadge(data.request).textContent"), /已阻塞/);
  assert.equal(h.run("submitted.length"), 0);
});

test("matching recovery facts cannot replace the explicit product or delivery confirmation step", () => {
  for (const stage of ["WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL", "WAITING_DELIVERY_FINALIZATION"]) {
    const h = harness();
    stoppedRecoveryFixture(h);
    h.request.stage = stage;
    assert.equal(h.run("requestNodeExecution(data.request).status"), stage);
    assert.equal(h.run("requestPresentation(data.request).status"), stage);
    const blockers = h.run("requestBlockerSection(data.request)");
    if (blockers) assert.equal(control(blockers, "批准并继续"), undefined,
      "an old recovery approval cannot compete with the explicit confirmation step");
  }
  const h = harness();
  stoppedRecoveryFixture(h);
  h.request.stage = "WAITING_HUMAN";
  h.request.knowledge_gap = {is_current: true, resolution: {resolution_id: "approved_knowledge"}};
  assert.equal(h.run("requestNodeExecution(data.request).status"), "KNOWLEDGE_APPROVED");
  assert.equal(h.run("requestPresentation(data.request).status"), "KNOWLEDGE_APPROVED");
});

test("a current file-scope decision states that approval prepares a plan without starting an Agent", () => {
  const h = harness();
  stoppedRecoveryFixture(h, "coder_scope");
  const node = h.run("requestNodeExecution(data.request)");
  assert.equal(node.label, "待工程确认");
  assert.match(h.run("requestPresentation(data.request).nextAction"), /批准文件范围.*不会启动 Agent.*审批恢复计划/);
  const box = h.run("requestBlockerSection(data.request)");
  assert.ok(visibleDescend(box).includes(control(box, "批准文件范围")));
  assert.equal(h.run("submitted.length"), 0);
});

test("actual role dispatch cannot be replaced by a previously prepared recovery decision", () => {
  for (const status of ["RUNNING", "READY", "RETRY_SCHEDULED"]) {
    const h = harness();
    stoppedRecoveryFixture(h);
    h.task.status = "IMPLEMENTING";
    h.task.terminal = false;
    h.task.blocker = null;
    h.step.status = status;
    h.step.lease_liveness = "LEASE_VALID";
    h.request.stage = "DELIVERING";
    h.request.execution = {state: status === "READY" ? "QUEUED" : status,
      responsibility: "team", reason: "本轮角色状态", next_action: "等待平台执行"};
    const node = h.run("requestNodeExecution(data.request)");
    assert.notEqual(node.label, "待工程确认", status);
    assert.equal(node.state, status === "RUNNING" ? "running" : "paused", status);
  }
});

for (const status of ["READY", "RUNNING"]) {
  test(`current ${status} role facts replace retained STOPPED advice and invalidate old approval controls`, async () => {
    const h = harness();
    stoppedRecoveryFixture(h);
    const old = control(h.run("requestBlockerSection(data.request)"), "批准并继续");
    h.request.stage = "DELIVERING";
    Object.assign(h.task, {status: "IMPLEMENTING", terminal: false, blocker: null,
      last_activity: "2026-10-05T02:00:00Z"});
    Object.assign(h.step, {status, lease_liveness: "LEASE_VALID"});
    const durable = h.run("JSON.stringify([data.request, data.task, operations])");
    const node = h.run("requestNodeExecution(data.request)");
    assert.equal(node.label, status === "RUNNING" ? "执行中" : "已排队");
    assert.equal(node.state, status === "RUNNING" ? "running" : "paused");
    assert.equal(h.run("requestNodeBadge(data.request).textContent"),
      `实现 · ${status === "RUNNING" ? "执行中" : "已排队"}`,
      "real role dispatch retains the actual delivery phase");
    const presentation = h.run("requestPresentation(data.request)");
    assert.equal(presentation.group, "active");
    assert.doesNotMatch(presentation.nextAction, /无需产品操作|核对停止原因|批准并继续/);
    const flow = h.run("deliveryFlow(data.request)");
    assert.equal(flow.children[3].className, status === "RUNNING" ? "current" : "paused");
    assert.doesNotMatch(text(flow.children[3]), /已阻塞|待工程确认/);
    const panel = new Element("section");
    h.context.operationPanel = panel;
    h.run("requestOperation(operationPanel, data.request)");
    assert.equal(control(panel, "批准并继续"), undefined);
    assert.equal(h.run("requestBlockerSection(data.request)"), null);
    await old.events.click();
    assert.equal(h.run("submitted.length"), 0, "retained callbacks cannot approve an already active role");
    assert.equal(h.run("JSON.stringify([data.request, data.task, operations])"), durable);
    h.step.lease_liveness = "LEASE_EXPIRED";
    if (status === "RUNNING") {
      assert.equal(h.run("requestNodeExecution(data.request).state"), "blocked");
      assert.equal(h.run("requestNodeExecution(data.request).status"), "EXECUTION_INTERRUPTED");
    }
    h.step.status = "WAITING_HUMAN";
    assert.equal(h.run("requestNodeExecution(data.request).state"), "blocked");
  });
}

test("current exact approvals and their facts are visible without opening engineering details", async () => {
  for (const kind of ["coder_scope", "coder_recovery", "prerequisite_repair", "candidate_verification"]) {
    const h = harness();
    const approval = currentApprovalFixture(h, kind);
    const box = h.run("recoveryApprovalBox(data.request, approval)");
    const visible = visibleDescend(box);
    const name = kind === "coder_scope" ? "批准文件范围" : "批准并继续";
    assert.ok(visible.some(node => node.tagName === "BUTTON" && node.textContent === name), kind);
    assert.ok(visible.some(node => node.textContent === approval.facts[0]), "the exact decision facts are not folded");
    assert.doesNotMatch(text(box), new RegExp(approval.plan_sha256), "opaque approval digest is never user input");
    assert.equal(h.run("submitted.length"), 0, "rendering never approves");
    await control(box, name).events.click();
    const submitted = JSON.parse(h.run("JSON.stringify(submitted[0])"));
    const field = kind === "coder_scope" ? "approved_scope_sha256" :
      kind === "prerequisite_repair" ? "approved_repair_sha256" : "approved_plan_sha256";
    assert.equal(submitted[field], approval.plan_sha256);
    assert.equal(submitted.expected_checkpoint_sha256, h.request.checkpoint_sha256);
    if (kind === "coder_scope") assert.deepEqual(submitted.coder_scope_request, approval.coder_scope_request);
  }
});

test("a previously prepared approval is hidden once a current role has been queued", () => {
  const h = harness();
  currentApprovalFixture(h);
  h.task.status = "QUEUED";
  h.step.status = "READY";
  h.step.wait_disposition = null;
  h.request.execution = {state: "QUEUED", responsibility: "engineering"};
  const panel = new Element("section");
  h.context.operationPanel = panel;
  assert.notEqual(h.run("requestPresentation(data.request).group"), "blocked", "exercise the distinct current-action placement");
  h.run("requestOperation(operationPanel, data.request)");
  assert.equal(control(panel, "批准并继续"), undefined,
    "a prepared historical decision cannot compete with current role dispatch");
  assert.equal(h.run("submitted.length"), 0);
});

test("unsupported recovery approvals show the service capability reason and disable their controls", async () => {
  for (const kind of ["coder_scope", "coder_recovery", "prerequisite_repair", "candidate_verification"]) {
    const h = harness();
    currentApprovalFixture(h, kind);
    h.run('consoleSupportedActions = consoleSupportedActions.filter(action => action !== "CONTINUE_DELIVERY")');
    const box = h.run("recoveryApprovalBox(data.request, approval)");
    const name = kind === "coder_scope" ? "批准文件范围" : "批准并继续";
    const approve = control(box, name);
    assert.equal(approve.disabled, true, kind);
    assert.ok(visibleDescend(box).some(node => /当前服务不支持恢复审批/.test(node.textContent)),
      "the capability reason must be visible without expanding technical details");
    assert.match(text(box), /原需求和已保存进度保留/);
    assert.doesNotMatch(text(box), /当前审批方案已变化/);
    await approve.events.click();
    assert.equal(h.run("submitted.length"), 0);
    assert.equal(h.run("operationNotice.title"), "当前服务不支持恢复审批");
  }
});

test("withdrawn recovery capability is checked again before submitting a retained approval", async () => {
  const h = harness();
  currentApprovalFixture(h);
  const old = control(h.run("recoveryApprovalBox(data.request, approval)"), "批准并继续");
  assert.notEqual(old.disabled, true);
  h.run('consoleOperationContractVersion = 0');
  await old.events.click();
  assert.equal(h.run("submitted.length"), 0);
  assert.equal(h.run("operationNotice.title"), "当前服务不支持恢复审批");
  h.run('consoleOperationContractVersion = 1');
  const current = control(h.run("recoveryApprovalBox(data.request, approval)"), "批准并继续");
  assert.equal(current.disabled, false);
  await current.events.click();
  assert.equal(h.run("submitted.length"), 1);
});

test("scope approval distinguishes an unchanged requested file from retained out-of-scope edits", () => {
  const h = harness();
  currentApprovalFixture(h, "coder_scope");
  h.request.blocker = "文件范围需要确认";
  const requested = text(h.run("requestBlockerSection(data.request)"));
  assert.match(requested, /申请补充文件范围.*尚未修改/);
  assert.doesNotMatch(requested, /文件改动超出原任务授权范围/);
  h.run('delete approval.coder_scope_request');
  const retained = text(h.run("requestBlockerSection(data.request)"));
  assert.match(retained, /文件改动超出原任务授权范围/);
  assert.doesNotMatch(retained, /尚未修改/);
});

test("every exact approval kind is consumed by its corresponding submitted digest", async () => {
  for (const kind of ["coder_scope", "coder_recovery", "prerequisite_repair", "candidate_verification"]) {
    const h = harness();
    const approval = currentApprovalFixture(h, kind);
    const old = control(h.run("recoveryApprovalBox(data.request, approval)"),
      kind === "coder_scope" ? "批准文件范围" : "批准并继续");
    const field = kind === "coder_scope" ? "approved_scope_sha256" :
      kind === "prerequisite_repair" ? "approved_repair_sha256" : "approved_plan_sha256";
    h.context.consumedField = field;
    h.run(`operations.push({operation_id: "approved", status: "SUCCEEDED", updated_at: "2026-10-05T02:00:00Z",
      intent: {action: "CONTINUE_DELIVERY", project_id: data.request.project_id, delivery_id: data.request.id,
        [consumedField]: approval.plan_sha256}})`);
    assert.equal(h.run("latestApproval(data.request.id, data.request.checkpoint_sha256)"), null, kind);
    await old.events.click();
    assert.equal(h.run("submitted.length"), 0, kind + " cannot revive the consumed current decision");
  }
});

test("detached exact approval callbacks cannot revive changed or historical decisions", async () => {
  for (const mutation of [
    'data.request.checkpoint_sha256 = "7".repeat(64)',
    'data.request.stage = "CLOSED"',
    'data.request.stage = "WAITING_PRODUCT_APPROVAL"',
    'operations[0].result.approval.plan_sha256 = "8".repeat(64)',
    'operations[0].result.approval.facts = ["不同的继续范围"]',
    'operations[0].status = "FAILED"',
    'operationsAvailable = false',
    'consoleSupportedActions = consoleSupportedActions.filter(action => action !== "CONTINUE_DELIVERY")',
    'snapshot.selected_project_id = "other_project"',
    'operations.push({operation_id: "consumed", status: "SUCCEEDED", updated_at: "2026-10-05T02:00:00Z", intent: {action: "CONTINUE_DELIVERY", project_id: data.request.project_id, delivery_id: data.request.id, approved_plan_sha256: "e".repeat(64)}})',
    'operations.push({operation_id: "active", status: "RUNNING", updated_at: "2026-10-05T02:00:00Z", intent: {action: "CONTINUE_DELIVERY", project_id: data.request.project_id, delivery_id: data.request.id}})',
  ]) {
    const h = harness();
    currentApprovalFixture(h);
    const old = control(h.run("recoveryApprovalBox(data.request, approval)"), "批准并继续");
    h.run(mutation);
    await old.events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});

test("pause shows its saved source without a proposal and refreshes the exact version during reconciliation", async () => {
  const h = harness();
  baselineFixture(h);
  Object.assign(h.step.wait_disposition.facts, {classification: "EXECUTION_BASELINE_PAUSED", execution_baseline_sha256: digest("8")});
  h.step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
  const box = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  const source = () => descend(box).find(node => node.className === "engineering-paused-source");
  const initialSource = source();
  assert.ok(initialSource, "the actual saved version is visible independently of the optional target form");
  assert.ok(visibleDescend(box).includes(initialSource));
  assert.match(text(initialSource), new RegExp("c".repeat(40)));
  assert.equal(descend(box).find(node => node.tagName === "INPUT").value, "", "no unverified target is guessed");
  const previousContinue = control(box, "继续原需求");
  h.context.retainedPause = box;
  h.task.last_activity = "2026-10-05T02:00:00Z";
  h.run("reconcileViewChildren(retainedPause, engineeringWaitBox(data.request, data.task, data.step))");
  assert.equal(source(), initialSource, "unrelated polling keeps the same saved-version node");
  Object.assign(h.step.wait_disposition.facts, {source_revision: "e".repeat(40), execution_baseline_sha256: digest("9")});
  h.step.wait_disposition_sha256 = digest("6");
  h.run("reconcileViewChildren(retainedPause, engineeringWaitBox(data.request, data.task, data.step))");
  assert.notEqual(source(), initialSource, "source/baseline binding changes invalidate the visible version");
  assert.match(text(source()), new RegExp("e".repeat(40)));
  assert.doesNotMatch(text(box), new RegExp("c".repeat(40)));
  assert.equal(h.run("submitted.length"), 0, "polling does not decide to continue");
  await previousContinue.events.click();
  assert.equal(h.run("submitted.length"), 0, "old callback cannot continue the new version");
  await control(box, "继续原需求").events.click();
  assert.equal(h.run("submitted[0].expected_source_revision"), "e".repeat(40));
  assert.equal(h.run("submitted[0].expected_execution_baseline_sha256"), digest("9"));
});
