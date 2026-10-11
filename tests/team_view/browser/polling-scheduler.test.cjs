const {test} = require("node:test");
const assert = require("node:assert/strict");
const {setTimeout: sleep} = require("node:timers/promises");
const {ui, operation} = require("./fixture.cjs");

async function observed(page, condition) {
  const deadline = Date.now() + 3000;
  while (Date.now() < deadline) {
    if (await page.evaluate(condition)) return;
    await sleep(10);
  }
  assert.fail("the fixture observation did not settle");
}

test("the browser starts its next Team read five seconds after a slow read completes", async t => {
  const h = await ui(t, {automaticPolling: true});
  let reads = 0, release, started;
  const held = new Promise(resolve => {release = resolve;});
  const entered = new Promise(resolve => {started = resolve;});
  t.after(() => release());
  await h.page.route("**/api/v1/team?**", async route => {
    reads++;
    if (reads === 1) {started(); await held;}
    await route.fulfill({json: h.team});
  });
  await h.page.clock.runFor(4999);
  assert.equal(reads, 0);
  await h.page.clock.runFor(1); await entered;
  await h.page.clock.runFor(8000);
  assert.equal(reads, 1, "no fixed-clock catch-up read while the first one is held");
  assert.equal(await h.page.evaluate(() => refreshing), true);
  release(); await observed(h.page, () => !refreshing);
  await h.page.clock.runFor(4999);
  assert.equal(reads, 1);
  await h.page.clock.runFor(1);
  await observed(h.page, () => !refreshing);
  assert.equal(reads, 2);
  assert.match(await h.page.locator("#connection").innerText(), /读取完成后自动更新/);
});

test("browser automatic busy retries back off and retain the editable draft", async t => {
  const h = await ui(t, {automaticPolling: true});
  await h.requests();
  await h.draft();
  let reads = 0, busy = true;
  await h.page.route("**/api/v1/team?**", route => {
    reads++;
    return busy ? route.fulfill({status: 503, json: {error: {code: "TEAM_READ_IN_PROGRESS"}}})
      : route.fulfill({json: h.team});
  });
  await h.page.clock.runFor(5000);
  await observed(h.page, () => !refreshing && teamReadIssue === "busy");
  for (const delay of [10000, 20000, 30000, 30000]) {
    const before = reads;
    await h.page.clock.runFor(delay - 1);
    assert.equal(reads, before);
    await h.page.clock.runFor(1);
    await observed(h.page, () => !refreshing && teamReadIssue === "busy");
    assert.equal(reads, before + 1);
    assert.equal(await h.page.locator('#composer input[name="name"]').evaluate(node => node === window.draftInput), true);
    assert.equal(await h.page.evaluate(() => canControlCurrentTeam()), false);
  }
  busy = false;
  await h.page.clock.runFor(30000);
  await observed(h.page, () => !refreshing && teamReadIssue === null);
  const before = reads;
  await h.page.clock.runFor(5000);
  await observed(h.page, () => !refreshing);
  assert.equal(reads, before + 1);
  assert.equal(await h.page.locator('#composer input[name="name"]').inputValue(), "保留正在编辑的需求");
});

test("real preparation GETs keep their five-second lane while Team is held", async t => {
  const scope = {operation_id: "operation_" + "1".repeat(32), team_id: "team_fixture", project_id: "project_fixture",
    delivery_id: "request_fixture", expected_checkpoint_sha256: "a".repeat(64), approved_plan_sha256: "e".repeat(64)};
  const h = await ui(t, {automaticPolling: true, operations: [operation("RUNNING", {
    operation_id: scope.operation_id, team_id: scope.team_id,
    intent: {action: "CONTINUE_DELIVERY", project_id: scope.project_id, delivery_id: scope.delivery_id,
      expected_checkpoint_sha256: scope.expected_checkpoint_sha256, approved_plan_sha256: scope.approved_plan_sha256},
  })]});
  let preparationReads = 0, release, started;
  const held = new Promise(resolve => {release = resolve;});
  const entered = new Promise(resolve => {started = resolve;});
  t.after(() => release());
  await h.page.route("**/preparation-progress", route => {
    preparationReads++;
    return route.fulfill({json: {schema_version: "v0.1", scope, records: []}});
  });
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  await h.page.evaluate(() => refreshRecoveryPreparationProgress());
  const before = preparationReads;
  await h.page.route("**/api/v1/team?**", async route => {
    started(); await held;
    await route.fulfill({json: h.team});
  });
  await h.page.clock.runFor(5000); await entered;
  await observed(h.page, () => recoveryPreparationFlight === null);
  assert.equal(preparationReads, before + 1);
  await h.page.clock.runFor(5000);
  await observed(h.page, () => recoveryPreparationFlight === null);
  assert.equal(preparationReads, before + 2);
  assert.equal(await h.page.evaluate(() => refreshing), true);
  release(); await observed(h.page, () => !refreshing);
});
