const assert = require("node:assert/strict");
const {test} = require("node:test");
const {ui} = require("./fixture.cjs");

test("inspection is visible, reads retained demand and never submits delivery", async t => {
  const h = await ui(t, {ready: false, operationManifest: {
    mode: "inspection", maintenance_summary: "平台维护", operation_contract_version: 8, supported_actions: [],
  }});
  const posts = [];
  h.page.on("request", request => { if (request.method() !== "GET") posts.push(request.url()); });
  assert.equal(await h.page.locator("#service-maintenance").isVisible(), true);
  assert.match(await h.page.locator("#service-maintenance").innerText(), /维护仅查看.*交付与修改操作已暂停/);
  assert.match(await h.page.locator("#connection").innerText(), /维护仅查看服务已连接/);
  assert.doesNotMatch(await h.page.locator("#connection").innerText(), /设置控制台/);
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  assert.match(await h.page.locator("#detail").innerText(), /Fixture request/);
  assert.equal(await h.page.evaluate(() => canControlCurrentTeam()), false);
  assert.match(await h.page.evaluate(() => deliveryControlUnavailableReason().reason), /仅查看/);
  assert.equal(await h.page.evaluate(() => systemOperationNotices().some(x => x.key === "system:delivery-not-ready")), false);
  await h.page.route("http://ui.test/api/v1/admin/**", route => route.fulfill({status: 503,
    json: {error: {code: "SERVICE_MAINTENANCE", message: "维护仅查看"}}}));
  await h.page.locator("#nav-settings").click();
  await h.page.waitForFunction(() => document.getElementById("content").textContent.includes("维护仅查看模式暂不开放"));
  assert.match(await h.page.locator("#content").innerText(), /维护仅查看模式暂不开放设置和知识管理/);
  assert.doesNotMatch(await h.page.locator("#content").innerText(), /请使用 ase-console|请先完成设置/);
  await h.tick();
  assert.match(await h.page.locator("#connection").innerText(), /维护仅查看服务已连接/);
  assert.equal(await h.page.locator("#connection").getAttribute("class"), "");
  await h.requests();
  assert.match(await h.page.locator("#content").innerText(), /Fixture request/);
  assert.deepEqual(posts, []);
});
