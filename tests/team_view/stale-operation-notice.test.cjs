// Notification filtering uses the actual renderer; APIs and durable operations stay read-only.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const operation = (status, action, overrides = {}) => ({
  operation_id: "old_product_approval", status,
  updated_at: "2026-09-21T00:00:00Z",
  intent: { action, project_id: "project_current", delivery_id: "request_current" },
  error_summary: "旧产品批准后的交付操作中断。",
  ...overrides,
});
const oldFailure = () => operation("INTERRUPTED", "PRODUCT_APPROVAL");
const nextContinue = (overrides = {}) => operation("SUCCEEDED", "CONTINUE_DELIVERY", {
  operation_id: "new_continue", updated_at: "2026-10-10T12:00:00Z",
  result: { delivery_id: "request_current", stage: "BLOCKED", checkpoint_sha256: "a".repeat(64),
    approval: { kind: "coder_recovery", title: "保留进度并继续原需求", plan_sha256: "b".repeat(64) } },
  ...overrides,
});

function harness(records) {
  const panel = { hidden: false, replaceChildren() {} };
  const context = vm.createContext({ records, document: { getElementById: () => panel } });
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  const run = code => vm.runInContext(code, context);
  run(`snapshot = {team_id: "team_current", selected_project_id: "project_current", agents: [], tasks: [],
    projects: [{id: "project_current", name: "当前项目"}], requests: [{id: "request_current",
      project_id: "project_current", stage: "BLOCKED", checkpoint_sha256: "${"a".repeat(64)}",
      scopes: [], documents: []}]};
    page = "requests"; operations = records; operationsAvailable = true;
    consoleAvailable = true; consoleDeliveryReady = true;
    renderNotification = () => {};`);
  return { records, run, render: () => { run("renderOperationStatus()"); return run("operationNotice"); },
    close: () => run("acknowledgeOperationNotice(operationNotice); renderOperationStatus()") };
}

test("a later Continue with a recovery approval removes an old interrupted Product approval notice", () => {
  const h = harness([oldFailure()]);
  assert.equal(h.render().operationId, "old_product_approval");
  h.records.push(nextContinue());
  const saved = JSON.stringify(h.records);
  assert.equal(h.render(), null, "the current prepared approval replaces the obsolete failure dialog");
  assert.equal(h.run('latestApproval("request_current", "a".repeat(64), "project_current").plan_sha256'), "b".repeat(64));
  for (let tick = 0; tick < 3; tick++) assert.equal(h.render(), null);
  assert.equal(JSON.stringify(h.records), saved, "filtering cannot rewrite operation history");
});

test("current human attention still appears once without reviving an older cross-action failure", () => {
  const current = nextContinue({result: {delivery_id: "request_current", stage: "BLOCKED",
    diagnostic: "请查看当前缺项。", checkpoint_sha256: "a".repeat(64)}});
  const h = harness([oldFailure(), current]);
  assert.equal(h.render().operationId, "new_continue");
  assert.equal(h.render().state, "ACTION_REQUIRED");
  h.close();
  assert.equal(h.render(), null, "closing the current notice cannot reveal an obsolete failure");
  assert.equal(h.render(), null);
});

test("a new failure still replaces a previous cross-action error and can be acknowledged", () => {
  const h = harness([oldFailure(), nextContinue({status: "FAILED", result: null, error_summary: "本次新的失败。"})]);
  assert.equal(h.render().operationId, "new_continue");
  assert.equal(h.render().state, "FAILED");
  h.close();
  assert.equal(h.render(), null);
});

test("a later running Continue replaces an interrupted Product approval and stays closed after acknowledgement", () => {
  const h = harness([oldFailure()]);
  assert.equal(h.render().state, "INTERRUPTED");
  h.records.push(nextContinue({status: "RUNNING", result: null}));
  assert.equal(h.render().operationId, "new_continue");
  assert.equal(h.render().state, "ACTIVE");
  h.close();
  assert.equal(h.render(), null);
  assert.equal(h.render(), null);
});

for (const scope of ["project", "requirement"]) {
  test(`a later operation in another ${scope} cannot suppress the current failure`, () => {
    const newer = nextContinue();
    if (scope === "project") newer.intent.project_id = "other_project";
    else { newer.intent.delivery_id = "other_request"; newer.result.delivery_id = "other_request"; }
    const h = harness([oldFailure(), newer]);
    assert.equal(h.render().operationId, "old_product_approval");
  });
}

test("another Project with the same target cannot suppress current human attention", () => {
  const current = nextContinue({result: {delivery_id: "request_current", stage: "BLOCKED", diagnostic: "当前事项。"}});
  const foreign = nextContinue({operation_id: "foreign", updated_at: "2026-10-10T13:00:00Z",
    intent: {...current.intent, project_id: "other_project"}});
  const h = harness([current, foreign]);
  assert.equal(h.render()?.operationId, "new_continue");
});

test("independent administration actions without a target retain separate failure notices", () => {
  const old = operation("FAILED", "CREATE_PROJECT", {intent: {action: "CREATE_PROJECT", project_id: "project_current"}});
  const newer = nextContinue({intent: {action: "UPDATE_SETTINGS", project_id: "project_current"}, result: null});
  const h = harness([old, newer]);
  assert.equal(h.render().operationId, "old_product_approval");
});

test("same-action retry still consumes the prior failure notification", () => {
  const h = harness([operation("FAILED", "CONTINUE_DELIVERY"), nextContinue()]);
  assert.equal(h.render(), null);
});
