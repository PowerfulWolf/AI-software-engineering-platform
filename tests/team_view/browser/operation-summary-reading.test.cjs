const {test} = require("node:test");
const assert = require("node:assert/strict");
const {ui} = require("./fixture.cjs");

async function summaryUI(t) {
  const h = await ui(t);
  const records = Array.from({length:61}, (_, index) => ({
    operation_id:"operation_" + String(1000 + index).padStart(32,"0"), team_id:"team_fixture",
    project_id:"project_fixture", delivery_id:"request_fixture", action:"CONTINUE_DELIVERY",
    status:"SUCCEEDED", sequence:3, requested_at:`2026-10-12T00:${String(59-Math.min(index,59)).padStart(2,"0")}:00Z`,
    updated_at:"2026-10-12T01:00:00Z", operation_sha256:"b".repeat(64), has_details:true,
    result_checkpoint_sha256:index === 0 ? "a".repeat(64) : "c".repeat(64),
    approval_kind:index === 0 ? "coder_recovery" : null,
    approval_plan_sha256:index === 0 ? "e".repeat(64) : null,
    summary:"当次记录摘要 " + index,
  }));
  const reads = [], fullReads = [], writes = [];
  let drift = false;
  const full = record => ({...record, schema_version:"v0.1", intent:{action:record.action,
    project_id:record.project_id, delivery_id:record.delivery_id,
    expected_checkpoint_sha256:record.result_checkpoint_sha256},
    result:{delivery_id:record.delivery_id, checkpoint_sha256:record.result_checkpoint_sha256,
      stage:"BLOCKED", diagnostic:"历史完整原因 " + records.indexOf(record), next_action:"当次建议处理",
      ...(record.approval_kind ? {approval:{kind:"coder_recovery", title:"保留完整进度继续",
        facts:["已检查并保留完整开发进度"], plan_sha256:record.approval_plan_sha256}} : {})}});
  await h.page.route("**/api/v1/operation-summaries?**", route => {
    const url = new URL(route.request().url());
    reads.push(url);
    if (route.request().headers()["if-none-match"]) return route.fulfill({status:304});
    const offset = Number(url.searchParams.get("cursor") || 0);
    return route.fulfill({headers:{ETag:'"same-inventory"'}, json:{schema_version:"v0.1",
      team_id:"team_fixture", scope:{project_id:url.searchParams.get("project_id"),
        delivery_id:url.searchParams.get("delivery_id")}, inventory_sha256:"f".repeat(64),
      items:records.slice(offset,offset+25), active:[], active_complete:true,
      next_cursor:offset+25 < records.length ? String(offset+25) : null, total_count:records.length}});
  });
  await h.page.route("**/api/v1/operations/operation_*", route => {
    const id = new URL(route.request().url()).pathname.split("/").pop();
    const record = records.find(item => item.operation_id === id);
    fullReads.push(id);
    return route.fulfill({json:{...full(record), ...(drift ? {operation_sha256:"d".repeat(64)} : {})}});
  });
  await h.page.route("**/api/v1/operations", route => {
    writes.push(route.request().method());
    return route.fulfill({status:503, json:{error:{message:"No full list permitted"}}});
  });
  h.state.operationManifest = {operation_contract_version:6, supported_actions:["CONTINUE_DELIVERY"],
    operation_summary_contract_version:"v0.1"};
  h.team.requests[0].stage = "BLOCKED";
  h.team.requests[0].blocker = "原开发结果待核对";
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  await h.tick();
  await h.page.waitForFunction(() => operationDetailReadyScope !== null);
  return {...h, records, reads, fullReads, writes, full, drift:() => {drift=true;}};
}

test("summary polling preserves the current approval and never fetches the full history list", async t => {
  const h = await summaryUI(t);
  const count = h.fullReads.length;
  const approval = h.page.getByRole("button", {name:"批准并继续",exact:true});
  await approval.waitFor();
  assert.equal(await approval.isEnabled(), true);
  await h.tick();
  assert.equal(h.fullReads.length, count);
  assert.deepEqual(h.writes, []);
  assert.ok(h.reads.length >= 4);
});

test("every history page is reachable and a record outside the first page opens and releases full detail", async t => {
  const h = await summaryUI(t);
  const history = h.page.locator('#detail details[data-key="operation-history:project_fixture/request_fixture"]');
  await history.locator(":scope > summary").click();
  assert.equal(await history.locator(".execution-history-entry").count(), 25);
  await history.getByRole("button", {name:"下一页（更早记录）",exact:true}).click();
  await history.getByText(/第 2 页/).waitFor();
  const entry = history.locator(".execution-history-entry").first();
  await entry.locator("details > summary").first().click();
  await entry.getByText("历史完整原因 25", {exact:false}).waitFor();
  assert.equal(h.fullReads.includes(h.records[25].operation_id), true);
  await entry.locator("details > summary").first().click();
  await h.page.waitForFunction(id => !operationDetailCache.has(id), h.records[25].operation_id);
  assert.equal(await h.page.evaluate(id => operationDetailCache.has(id), h.records[25].operation_id), false);
  assert.equal(await h.page.evaluate(id => operations.some(item => item.operation_id === id), h.records[25].operation_id), false);
  await history.getByRole("button", {name:"下一页（更早记录）",exact:true}).click();
  await history.getByText(/第 3 页/).waitFor();
  assert.equal(await history.locator(".execution-history-entry").count(), 11);
  await history.getByRole("button", {name:"上一页",exact:true}).click();
  await history.getByText(/第 2 页/).waitFor();
  await history.getByRole("button", {name:"返回最新记录",exact:true}).click();
  await history.getByText(/第 1 页/).waitFor();
});

test("changed full approval at click time prevents any POST and clears the current authority", async t => {
  const h = await summaryUI(t);
  h.drift();
  await h.page.getByRole("button", {name:"批准并继续",exact:true}).click();
  await h.page.getByText(/操作记录已有变化/).first().waitFor();
  assert.deepEqual(h.writes, []);
  assert.equal(await h.page.evaluate(() => operationsAvailable), false);
  assert.equal(await h.page.evaluate(() => operationDetailReadyScope), null);
});

test("closing a pending historical detail releases its late completed full response", async t => {
  const h = await summaryUI(t);
  const history = h.page.locator('#detail details[data-key="operation-history:project_fixture/request_fixture"]');
  await history.locator(":scope > summary").click();
  await history.getByRole("button", {name:"下一页（更早记录）",exact:true}).click();
  await history.getByText(/第 2 页/).waitFor();
  const record = h.records[25];
  let start, release;
  const started = new Promise(resolve => {start = resolve;});
  const pending = new Promise(resolve => {release = resolve;});
  t.after(() => release());
  await h.page.route("**/api/v1/operations/" + record.operation_id, async route => {
    start();
    await pending;
    await route.fulfill({json:h.full(record)});
  });
  await h.page.evaluate(id => {
    window.pendingHistoryReadCompleted = false;
    const original = cacheFullOperation;
    cacheFullOperation = value => {
      const result = original(value);
      if (value.operation_id === id) window.pendingHistoryReadCompleted = true;
      return result;
    };
  }, record.operation_id);
  const entry = history.locator(".execution-history-entry").first();
  const detail = entry.locator("details").first();
  await detail.locator(":scope > summary").click();
  await started;
  await detail.locator(":scope > summary").click();
  await h.page.waitForFunction(id => {
    const row = document.querySelector(`[data-view-block="summary-history:${id}"]`);
    return !row || !row.querySelector("details").open;
  }, record.operation_id);
  release();
  await h.page.waitForFunction(() => window.pendingHistoryReadCompleted);
  await h.page.waitForFunction(id => !operationDetailCache.has(id), record.operation_id);
  assert.equal(await detail.locator(":scope > div").textContent(), "");
  assert.equal(await h.page.evaluate(id => operations.some(item => item.operation_id === id), record.operation_id), false);
});
