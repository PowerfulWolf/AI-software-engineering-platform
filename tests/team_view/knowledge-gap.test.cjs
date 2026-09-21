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
    snapshot = {team_id: "team_test", requests: [{id: "r1", project_id: "project_test", title: "Requirement", stage: "WAITING_HUMAN", checkpoint_sha256: "checkpoint-a", scopes: [], documents: [], dialogue: []}], tasks: [], agents: [], projects: []};
    selected = {kind: "request", id: "r1"}; page = "requests";
    consoleAvailable = true; consoleDeliveryReady = true; operationsAvailable = true; consoleTeamId = "team_test";
    renderDetail();
  `, context);
  return { context, get, detail: () => get("detail"), render: () => vm.runInContext("renderDetail()", context) };
}
const gap = {gap_id: "gap-a", question: "请确认范围 <script>not executable</script>", required_decision: "Provide verified facts and approve the exact resolution."};
const pending = {gap, is_current: true};
const resolution = {gap_id: gap.gap_id, resolution_id: "resolution-a", answer: "A", sources: [{uri: "产品确认", content: "A"}]};
const approved = {...pending, resolution};
const findButton = (h, label) => all(h.detail()).find(n => n.tag === "button" && n.textContent === label);

test("knowledge gaps reuse one region and retain drafts across clicks and refresh", async () => {
  let reads = 0;
  const h = harness(async () => { reads++; return {ok: true, json: async () => [pending]}; });
  await findButton(h, "查看待确认的知识").events.click();
  const form = all(h.detail()).find(n => n.tag === "form");
  const answer = all(form).find(n => n.tag === "textarea");
  answer.value = "保留功能，只修改标签";
  await findButton(h, "收起知识详情").events.click();
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
  resolve({ok: true, json: async () => [pending]});
  await retry;
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 1);
  assert.doesNotMatch(text(h.detail()), /temporary failure/);
});

test("knowledge resolution submits once and preserves form/error state on retry", async () => {
  let writes = 0;
  const h = harness(async (url, options = {}) => {
    if (!options.method) return {ok: true, json: async () => writes > 1 ? [approved] : [pending, pending]};
    writes++;
    const payload = JSON.parse(options.body);
    assert.equal(payload.gap_id, gap.gap_id);
    assert.equal(payload.answer, "用户已确认");
    assert.equal(payload.sources[0].content, payload.answer);
    assert.match(payload.sources[0].sha256, /^[a-f0-9]{64}$/);
    return {ok: writes > 1, json: async () => writes > 1 ? resolution : ({error: {message: "请重试"}})};
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
  assert.match(text(h.detail()), /解答已批准/);
  assert.doesNotMatch(text(h.detail()), /请重试/);
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 0);
  assert.ok(findButton(h, "继续交付"));
  await findButton(h, "查看已确认的知识").events.click();
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 0);
  assert.match(text(h.detail()), /产品确认/);
});

test("checkpoint changes isolate forms and old asynchronous loads", async () => {
  let firstResolve, reads = 0;
  const h = harness(async () => {
    if (++reads === 1) return new Promise(done => { firstResolve = done; });
    return {ok: true, json: async () => [{...pending, gap: {...gap, gap_id: "gap-new", question: "新问题"}}]};
  });
  const oldLoad = findButton(h, "查看待确认的知识").events.click();
  vm.runInContext('snapshot.requests[0].checkpoint_sha256 = "checkpoint-b"; renderDetail()', h.context);
  await findButton(h, "查看待确认的知识").events.click();
  firstResolve({ok: true, json: async () => [pending]});
  await oldLoad;
  assert.match(text(h.detail()), /新问题/);
  assert.doesNotMatch(text(h.detail()), /not executable/);
});

test("reloaded approved gap shows saved answer and exact-checkpoint continuation, not old blockers", async () => {
  const submitted = [];
  const h = harness(async (url, options = {}) => {
    if (options.method) {
      submitted.push(JSON.parse(options.body).intent);
      return {ok: true, json: async () => ({operation_id: "op-new", status: "QUEUED", updated_at: "2026-09-22", intent: submitted.at(-1)})};
    }
    return {ok: true, json: async () => [approved]};
  });
  h.context.approvedView = approved;
  vm.runInContext(`
    snapshot.requests[0].knowledge_gap = approvedView;
    snapshot.requests[0].blocker = "Resolve and approve knowledge gap gap-a before resuming.";
    operations = [{operation_id: "op-old", status: "SUCCEEDED", intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1", project_id: "project_test"}, result: {delivery_id: "r1", stage: "WAITING_HUMAN", checkpoint_sha256: "checkpoint-a", next_action: snapshot.requests[0].blocker}, updated_at: "2026-09-21"}];
    renderDetail(); renderOperationStatus();
  `, h.context);
  await findButton(h, "查看已确认的知识").events.click();
  assert.equal(all(h.detail()).filter(n => n.tag === "form" || n.tag === "textarea").length, 0);
  assert.match(text(h.detail()), /已回答的内容.*A.*产品确认/);
  assert.match(text(h.detail()), /已确认的知识 · 待继续/);
  assert.doesNotMatch(text(h.detail()), /Resolve and approve|需要你的确认/);
  assert.doesNotMatch(text(h.get("operations")), /等待人工|操作需要处理/);
  assert.equal(all(h.detail()).filter(n => n.tag === "button" && n.textContent === "继续交付").length, 1);
  await findButton(h, "继续交付").events.click();
  assert.equal(submitted.length, 1);
  assert.deepEqual(submitted[0], {action: "CONTINUE_DELIVERY", project_id: "project_test", delivery_id: "r1", expected_checkpoint_sha256: "checkpoint-a"});
  assert.equal(findButton(h, "继续交付"), undefined);
});

test("current knowledge wait outranks a preserved child checkpoint, but not an explicit running operation", () => {
  const h = harness(async () => ({ok: true, json: async () => [approved]}));
  h.context.approvedView = approved;
  vm.runInContext(`
    snapshot.requests[0].knowledge_gap = approvedView;
    snapshot.tasks = [{id: "child", request_id: "r1", status: "IMPLEMENTING", terminal: false, last_activity: "2026-09-21", next_action: "RUN_DELIVERY"}];
  `, h.context);
  assert.equal(vm.runInContext("requestPresentation(snapshot.requests[0]).status", h.context), "KNOWLEDGE_APPROVED");
  vm.runInContext('snapshot.requests[0].knowledge_gap = {...approvedView, resolution: null}', h.context);
  assert.equal(vm.runInContext("requestPresentation(snapshot.requests[0]).status", h.context), "WAITING_HUMAN");
  vm.runInContext(`operations = [{operation_id: "op-new", status: "RUNNING", updated_at: "2026-09-21", intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1"}}]`, h.context);
  assert.equal(vm.runInContext("requestPresentation(snapshot.requests[0]).status", h.context), "DELIVERING");
});

test("polling the same checkpoint replaces pending drafts when approval arrived elsewhere", async () => {
  let view = pending;
  const h = harness(async () => ({ok: true, json: async () => [view]}));
  await findButton(h, "查看待确认的知识").events.click();
  all(h.detail()).find(n => n.tag === "textarea").value = "unsaved draft";
  view = approved;
  h.context.approvedView = approved;
  vm.runInContext("snapshot.requests[0].knowledge_gap = approvedView; renderDetail()", h.context);
  await findButton(h, "查看已确认的知识").events.click();
  assert.equal(all(h.detail()).filter(n => n.tag === "textarea").length, 0);
  assert.match(text(h.detail()), /产品确认/);
});

test("operation guidance remains readable if the Team snapshot is unavailable", () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  assert.doesNotThrow(() => vm.runInContext(`
    snapshot = null;
    operations = [{operation_id: "op-old", status: "SUCCEEDED", intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1", project_id: "project_test"}, result: {delivery_id: "r1", stage: "WAITING_HUMAN", checkpoint_sha256: "checkpoint-a"}, updated_at: "2026-09-21"}];
    renderOperationStatus();
  `, h.context));
  assert.match(text(h.get("operations")), /等待人工/);
  assert.doesNotMatch(text(h.get("operations")), /解答已批准/);
});

test("opening a stale pending entry echoes the saved answer and immediately confirms its state", async () => {
  const answer = "第一行已确认\n第二行 <script>plain text</script>";
  const confirmed = {...approved, resolution: {...resolution, answer}};
  let reads = 0;
  const h = harness(async () => { reads++; return {ok: true, json: async () => [confirmed]}; });
  await findButton(h, "查看待确认的知识").events.click();
  assert.equal(all(h.detail()).find(n => n.className === "knowledge-gap-answer").textContent, answer);
  const css = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/style.css"), "utf8");
  assert.match(css, /\.knowledge-gap-answer\s*\{[^}]*white-space:\s*pre-wrap/);
  assert.equal(all(h.detail()).find(n => n.className === "knowledge-gap-content").hidden, false);
  assert.equal(all(h.detail()).filter(n => n.tag === "form" || n.tag === "textarea").length, 0);
  assert.ok(all(h.detail()).some(n => n.tag === "h2" && n.textContent === "已确认的知识"));
  assert.match(text(h.detail()), /已确认的知识 · 待继续/);
  assert.doesNotMatch(text(h.detail()), /补充待确认的信息|查看待确认的知识|需要你的确认/);
  await findButton(h, "收起知识详情").events.click();
  h.render();
  await findButton(h, "查看已确认的知识").events.click();
  assert.equal(reads, 1);
  assert.equal(all(h.detail()).find(n => n.className === "knowledge-gap-answer").textContent, answer);
});

test("a late confirmed answer cannot confirm a newer checkpoint's question", async () => {
  let firstResolve, reads = 0;
  const current = {...pending, gap: {...gap, gap_id: "gap-new", question: "新的待确认问题"}};
  const h = harness(async () => {
    if (++reads === 1) return new Promise(done => { firstResolve = done; });
    return {ok: true, json: async () => [current]};
  });
  const oldLoad = findButton(h, "查看待确认的知识").events.click();
  h.context.currentView = current;
  vm.runInContext('snapshot.requests[0] = {...snapshot.requests[0], checkpoint_sha256: "checkpoint-b", knowledge_gap: currentView}; renderDetail()', h.context);
  await findButton(h, "查看待确认的知识").events.click();
  firstResolve({ok: true, json: async () => [approved]});
  await oldLoad;
  assert.match(text(h.detail()), /新的待确认问题/);
  assert.doesNotMatch(text(h.detail()), /已确认的知识|产品确认/);
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 1);
});

test("historical approved gap and current pending gap have only one actionable form", async () => {
  const current = {...pending, gap: {...gap, gap_id: "gap-b", question: "下一项问题"}};
  const h = harness(async () => ({ok: true, json: async () => [{...approved, is_current: false}, current]}));
  h.context.currentView = current;
  vm.runInContext("snapshot.requests[0].knowledge_gap = currentView; renderDetail()", h.context);
  await findButton(h, "查看待确认的知识").events.click();
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 1);
  assert.match(text(h.detail()), /下一项问题/);
  const history = all(h.detail()).find(n => n.className === "knowledge-gap-card");
  assert.equal(all(history).filter(n => n.tag === "button").length, 0);
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
