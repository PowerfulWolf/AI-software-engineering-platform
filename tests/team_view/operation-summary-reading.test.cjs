const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const digest = digit => digit.repeat(64);
const summary = (index = 1, overrides = {}) => ({
  operation_id: "operation_" + String(index).padStart(32, "0"), team_id: "team_current",
  project_id: "project_current", delivery_id: "request_current", action: "CONTINUE_DELIVERY",
  status: "SUCCEEDED", sequence: 3, requested_at: "2026-10-12T00:00:00Z",
  updated_at: "2026-10-12T00:01:00Z", operation_sha256: digest("a"), has_details: true,
  result_checkpoint_sha256: digest("b"), summary: "当次处理完成", ...overrides,
});
const page = (items, overrides = {}) => ({schema_version: "v0.1", team_id: "team_current",
  scope: {project_id: "project_current", delivery_id: "request_current"},
  inventory_sha256: digest("c"), items, total_count: items.length, active: [],
  active_complete: true, next_cursor: null, ...overrides});

function harness() {
  const requests = [], replies = [];
  const context = vm.createContext({TextEncoder, URLSearchParams, AbortController,
    console, structuredClone, document: {createElement: () => ({})},
    fetch: async (url, options) => {
      requests.push({url, options});
      const reply = replies.shift();
      if (!reply) throw new Error("Unexpected request: " + url);
      if (reply.beforeResponse) reply.beforeResponse();
      return {ok: (reply.status || 200) < 400, status: reply.status || 200,
        headers: {get: () => reply.etag || '"current"'}, json: async () => reply.body};
    },
  });
  const source = fs.readFileSync(path.join(__dirname,
    "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  vm.runInContext(source.slice(source.indexOf("async function refreshConsoleInfo("),
    source.indexOf("async function refreshSettingsSnapshot(")), context);
  const run = expression => vm.runInContext(expression, context);
  run(`snapshot = {team_id:"team_current", selected_project_id:"project_current", requests:[{
    id:"request_current", project_id:"project_current", checkpoint_sha256:"${digest("b")}",
    scopes:[], stage:"BLOCKED"}], tasks:[], agents:[]};
    consoleTeamId="team_current"; consoleOperationSummaryContractVersion="v0.1";
    selected={kind:"request", id:"request_current"};`);
  return {run, context, requests, replies};
}

test("summary pages are separate reading facts and 304 reuses only the same verified scope", async () => {
  const h = harness();
  h.replies.push({body: page([summary()])});
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  assert.equal(h.requests[0].url.startsWith("/api/v1/operation-summaries?"), true);
  assert.equal(h.run("operations.length"), 0, "a summary never becomes a full Operation");
  assert.equal(h.run("operationReadingRecords()[0].intent"), undefined);
  h.replies.push({status: 304});
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  assert.equal(h.requests[1].options.headers["If-None-Match"], '"current"');
  assert.equal(h.run("operationReadingRecords().length"), 1);
});

test("incomplete active facts, foreign scope and unbounded pages fail closed", async () => {
  for (const invalid of [page([], {active_complete: false}),
    page([summary(1, {project_id: "foreign"})]), page(Array.from({length: 51}, (_, i) => summary(i + 1)))]) {
    const h = harness();
    h.replies.push({body: invalid});
    await assert.rejects(h.run('readOperationSummaryPage("project_current", "request_current")'));
    assert.equal(h.run("operations.length"), 0);
  }
});

test("active records outside the first history page still prevent duplicate delivery", async () => {
  const h = harness();
  h.replies.push({body: page([summary()], {active: [summary(2, {status: "RUNNING", sequence: 2})]})});
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  h.run("operationsAvailable=true");
  assert.equal(h.run('activeOperation("request_current", "project_current").operation_id'),
    summary(2).operation_id);
});

test("single full detail must match the latest digest and never admits a drifted approval", async () => {
  const h = harness();
  const source = summary();
  h.replies.push({body: page([source])});
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  h.context.source = source;
  h.replies.push({body: {...source, operation_sha256: digest("d"), intent: {
    action: source.action, project_id: source.project_id, delivery_id: source.delivery_id}}});
  await assert.rejects(h.run("readFullOperation(source, {fresh:true})"));
  assert.equal(h.run("operations.length"), 0);
});

test("history pagination keeps all records and stale cursors cannot merge changed inventories", async () => {
  const h = harness();
  const first = page([summary(1)], {next_cursor: "cursor-first", total_count: 3});
  h.replies.push({body: first});
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  h.run('operationHistoryPage("project_current", "request_current")');
  h.replies.push({body: page([summary(2), summary(3)], {total_count: 3})});
  await h.run('loadMoreOperationHistory("project_current", "request_current")');
  assert.equal(h.run('operationHistoryPage("project_current", "request_current").items.length'), 2);
  assert.equal(h.run('operationHistoryPage("project_current", "request_current").back[0].items.length'), 1);
  const other = harness();
  other.replies.push({body: first});
  await other.run('readOperationSummaryPage("project_current", "request_current")');
  other.run('operationHistoryPage("project_current", "request_current")');
  other.replies.push({status: 409});
  await assert.rejects(other.run('loadMoreOperationHistory("project_current", "request_current")'));
  assert.equal(other.run('operationHistoryPage("project_current", "request_current").items.length'), 1);
});

const full = source => ({...source, schema_version:"v0.1", intent:{action:source.action,
  project_id:source.project_id, delivery_id:source.delivery_id, expected_checkpoint_sha256:digest("b")},
  result:{delivery_id:source.delivery_id, checkpoint_sha256:digest("b"), stage:"BLOCKED",
    approval:{kind:"coder_recovery", plan_sha256:digest("e"), title:"保留进度继续", facts:["完整进度已保留"]}}});
const manifest = () => ({schema_version:"v0.2", team_id:"team_current", delivery_ready:true,
  operation_contract_version:6, supported_actions:["CONTINUE_DELIVERY"], operation_summary_contract_version:"v0.1"});

test("hydrating an independent same-Project result cannot supply a current approval", async () => {
  const h = harness(), source = summary(1, {result_scope_relation:"UNVERIFIED_RESOURCE",
    result_project_id:"project_current", result_delivery_id:"request_independent",
    result_checkpoint_sha256:null, intent_checkpoint_sha256:digest("b"), summary:null});
  const value = full(source);
  value.result.project_id = "project_current";
  value.result.delivery_id = "request_independent";
  value.result.checkpoint_sha256 = digest("d");
  h.replies.push({body:page([source])}, {body:value});
  await h.run("loadCurrentOperationDetails()");
  h.run("operationsAvailable=true");
  assert.equal(h.run('latestApproval("request_current", "' + digest("b") + '")'), null);
  assert.equal(h.run("recordedOperationOutcome(operationReadingRecords()[0])"), null);
  assert.equal(h.run("operationNeedsHumanAttention(operationReadingRecords()[0])"), false);
  h.context.foreignApproval = JSON.stringify(value.result.approval);
  h.run('consoleAvailable=true; consoleDeliveryReady=true; consoleOperationContractVersion=6; consoleSupportedActions=["CONTINUE_DELIVERY"]; renderDetail=()=>{}; renderNotification=()=>{}');
  const decision = await h.run('submitRecoveryApprovalOperation({action:"CONTINUE_DELIVERY", project_id:"project_current", delivery_id:"request_current", expected_checkpoint_sha256:"' + digest("b") + '", approved_plan_sha256:"' + digest("e") + '"}, foreignApproval)');
  assert.equal(decision, null);
  assert.equal(h.requests.some(request => request.options?.method === "POST"), false);
});

test("old summary locators cannot authorize a hydrated independent full result", async () => {
  const h = harness(), source = summary();
  const value = full(source);
  value.result.project_id = "project_current";
  value.result.delivery_id = "request_independent";
  h.replies.push({body:page([source])}, {body:value});
  await h.run("loadCurrentOperationDetails()");
  h.run("operationsAvailable=true");
  assert.equal(h.run('latestApproval("request_current", "' + digest("b") + '")'), null);
  assert.equal(h.run("recordedOperationOutcome(operationReadingRecords()[0])"), null);
});

test("foreign Project and forged result-relation metadata refuse complete hydration", async () => {
  for (const wrong of ["project", "relation", "delivery"]) {
    const h = harness(), source = summary(1, {result_scope_relation:"SAME_RESOURCE",
      result_project_id:"project_current", result_delivery_id:"request_current"});
    const value = full(source); value.result.project_id = "project_current";
    if (wrong === "project") value.result.project_id = "project_foreign";
    if (wrong === "relation") value.result.delivery_id = "request_independent";
    if (wrong === "delivery") source.result_delivery_id = "request_independent";
    h.replies.push({body:page([source])}, {body:value});
    await assert.rejects(h.run("loadCurrentOperationDetails()"));
    assert.equal(h.run("operations.length"), 0);
    assert.equal(h.requests.some(request => request.options?.method === "POST"), false);
  }
});

test("independent summary results cannot smuggle current stage or approval locators", async () => {
  for (const mutation of [{result_stage:"DONE"}, {approval_kind:"coder_recovery"},
    {baseline_plan_sha256:digest("e")}, {next_step:"继续原需求"}, {has_baseline_binding:true},
    {result_scope_relation:"NO_RESOURCE", action:"CONTINUE_DELIVERY", result_delivery_id:null}]) {
    const h = harness(), source = summary(1, {result_scope_relation:"UNVERIFIED_RESOURCE",
      result_project_id:"project_current", result_delivery_id:"request_independent",
      result_checkpoint_sha256:null, summary:null, ...mutation});
    h.replies.push({body:page([source])});
    await assert.rejects(h.run('readOperationSummaryPage("project_current", "request_current")'));
    assert.equal(h.run("operationSummaryPages.size"), 0);
  }
});

test("only deletion has a command-only no-resource result; other missing resources remain unverified", async () => {
  for (const [action, relation] of [["DELETE_REQUIREMENT", "NO_RESOURCE"], ["CONTINUE_DELIVERY", "UNVERIFIED_RESOURCE"]]) {
    const h = harness(), source = summary(1, {action, result_scope_relation:relation,
      result_project_id:"project_current", result_delivery_id:null, result_checkpoint_sha256:null,
      intent_checkpoint_sha256:digest("b"), summary:null});
    const value = full(source); value.result = {project_id:"project_current", stage:"REQUIREMENT_DELETED", next_action:"历史结果"};
    h.replies.push({body:page([source])}, {body:value});
    await h.run("loadCurrentOperationDetails()");
    h.run("operationsAvailable=true");
    assert.equal(h.run("operationResultScopeRelation(operations[0])"), relation);
    assert.equal(h.run("operationResult(operations[0])"), null);
    assert.equal(h.run("recordedOperationOutcome(operations[0])"), null);
  }
});

test("a real create-project result supplies its new identity for scoped full history", async () => {
  const h = harness(), source = summary(1, {action:"CREATE_PROJECT", delivery_id:null,
    result_scope_relation:"CREATED_RESOURCE", result_project_id:"project_current", result_delivery_id:null,
    result_checkpoint_sha256:null, summary:null});
  const value = full(source); value.intent = {action:"CREATE_PROJECT", name:"New Project"};
  value.result = {project_id:"project_current", stage:"CREATED", next_action:"查看项目"};
  const scoped = page([source], {scope:{project_id:"project_current", delivery_id:null}});
  h.replies.push({body:scoped}, {body:value});
  await h.run('readOperationSummaryPage("project_current", null)');
  h.context.source = source;
  const record = await h.run('readFullOperation(source, {fresh:true})');
  assert.equal(record, value);
  assert.equal(h.run('operationProject(operationDetailCache.get(source.operation_id).value)'), "project_current");
});

test("the shipped refresh uses summary polling and loads only the current exact full record", async () => {
  const h = harness(), source = summary();
  h.replies.push({body:manifest()}, {body:page([source], {scope:{project_id:"project_current", delivery_id:null}})},
    {body:page([source])}, {body:full(source)});
  await h.run("refreshOperations()");
  assert.equal(h.run("operationsAvailable"), true);
  assert.equal(h.run('latestApproval("request_current", "' + digest("b") + '").kind'), "coder_recovery");
  assert.equal(h.requests.some(request => request.url === "/api/v1/operations"), false);
  assert.equal(h.requests.filter(request => request.url === "/api/v1/operations/" + source.operation_id).length, 1);
  h.replies.push({body:manifest()}, {status:304}, {status:304});
  await h.run("refreshOperations()");
  assert.equal(h.run("operationsAvailable"), true);
  assert.equal(h.requests.filter(request => request.url === "/api/v1/operations/" + source.operation_id).length, 1);
});

test("a changed current full record revokes the prepared approval before any write", async () => {
  const h = harness(), source = summary();
  h.replies.push({body:page([source])}, {body:full(source)});
  await h.run("loadCurrentOperationDetails()");
  h.run('consoleAvailable=true; consoleDeliveryReady=true; operationsAvailable=true; consoleOperationContractVersion=6; consoleSupportedActions=["CONTINUE_DELIVERY"]');
  h.context.intent = {action:"CONTINUE_DELIVERY", project_id:"project_current",
    delivery_id:"request_current", expected_checkpoint_sha256:digest("b"), approved_plan_sha256:digest("e")};
  h.replies.push({status:304}, {body:{...full(source), operation_sha256:digest("d")}});
  await assert.rejects(h.run("recheckOperationWriteFacts(intent)"));
  assert.equal(h.run("operationsAvailable"), false);
  assert.equal(h.requests.filter(request => request.url === "/api/v1/operations/" + source.operation_id).length, 2);
  assert.equal(h.requests.every(request => request.options?.method !== "POST"), true);
});

test("current-scope changes during a fresh full read cannot authorize an old callback", async () => {
  const h = harness(), source = summary();
  h.replies.push({body:page([source])}, {body:full(source)});
  await h.run("loadCurrentOperationDetails()");
  h.run('consoleAvailable=true; consoleDeliveryReady=true; operationsAvailable=true; consoleOperationContractVersion=6; consoleSupportedActions=["CONTINUE_DELIVERY"]');
  h.context.intent = {action:"CONTINUE_DELIVERY", project_id:"project_current", delivery_id:"request_current"};
  h.replies.push({status:304});
  const reply = {body:full(source)};
  Object.defineProperty(reply, "body", {get() {
    h.run('selectionIntentRevision++; selected = null');
    return full(source);
  }});
  h.replies.push(reply);
  await assert.rejects(h.run("recheckOperationWriteFacts(intent)"));
  assert.equal(h.requests.filter(request => request.url === "/api/v1/operations/" + source.operation_id).length, 2);
  assert.equal(h.requests.every(request => request.options?.method !== "POST"), true);
});

test("a summary read failure preserves reading but cannot restore current control", async () => {
  const h = harness(), source = summary();
  h.replies.push({body:manifest()}, {body:page([source], {scope:{project_id:"project_current", delivery_id:null}})},
    {body:page([source])}, {body:full(source)});
  await h.run("refreshOperations()");
  h.replies.push({body:manifest()}, {status:503});
  await h.run("refreshOperations()");
  assert.equal(h.run("operationsAvailable"), false);
  assert.equal(h.run('latestApproval("request_current", "' + digest("b") + '")'), null);
  assert.equal(h.run("operationReadingRecords().length"), 1);
});

test("a complete unchanged fresh read permits the exact existing approval without making a new one", async () => {
  const h = harness(), source = summary();
  h.replies.push({body:manifest()}, {body:page([source], {scope:{project_id:"project_current", delivery_id:null}})},
    {body:page([source])}, {body:full(source)});
  await h.run("refreshOperations()");
  h.context.intent = {action:"CONTINUE_DELIVERY", project_id:"project_current", delivery_id:"request_current",
    expected_checkpoint_sha256:digest("b"), approved_plan_sha256:digest("e")};
  const approval = h.run('JSON.stringify(latestApproval("request_current", "' + digest("b") + '"))');
  h.replies.push({status:304}, {body:full(source)});
  await h.run("recheckOperationWriteFacts(intent)");
  assert.equal(h.run('JSON.stringify(latestApproval("request_current", "' + digest("b") + '"))'), approval);
  assert.equal(h.run("canControlCurrentTeam()"), true);
});

test("an older page detail is a reading source and cannot enter current approval operations", async () => {
  const h = harness(), source = summary(1), old = summary(2, {result_checkpoint_sha256:digest("d")});
  h.replies.push({body:page([source], {next_cursor:"older", total_count:2})});
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  h.run('operationHistoryPage("project_current", "request_current")');
  h.replies.push({body:page([old], {total_count:2})});
  await h.run('loadMoreOperationHistory("project_current", "request_current")');
  h.context.old = old;
  h.replies.push({body:full(old)});
  await h.run("readFullOperation(old, {fresh:true})");
  assert.equal(h.run("operationDetailCache.size"), 1);
  assert.equal(h.run("operations.length"), 0);
});

test("old Team pages cannot participate in active work even with the same project and delivery", async () => {
  const h = harness();
  h.replies.push({body:page([], {active:[summary(2, {status:"RUNNING"})]})});
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  h.run('operationsAvailable=true; consoleTeamId="team_other"; snapshot.team_id="team_other"');
  assert.equal(h.run('activeOperation("request_current", "project_current")'), undefined);
  h.run("clearOperationReadScope()");
  assert.equal(h.run("operationSummaryPages.size + operationHistoryPages.size + operationDetailCache.size"), 0);
});

test("detail cache count and UTF8 byte eviction can never leave a current READY reading gate", () => {
  const h = harness();
  h.context.records = Array.from({length:9}, (_, index) => full(summary(index+1)));
  h.run('currentOperationSources=records; operationDetailReadyScope="prepared"; records.forEach(cacheFullOperation)');
  assert.equal(h.run("operationDetailCache.size"), 8);
  assert.equal(h.run("operationDetailReadyScope"), null);
  h.run('clearOperationReadScope(); currentOperationSources=records.slice(0,3); operationDetailReadyScope="prepared"');
  h.run('records.slice(0,3).forEach(value => cacheFullOperation({...value, reading_body:"x".repeat(11*1024*1024)}))');
  assert.ok(h.run('[...operationDetailCache.values()].reduce((sum,item)=>sum+item.bytes,0)') <= 32*1024*1024);
  assert.equal(h.run("operationDetailReadyScope"), null);
});

test("a Team switch during an empty-source cached read prevents the real submitOperation POST", async () => {
  const h = harness();
  h.run(`selected=null; consoleAvailable=true; consoleDeliveryReady=true; operationsAvailable=true;
    consoleOperationContractVersion=6; consoleSupportedActions=["CREATE_REQUIREMENT"];
    renderNotification=()=>{}; renderOperationStatus=()=>{}; renderDetail=()=>{}; observeSubmittedOperation=()=>{};`);
  h.replies.push({body:page([], {scope:{project_id:"project_current", delivery_id:null}})});
  await h.run('readOperationSummaryPage("project_current", null)');
  h.replies.push({status:304, beforeResponse() {
    h.run('clearOperationReadScope(); consoleTeamId="team_other"; snapshot.team_id="team_other"; operationsAvailable=true');
  }});
  const result = await h.run('submitOperation({action:"CREATE_REQUIREMENT", project_id:"project_current", name:"Exact original Team"})');
  assert.equal(result, null);
  assert.equal(h.requests.some(request => request.options?.method === "POST"), false);
  assert.equal(h.run("operationSummaryPages.size"), 0);
});

test("a late 200 summary cannot publish under a different Team even with reused project identities", async () => {
  const h = harness();
  h.replies.push({body:page([], {team_id:"team_other"}), beforeResponse() {
    h.run('clearOperationReadScope(); consoleTeamId="team_other"; snapshot.team_id="team_other"');
  }});
  await assert.rejects(h.run('readOperationSummaryPage("project_current", "request_current")'));
  assert.equal(h.run("operationSummaryPages.size"), 0);
});

test("a capability downgrade during a cached read prevents the real submitOperation POST", async () => {
  const h = harness();
  h.run(`selected=null; consoleAvailable=true; consoleDeliveryReady=true; operationsAvailable=true;
    consoleOperationContractVersion=6; consoleSupportedActions=["CREATE_REQUIREMENT"];
    renderNotification=()=>{}; renderOperationStatus=()=>{}; renderDetail=()=>{}; observeSubmittedOperation=()=>{};`);
  h.replies.push({body:page([], {scope:{project_id:"project_current", delivery_id:null}})});
  await h.run('readOperationSummaryPage("project_current", null)');
  h.replies.push({status:304, beforeResponse() {
    h.run('consoleSupportedActions=[]; consoleOperationContractVersion=1');
  }});
  assert.equal(await h.run('submitOperation({action:"CREATE_REQUIREMENT", project_id:"project_current"})'), null);
  assert.equal(h.requests.some(request => request.options?.method === "POST"), false);
});

test("a late full detail cannot restore a cache after its original reading owner was cleared", async () => {
  const h = harness(), source = summary();
  h.replies.push({body:page([source])});
  await h.run('readOperationSummaryPage("project_current", "request_current")');
  h.context.source = source;
  h.replies.push({body:full(source), beforeResponse() {
    h.run('clearOperationReadScope(); operationsAvailable=true');
  }});
  await assert.rejects(h.run('readFullOperation(source, {fresh:true})'));
  assert.equal(h.run("operationDetailCache.size"), 0);
  assert.equal(h.run("operationsAvailable"), true, "an old callback must not revoke the newer owner");
});

test("an unchanged empty-source read permits the real create submission despite unrelated active delivery", async () => {
  const h = harness();
  h.run(`selected=null; consoleAvailable=true; consoleDeliveryReady=true; operationsAvailable=true;
    consoleOperationContractVersion=6; consoleSupportedActions=["CREATE_REQUIREMENT"];
    renderNotification=()=>{}; renderOperationStatus=()=>{}; renderDetail=()=>{}; observeSubmittedOperation=()=>{};`);
  const operation = summary(9, {action:"CREATE_REQUIREMENT", delivery_id:null, status:"QUEUED", sequence:1});
  h.replies.push({body:page([], {scope:{project_id:"project_current", delivery_id:null},
    active:[summary(2, {status:"RUNNING"})]})},
    {body:{...operation, intent:{action:operation.action, project_id:operation.project_id}}});
  const result = await h.run('submitOperation({action:"CREATE_REQUIREMENT", project_id:"project_current", name:"New requirement"})');
  assert.equal(result?.operation_id, operation.operation_id);
  assert.equal(h.requests.filter(request => request.options?.method === "POST").length, 1);
});
