const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

class Element {
  constructor(tag) {
    Object.assign(this, { tag, children: [], events: {}, attributes: {}, dataset: {}, textContent: "", className: "", value: "", hidden: false });
    this.classList = { toggle() {} };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, fn) { this.events[name] = fn; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  focus() {}
  scrollIntoView() {}
  set innerHTML(value) { throw new Error("Unsafe HTML: " + value); }
}
const all = (node) => [node, ...node.children.filter(n => typeof n !== "string").flatMap(all)];
const text = (node) => node.textContent + node.children.map(n => typeof n === "string" ? n : text(n)).join(" ");
function harness(fetcher) {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, new Element("div"));
    return nodes.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: get, createElement: tag => new Element(tag), createTextNode: s => s, querySelectorAll: () => [] },
    fetch: fetcher, crypto: webcrypto, TextEncoder, setTimeout: () => 0, clearTimeout() {},
    AbortController, structuredClone,
  });
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.replace(/\nrefresh\(\);\nsetInterval\(refresh, 5000\);\s*$/, "\n"), context);
  vm.runInContext(`
    snapshot = {requests: [{id: "r1", project_id: "project_test", title: "Requirement", stage: "WAITING_HUMAN", checkpoint_sha256: "checkpoint-a", scopes: [], documents: [], dialogue: []}], tasks: [], agents: [], projects: []};
    selected = {kind: "request", id: "r1"}; page = "requests";
    consoleAvailable = true; consoleDeliveryReady = true; operationsAvailable = true;
    renderDetail();
  `, context);
  return { context, detail: () => get("detail"), render: () => vm.runInContext("renderDetail()", context) };
}
const gap = {gap_id: "gap-a", question: "请确认范围 <script>not executable</script>", required_decision: "Provide verified facts and approve the exact resolution."};
const findButton = (h, label) => all(h.detail()).find(n => n.tag === "button" && n.textContent === label);

test("knowledge gaps reuse one region and retain drafts across clicks and refresh", async () => {
  let reads = 0;
  const h = harness(async () => { reads++; return {ok: true, json: async () => [gap]}; });
  await findButton(h, "查看待确认的知识").events.click();
  const form = all(h.detail()).find(n => n.tag === "form");
  const answer = all(form).find(n => n.tag === "textarea");
  answer.value = "保留功能，只修改标签";
  await all(h.detail()).find(n => n.tag === "button" && /待确认的知识/.test(n.textContent)).events.click();
  h.render();
  await all(h.detail()).find(n => n.tag === "button" && /待确认的知识/.test(n.textContent)).events.click();
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 1);
  assert.equal(reads, 1);
  assert.equal(all(h.detail()).find(n => n.tag === "textarea").value, answer.value);
  assert.ok(all(h.detail()).some(n => n.tag === "p" && n.textContent === gap.question));
  assert.doesNotMatch(text(h.detail()), /Provide verified facts/);
});

test("knowledge gap load is single-flight; failure retries replace feedback", async () => {
  let resolve, reads = 0;
  const h = harness(() => { reads++; return new Promise(done => { resolve = done; }); });
  const button = findButton(h, "查看待确认的知识");
  const first = button.events.click();
  const second = button.events.click();
  assert.equal(reads, 1);
  resolve({ok: false, json: async () => ({error: {message: "temporary failure"}})});
  await Promise.all([first, second]);
  const retry = button.events.click();
  resolve({ok: true, json: async () => [gap]});
  await retry;
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 1);
  assert.doesNotMatch(text(h.detail()), /temporary failure/);
});

test("knowledge resolution submits once and preserves form/error state on retry", async () => {
  let writes = 0;
  const h = harness(async (url, options = {}) => {
    if (!options.method) return {ok: true, json: async () => [gap, gap]};
    writes++;
    const payload = JSON.parse(options.body);
    assert.equal(payload.gap_id, gap.gap_id);
    assert.equal(payload.answer, "用户已确认");
    assert.equal(payload.sources[0].content, payload.answer);
    assert.match(payload.sources[0].sha256, /^[a-f0-9]{64}$/);
    return {ok: writes > 1, json: async () => ({error: {message: "请重试"}})};
  });
  await findButton(h, "查看待确认的知识").events.click();
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 1);
  const form = all(h.detail()).find(n => n.tag === "form");
  all(form).find(n => n.tag === "textarea").value = "用户已确认";
  all(form).find(n => n.tag === "input").value = "产品负责人确认";
  const event = {preventDefault() {}};
  await Promise.all([form.events.submit(event), form.events.submit(event)]);
  assert.equal(writes, 1);
  assert.equal(all(form).find(n => n.tag === "textarea").value, "用户已确认");
  await form.events.submit(event);
  assert.equal(writes, 2);
  assert.match(text(form), /解答已批准/);
  assert.doesNotMatch(text(form), /请重试/);
  assert.ok(all(form).some(n => n.tag === "button" && n.textContent === "继续需求"));
});

test("checkpoint changes isolate forms and old asynchronous loads", async () => {
  let firstResolve, reads = 0;
  const h = harness(async () => {
    if (++reads === 1) return new Promise(done => { firstResolve = done; });
    return {ok: true, json: async () => [{...gap, gap_id: "gap-new", question: "新问题"}]};
  });
  const oldLoad = findButton(h, "查看待确认的知识").events.click();
  vm.runInContext('snapshot.requests[0].checkpoint_sha256 = "checkpoint-b"; renderDetail()', h.context);
  await findButton(h, "查看待确认的知识").events.click();
  firstResolve({ok: true, json: async () => [gap]});
  await oldLoad;
  assert.match(text(h.detail()), /新问题/);
  assert.doesNotMatch(text(h.detail()), /not executable/);
});

test("model call details load once and show primary, fallback, duration and IDs", async () => {
  let reads = 0;
  const h = harness(async () => ({ok: true, json: async () => {reads++; return [
    {route_index:1, provider:"hdl", model:"primary", reasoning_effort:"xhigh", phase:"knowledge_intent", role:"product", outcome:"FAILED", duration_ms:60100, http_status:504, request_id:"req-primary"},
    {route_index:2, provider:"hdl", model:"backup", reasoning_effort:"medium", phase:"knowledge_intent", role:"product", outcome:"SUCCEEDED", duration_ms:1234, http_status:200, request_id:"req-backup"},
  ];}}));
  const details = vm.runInContext('modelCallDiagnostics({operation_id:"op-test", status:"SUCCEEDED"})', h.context);
  details.open = true;
  await Promise.all([details.events.toggle(), details.events.toggle()]);
  await details.events.toggle();
  assert.equal(reads, 1);
  assert.match(text(details), /主模型.*primary/);
  assert.match(text(details), /备用 1.*backup/);
  assert.match(text(details), /60.10 秒.*HTTP 504/);
  assert.match(text(details), /req-primary/);
  assert.match(text(details), /req-backup/);
});
