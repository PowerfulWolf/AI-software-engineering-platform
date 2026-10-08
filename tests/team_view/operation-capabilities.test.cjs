const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.textContent = "";
    this.classList = {add() {}};
  }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute() {}
  addEventListener() {}
  set innerHTML(value) { throw new Error("Unsafe HTML: " + value); }
}
const text = node => node.textContent + node.children.map(item => typeof item === "string" ? item : text(item)).join(" ");

function harness() {
  const requests = [];
  const info = {schema_version: "v0.2", team_id: "team_fixture", delivery_ready: true};
  const request = {id: "request_fixture", project_id: "project_fixture", stage: "DELIVERING",
    checkpoint_sha256: "a".repeat(64), scopes: [{delivery_id: "delivery_fixture"}], documents: []};
  const step = {work_item_id: "work_fixture", role: "coder", status: "WAITING_HUMAN",
    wait_disposition_sha256: "b".repeat(64), wait_disposition: {responsibility: "engineering",
      reason: "原执行结果待核验。", next_action: "平台核验原执行。", facts: {task_id: "task_fixture",
        work_item_id: "work_fixture", task_intent_sha256: "c".repeat(64), source_revision: "d".repeat(40), checkpoint_sequence: 4}}};
  const task = {id: "delivery_fixture", task_id: "task_fixture", request_id: request.id,
    project_id: request.project_id, status: "IMPLEMENTING", terminal: false, role_queue: [step]};
  const data = {request, step, task};
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data,
    fetch: async (url, options = {}) => {
      requests.push({url, method: options.method || "GET", body: options.body});
      if (url === "/api/v1/console") return {ok: !context.consoleFailure, status: context.consoleFailure ? context.consoleStatus || 503 : 200,
        json: async () => {
          if (context.consoleInvalidJson) throw new SyntaxError("invalid fixture JSON");
          return structuredClone(context.info);
        }};
      if (options.method === "POST") return {ok: true, json: async () => ({operation_id: "operation_accepted",
        status: "QUEUED", intent: JSON.parse(options.body).intent})};
      throw new Error("Unexpected fixture request");
    }, info});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  vm.runInContext(source.slice(source.indexOf("async function refreshConsoleInfo("),
    source.indexOf("async function refreshOperations(")), context);
  vm.runInContext(`snapshot = {team_id: "team_fixture", selected_project_id: "project_fixture", projects: [],
    agents: [], tasks: [data.task], requests: [data.request]}; operationsAvailable = true;
    renderOperationStatus = () => {}; renderDetail = () => {}; renderNotification = () => {};`, context);
  return {context, data, requests, run: code => vm.runInContext(code, context),
    refresh: () => vm.runInContext("refreshConsoleInfo()", context),
    submit: action => {context.action = action; return vm.runInContext(
      'submitOperation({...engineeringWaitIntent(data.request, data.step), action})', context);},
    posts: () => requests.filter(item => item.method === "POST")};
}

test("legacy console cannot receive a new engineering command and shows an actionable Chinese mismatch", async () => {
  const h = harness();
  await h.refresh();
  const original = JSON.stringify(h.data);
  assert.equal(await h.submit("HANDLE_DELIVERY_WAIT"), null);
  assert.equal(h.posts().length, 0);
  assert.equal(JSON.stringify(h.data), original);
  assert.match(h.run("operationNotice.message"), /页面与服务版本不匹配/);
  assert.match(h.run("operationNotice.message"), /当前操作和角色执行结束、服务空闲时重启 Web Console/);
  const card = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(card), /页面与服务版本不匹配/);
  assert.match(text(card), /原需求和已保存进度保留/);
  assert.doesNotMatch(text(card), /本次请求未被受理/, "a page compatibility hint is not a command rejection");
});

test("capability withdrawal preserves an accepted active operation and its current wait advice", async () => {
  const h = harness();
  Object.assign(h.context.info, {operation_contract_version: 1, supported_actions: ["HANDLE_DELIVERY_WAIT"]});
  await h.refresh();
  h.run(`operations = [{operation_id: "operation_running", status: "RUNNING", updated_at: "2026-10-05T02:00:00Z",
    intent: {...engineeringWaitIntent(data.request, data.step), action: "HANDLE_DELIVERY_WAIT"}}];`);
  h.context.info.supported_actions = [];
  await h.refresh();
  const card = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(card), /平台正在处理中断/);
  assert.match(text(card), /当前不需要决定，请等待这次处理返回结果/);
  assert.match(text(card), /页面暂不能提交后续新操作/);
  assert.doesNotMatch(text(card), /本次请求未被受理|当前页面的处理操作未获当前服务支持/);
  assert.equal(h.run("operations[0].status"), "RUNNING");
  assert.equal(h.posts().length, 0);
});

test("capability withdrawal preserves a recorded decision without calling it rejected", async () => {
  const h = harness();
  Object.assign(h.context.info, {operation_contract_version: 1, supported_actions: ["HANDLE_DELIVERY_WAIT"]});
  await h.refresh();
  h.run(`(() => {
    const bound = engineeringWaitIntent(data.request, data.step);
    const proof = {task_id: data.task.task_id, work_item_id: bound.work_item_id,
      disposition_sha256: bound.expected_disposition_sha256, task_intent_sha256: bound.expected_task_intent_sha256,
      source_revision: bound.expected_source_revision, checkpoint_sequence: bound.expected_checkpoint_sequence,
      proof_sha256: "e".repeat(64), missing: [], permitted_resolutions: ["RETRY_FROM_CHECKPOINT"]};
    const handling = {kind: "delivery_wait_handling", schema_version: "v1", ...proof, investigation: proof,
      status: "RESOLVED", manual_resolution_allowed: false, handling_sha256: "f".repeat(64),
      resolution: {resolution_kind: "RETRY_FROM_CHECKPOINT", proof_sha256: proof.proof_sha256}};
    operations = [{operation_id: "operation_resolved", status: "SUCCEEDED", updated_at: "2026-10-05T02:00:00Z",
      intent: {...bound, action: "HANDLE_DELIVERY_WAIT"},
      result: {checkpoint_sha256: data.request.checkpoint_sha256, engineering_wait_handling: handling}}];
  })();`);
  h.context.info.supported_actions = [];
  await h.refresh();
  const card = h.run("engineeringWaitBox(data.request, data.task, data.step)");
  assert.match(text(card), /继续决定已保存/);
  assert.match(text(card), /当前不需要重复决定，请查看新的执行进展/);
  assert.match(text(card), /页面暂不能提交后续新操作/);
  assert.doesNotMatch(text(card), /本次请求未被受理|当前页面的处理操作未获当前服务支持/);
  assert.equal(h.run("operations[0].status"), "SUCCEEDED");
});

test("a matching manifest permits HANDLE while an unsupported action or contract cannot POST", async () => {
  for (const manifest of [
    {operation_contract_version: 1, supported_actions: ["INSPECT_DELIVERY_WAIT"]},
    {operation_contract_version: 0, supported_actions: ["HANDLE_DELIVERY_WAIT"]},
    {operation_contract_version: true, supported_actions: ["HANDLE_DELIVERY_WAIT"]},
    {operation_contract_version: 1, supported_actions: "HANDLE_DELIVERY_WAIT"},
    {operation_contract_version: 1, supported_actions: [null]},
  ]) {
    const h = harness();
    Object.assign(h.context.info, manifest);
    await h.refresh();
    assert.equal(await h.submit("HANDLE_DELIVERY_WAIT"), null);
    assert.equal(h.posts().length, 0, JSON.stringify(manifest));
  }
  for (const version of [1, 2]) {
    const h = harness();
    Object.assign(h.context.info, {operation_contract_version: version, supported_actions: ["HANDLE_DELIVERY_WAIT"]});
    await h.refresh();
    assert.equal((await h.submit("HANDLE_DELIVERY_WAIT")).operation_id, "operation_accepted");
    assert.equal(h.posts().length, 1);
    assert.equal(JSON.parse(h.posts()[0].body).intent.action, "HANDLE_DELIVERY_WAIT");
    assert.equal(await h.submit("CONTINUE_DELIVERY"), null, "the global submit guard also covers other actions");
    assert.equal(h.posts().length, 1);
  }
});

test("rescue API fields require contract two while original baseline actions remain version one compatible", async () => {
  for (const version of [1, 2]) {
    const h = harness();
    Object.assign(h.context.info, {operation_contract_version: version,
      supported_actions: ["PROPOSE_EXECUTION_BASELINE", "EXECUTE_EXECUTION_BASELINE"]});
    await h.refresh();
    assert.equal(h.run("consoleSupportsOperation('PROPOSE_EXECUTION_BASELINE')"), true);
    assert.equal(h.run("consoleSupportsLegacyRescue()"), version >= 2);
    const result = await h.run(`submitOperation({action: "PROPOSE_EXECUTION_BASELINE",
      project_id: data.request.project_id, delivery_id: data.request.id, purpose: "legacy_workspace_rescue"})`);
    assert.equal(result?.operation_id || null, version >= 2 ? "operation_accepted" : null);
    assert.equal(h.posts().length, version >= 2 ? 1 : 0);
  }
});

test("a local stop authorization requires contract three at the public submit boundary", async () => {
  for (const version of [1, 2, 3]) {
    const h = harness();
    Object.assign(h.context.info, {operation_contract_version: version,
      supported_actions: ["PROPOSE_EXECUTION_BASELINE", "EXECUTE_EXECUTION_BASELINE"]});
    await h.refresh();
    const result = await h.run(`submitOperation({action: "EXECUTE_EXECUTION_BASELINE",
      project_id: data.request.project_id, delivery_id: data.request.id, confirm_local_execution_stopped: true})`);
    assert.equal(result?.operation_id || null, version >= 3 ? "operation_accepted" : null);
    assert.equal(h.posts().length, version >= 3 ? 1 : 0);
  }
});

test("capability changes participate in rendering and failures clear previously supported commands", async () => {
  const h = harness();
  Object.assign(h.context.info, {operation_contract_version: 1, supported_actions: ["HANDLE_DELIVERY_WAIT"]});
  await h.refresh();
  const originalFacts = h.run("JSON.stringify(pollingControlFacts())");
  h.context.info.supported_actions = ["INSPECT_DELIVERY_WAIT"];
  await h.refresh();
  assert.notEqual(h.run("JSON.stringify(pollingControlFacts())"), originalFacts);
  assert.equal(await h.submit("HANDLE_DELIVERY_WAIT"), null);
  h.context.consoleFailure = true;
  await h.refresh();
  assert.equal(h.run("consoleOperationContractVersion"), null);
  assert.equal(h.run("consoleSupportedActions"), null);
  assert.equal(h.posts().length, 0);
});

test("404, invalid metadata and invalid JSON discard the prior manifest", async () => {
  for (const failure of ["missing", "metadata", "json"]) {
    const h = harness();
    Object.assign(h.context.info, {operation_contract_version: 1, supported_actions: ["HANDLE_DELIVERY_WAIT"]});
    await h.refresh();
    assert.equal(h.run("consoleSupportsOperation('HANDLE_DELIVERY_WAIT')"), true);
    if (failure === "missing") { h.context.consoleFailure = true; h.context.consoleStatus = 404; }
    if (failure === "metadata") h.context.info.schema_version = "invalid";
    if (failure === "json") h.context.consoleInvalidJson = true;
    await h.refresh();
    assert.equal(h.run("consoleOperationContractVersion"), null, failure);
    assert.equal(h.run("consoleSupportedActions"), null, failure);
    assert.equal(await h.submit("HANDLE_DELIVERY_WAIT"), null);
    assert.equal(h.posts().length, 0);
  }
});

test("old invalid-input rejection is Chinese and does not claim a new requirement blocker", () => {
  const h = harness();
  const explanation = h.run('humanizeBlockingText("Operation input is invalid.")');
  assert.match(explanation, /本次请求未被受理/);
  assert.match(explanation, /不是原需求新增的阻塞/);
  assert.doesNotMatch(explanation, /Operation input is invalid/);
});
