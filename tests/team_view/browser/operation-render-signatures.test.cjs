const assert = require("node:assert/strict");
const {test} = require("node:test");
const {ui, operation} = require("./fixture.cjs");

const sealed = (overrides = {}) => operation("SUCCEEDED", {
  operation_id: "operation_" + "a".repeat(32),
  operation_sha256: "b".repeat(64),
  result: {delivery_id: "request_fixture", next_action: "当次保留的完整处理建议"},
  ...overrides,
});

async function openRequest(h) {
  await h.requests();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
}

test("unchanged sealed operations never serialize the preserved large result into render signatures", async t => {
  const marker = "complete-preserved-baseline-patch:";
  const body = marker + "retained development progress\n".repeat(30000);
  const record = sealed({intent: {action: "PROPOSE_EXECUTION_BASELINE", project_id: "project_fixture",
    delivery_id: "request_fixture"}, result: {next_action: "旧基线计划仍保留",
    execution_baseline_plan: {purpose: "source_rebind", prepared_patch: body}}});
  const projectRecord = sealed({operation_id: "operation_" + "d".repeat(32), intent: {
    action: "PROPOSE_EXECUTION_BASELINE", project_id: "project_fixture", delivery_id: "request_deleted"},
    result: record.result});
  const h = await ui(t, {operations: [record, projectRecord]});
  await openRequest(h);
  await h.page.evaluate(marker => {
    const original = JSON.stringify;
    window.largeRenderSerializations = 0;
    window.largeRenderSerializationSites = [];
    JSON.stringify = function (...args) {
      const value = original.apply(this, args);
      if (value?.includes(marker)) {
        window.largeRenderSerializations++;
        window.largeRenderSerializationSites.push(new Error().stack.split("\n").slice(2, 5));
      }
      return value;
    };
  }, marker);
  await h.tick();
  assert.equal(await h.page.evaluate(() => largeRenderSerializations), 0,
    "an unchanged poll must not stringify the immutable baseline result");
  h.team.requests[0].next_action = "需求事实单独发生变化";
  await h.tick();
  assert.equal(await h.page.evaluate(() => largeRenderSerializations), 0,
    "changed Requirement facts must not stringify either full history result: " +
      JSON.stringify(await h.page.evaluate(() => largeRenderSerializationSites)));
  assert.equal(await h.page.evaluate(() => operations.length), 2);
  assert.equal(await h.page.evaluate(() => operations.every(value =>
    value.result.execution_baseline_plan.prepared_patch.length > 800000)), true,
  "complete API bodies remain available; only render signatures are compact");
});

test("a new complete operation digest updates history while an unchanged digest preserves its DOM", async t => {
  const h = await ui(t, {operations: [sealed()]});
  await openRequest(h);
  const history = h.page.locator('#detail details[data-key="operation-history:project_fixture/request_fixture"]');
  await history.locator(":scope > summary").click();
  const row = history.locator(".execution-history-entry");
  await row.evaluate(node => {window.originalOperationRow = node;});
  await h.tick();
  assert.equal(await row.evaluate(node => node === window.originalOperationRow), true);
  h.state.operations[0].operation_sha256 = "c".repeat(64);
  h.state.operations[0].result.next_action = "新的完整结果需要展示";
  await h.tick();
  assert.match(await row.innerText(), /新的完整结果需要展示/);
  assert.equal(await row.evaluate(node => node === window.originalOperationRow), false);
  assert.equal(await history.evaluate(node => node.open), true);
});

test("missing or invalid operation identities and digests retain complete-facts invalidation", async t => {
  const cases = [undefined, "not-a-digest", "G".repeat(64)].map((digest, index) => ({
    operation_id: "operation_" + String(index).repeat(32), operation_sha256: digest,
  }));
  cases.push({operation_id: "operation_invalid", operation_sha256: "b".repeat(64)});
  const records = cases.map((identity, index) => sealed({
    ...identity,
    result: {next_action: "原历史建议 " + index},
  }));
  const h = await ui(t, {operations: records});
  await openRequest(h);
  await h.page.locator('#detail details[data-key="operation-history:project_fixture/request_fixture"] > summary').click();
  for (const [index, record] of h.state.operations.entries())
    record.result.next_action = "已更新的兼容历史建议 " + index;
  await h.tick();
  const detail = h.page.locator("#detail");
  for (let index = 0; index < records.length; index++)
    assert.match(await detail.innerText(), new RegExp("已更新的兼容历史建议 " + index));
});

test("compact operation signatures cannot authorize a superseded recovery plan or checkpoint", async t => {
  const record = sealed({result: {delivery_id: "request_fixture", checkpoint_sha256: "a".repeat(64),
    stage: "WAITING_HUMAN", next_action: "核对精确恢复方案", approval: {kind: "coder_recovery",
      plan_sha256: "d".repeat(64), title: "确认保留进度继续", facts: ["保留完整开发进度"]}}});
  const h = await ui(t, {operations: [record]});
  h.team.requests[0].stage = "WAITING_HUMAN";
  await h.tick();
  await openRequest(h);
  let writes = 0;
  h.page.on("request", request => {if (request.method() !== "GET") writes++;});
  const approve = h.page.locator("#detail").getByRole("button", {name: "批准并继续", exact: true});
  await approve.evaluate(node => {window.supersededRecoveryApproval = node;});
  await h.tick();
  assert.equal(await approve.evaluate(node => node === window.supersededRecoveryApproval), true);
  record.operation_sha256 = "e".repeat(64);
  record.result.approval.plan_sha256 = "f".repeat(64);
  await h.tick();
  assert.equal(await h.page.evaluate(() => supersededRecoveryApproval.isConnected), false);
  await h.page.evaluate(async () => {supersededRecoveryApproval.click(); await Promise.resolve();});
  assert.equal(writes, 0, "the old exact plan cannot be approved by a retained callback");
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await approve.evaluate(node => {window.oldCheckpointApproval = node;});
  h.team.requests[0].checkpoint_sha256 = "9".repeat(64);
  await h.tick();
  assert.equal(await approve.count(), 0);
  await h.page.evaluate(async () => {oldCheckpointApproval.click(); await Promise.resolve();});
  assert.equal(writes, 0, "unchanged operation digests cannot restore a stale Requirement checkpoint");
});
