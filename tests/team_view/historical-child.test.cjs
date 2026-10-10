const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function state() {
  const element = () => ({children: [], textContent: "", dataset: {},
    append(...nodes) { this.children.push(...nodes); }, addEventListener() {},
    setAttribute() {}, classList: {toggle() {}}});
  const context = vm.createContext({
    document: {getElementById: element, createElement: element, querySelectorAll: () => []},
    fetch: () => new Promise(() => {}), AbortController,
    setInterval() {}, setTimeout() {}, clearTimeout() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,
    "../../src/ai_software_engineer/team_view/app.js"), "utf8"), context);
  vm.runInContext(`
    snapshot = {selected_project_id: "p", requests: [], tasks: []};
    const request = {id: "delivery_multi_original", project_id: "p", title: "K1",
      stage: "PLANNING", checkpoint_sha256: "current", scopes: [{root: "/repo"}],
      next_action: "继续计划", failed_stages: []};
    const old = {id: "delivery_old", request_id: request.id, title: "K1", project_id: "p",
      status: "BLOCKED", terminal: true, last_activity: "2026-10-01T00:00:00Z",
      blocker: "历史设计被拒绝", next_action: "历史恢复建议", role_queue: []};
    snapshot.requests = [request]; snapshot.tasks = [old];
  `, context);
  return expression => vm.runInContext(expression, context);
}

test("cleared current child scopes retain audit history without a current blocker or task", () => {
  const run = state();
  assert.equal(run("requestTasks(request).length"), 1);
  assert.equal(run("currentRequestTasks(request).length"), 0);
  for (const stage of ["PLANNING", "DELIVERING"]) {
    run(`request.stage = ${JSON.stringify(stage)}`);
    assert.equal(run("terminalBlockedRequestTask(request)"), null);
    assert.doesNotMatch(run("requestPresentation(request).blocker || ''"), /历史/);
    if (stage === "PLANNING")
      assert.equal(run("deliveryFlow(request).children.some(step => step.className === 'blocked')"), false);
  }
  run(`old.terminal = false; old.status = "IMPLEMENTING";
    old.blocker = null; old.role_queue = [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_EXPIRED"}];`);
  assert.equal(run("interruptedRequestTask(request)"), null);
  run('old.role_queue[0].lease_liveness = "LEASE_VALID"');
  assert.equal(run("activeRequestTask(request)"), null);
  run('old.role_queue[0].status = "WAITING_HUMAN"');
  assert.equal(run("waitingRequestTask(request)"), null);
  assert.equal(run("requestTasks(request).length"), 1);
});

test("current source identity selects its newest verifier and excludes an old active child", () => {
  const run = state();
  run(`request.stage = "DELIVERING"; request.scopes[0].delivery_id = "delivery_new";
    old.terminal = false; old.status = "IMPLEMENTING"; old.blocker = null;
    old.last_activity = "2026-10-01T00:04:00Z";
    const current = {...old, id: "delivery_new", terminal: true, status: "DONE",
      last_activity: "2026-10-01T00:01:00Z"};
    const verifier = {...old, id: "verification_new", source_delivery_id: "delivery_new",
      status: "QA", work_kind: "candidate_verification", last_activity: "2026-10-01T00:02:00Z",
      role_queue: [{role: "qa", status: "RUNNING", lease_liveness: "LEASE_VALID"}]};
    snapshot.tasks.push(current, verifier);`);
  assert.equal(run("currentRequestTasks(request).length"), 1);
  assert.equal(run("currentRequestTasks(request)[0].id"), "verification_new");
  assert.equal(run("activeRequestTask(request).id"), "verification_new");
  assert.equal(run("requestTasks(request).length"), 3);
  run(`const standalone = {...request, id: "delivery_standalone", scopes: [{delivery_id: "delivery_standalone"}]};
    snapshot.requests.push(standalone);
    snapshot.tasks.push({...verifier, id: "delivery_standalone", source_delivery_id: null, request_id: standalone.id});`);
  assert.equal(run("currentRequestTasks(standalone).length"), 1);
  assert.equal(run("currentRequestTasks(request)[0].id"), "verification_new");
});

// Execute buildDetail and its real incremental reconciler, including disclosure visibility.
// No navigation initialization, network, runtime or durable stores are used.
class DetailElement {
  constructor(tag) {
    Object.assign(this, {tagName: tag.toUpperCase(), children: [], events: {}, attributes: {},
      dataset: {}, textContent: "", className: "", hidden: false});
    this.classList = {toggle() {}, add: (...tokens) => {
      this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...tokens])].join(" ");
    }};
  }
  append(...nodes) {
    for (const node of nodes) {
      node.remove();
      node.parentNode = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    for (const node of [...this.children]) node.remove();
    this.append(...nodes);
  }
  get childNodes() { return this.children; }
  get lastChild() { return this.children.at(-1); }
  get parentElement() { return this.parentNode || null; }
  get isConnected() { return this.root === true || Boolean(this.parentNode?.isConnected); }
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
    this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1);
    this.parentNode = null;
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  addEventListener(key, callback) { this.events[key] = callback; }
  querySelectorAll(selector) { return descend(this).slice(1).filter(node => matches(node, selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  scrollIntoView() {}
  set innerHTML(value) { throw new Error("Unsafe HTML: " + value); }
}
const descend = node => [node, ...node.children.flatMap(descend)];
const text = node => node.textContent + " " + node.children.map(text).join(" ");
const visible = node => [node, ...node.children.filter(child => !child.hidden &&
  (node.tagName !== "DETAILS" || node.open === true || child.tagName === "SUMMARY")).flatMap(visible)];
const visibleText = node => visible(node).map(child => child.textContent).join(" | ");
const matches = (node, selector) => {
  if (selector.startsWith(".")) return node.className.split(/\s+/).includes(selector.slice(1));
  if (selector === "details[open]") return node.tagName === "DETAILS" && node.open === true;
  if (selector === '[aria-modal="true"]') return node.attributes["aria-modal"] === "true";
  return node.tagName === selector.toUpperCase();
};
const control = (node, title) => descend(node).find(child => child.tagName === "BUTTON" && child.textContent === title);

function detailState() {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) {
      const node = new DetailElement("div");
      node.root = true;
      node.id = id;
      nodes.set(id, node);
    }
    return nodes.get(id);
  };
  const context = vm.createContext({
    document: {getElementById: get, createElement: tag => new DetailElement(tag),
      querySelectorAll: selector => [...nodes.values()].flatMap(descend).filter(node => matches(node, selector))},
    fetch: () => { throw new Error("Historical detail must not send HTTP requests"); },
  });
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  const run = code => vm.runInContext(code, context);
  run(`
    const request = {id: "delivery_multi_original", project_id: "p", title: "K1", stage: "DELIVERING",
      checkpoint_sha256: "current", scopes: [{root: "/repo", selected_paths: ["."], delivery_id: "delivery_new"}],
      documents: [], dialogue: [], next_action: "等待本轮执行", failed_stages: []};
    const old = {id: "delivery_old", task_id: "task_old", request_id: request.id, project_id: "p", title: "K1",
      status: "BLOCKED", terminal: true, scope: request.scopes[0], last_activity: "2026-10-01T00:00:00Z",
      blocker: "旧执行产出未通过校验。", next_action: "核实旧执行后恢复。",
      execution: {state: "STOPPED", responsibility: "engineering", reason_code: "OLD_INTERRUPTION",
        reason: "旧执行产出未通过校验。", next_action: "核实旧执行后恢复。", action_required: false},
      assignments: [], role_queue: [], runs: [], documents: [{name: "旧报告", content: "完整保留的报告正文。",
        source_uri: "artifact://old", sha256: "a".repeat(64)}],
      timeline: Array.from({length: 13}, (_, index) => ({id: "entry_" + index, task_id: "task_old",
        kind: "state_event", summary: "旧轮次 " + index, occurred_at: "2026-10-01T00:00:00Z",
        source_uri: "event://old/" + index, details: {}}))};
    const current = {...old, id: "delivery_new", task_id: "task_new", terminal: false, status: "IMPLEMENTING",
      last_activity: "2026-10-10T00:00:00Z", blocker: null, next_action: "等待当前执行",
      execution: {state: "RUNNING", responsibility: "team", reason: "当前角色正在执行。",
        next_action: "等待当前执行", action_required: false},
      role_queue: [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID",
        attempt: 8, heartbeat_at: "2026-10-10T00:00:00Z"}], documents: [], timeline: []};
    snapshot = {team_id: "team", selected_project_id: "p", projects: [], agents: [],
      requests: [request], tasks: [old, current]};
    selected = {kind: "task", id: old.id};
    globalThis.navigations = [];
    showDetail = (kind, id) => { navigations.push({kind, id}); };
    renderDetail();
  `);
  return {run, get, panel: get("detail"), context};
}

test("historical Task detail keeps historical identity, advice and exact current Requirement visible", async () => {
  const h = detailState();
  const before = h.run("JSON.stringify(snapshot)");
  const visible = visibleText(h.panel);
  assert.match(visible, /历史执行记录/);
  assert.match(visible, /不代表当前需求/);
  assert.match(visible, /当前需求.*实现.*执行中/);
  assert.match(visible, /当次执行结果/);
  assert.match(visible, /当次执行 · 已阻塞/);
  assert.match(visible, /当次原因 · 旧执行产出未通过校验/);
  assert.match(visible, /当次处理建议 · 核实旧执行后恢复/);
  assert.doesNotMatch(visible, /当前执行 · 已阻塞|下一步 · 核实旧执行|当前进展|当前轮/);
  assert.equal(h.panel.querySelector('[aria-modal="true"]').attributes["aria-labelledby"], "task-detail-dialog-heading");
  assert.equal(h.panel.querySelector(".detail-panel-heading").textContent, "历史任务详情");
  const back = control(h.panel, "查看当前需求");
  assert.ok(back, "current Requirement navigation is visible without unfolding reference");
  assert.ok(visibleText(h.panel).includes(back.textContent));
  assert.equal(descend(h.panel).filter(node => node.attributes["data-delivery-control"] === "true").length, 0);
  await back.events.click();
  assert.equal(h.run("JSON.stringify(navigations)"), JSON.stringify([{kind: "request", id: "delivery_multi_original"}]));
  assert.equal(h.panel.querySelector(".execution-history").children.length, 13);
  assert.match(text(h.panel), /artifact:\/\/old/);
  assert.match(text(h.panel), new RegExp("a".repeat(64)));
  assert.equal(h.run("JSON.stringify(snapshot)"), before, "render and navigation do not change historical facts");
});

test("legacy and nonterminal historical Tasks never promote an old running claim or recovery advice", () => {
  const h = detailState();
  h.run(`old.execution = null; old.terminal = false; old.status = "IMPLEMENTING";
    old.role_queue = current.role_queue; renderDetail({incremental: true});`);
  const shown = visibleText(h.panel);
  assert.match(shown, /历史执行记录/);
  assert.match(shown, /当次交付阶段 · 实现/);
  assert.match(shown, /当次原因 · 旧执行产出未通过校验/);
  assert.match(shown, /当次处理建议 · 核实旧执行后恢复/);
  assert.doesNotMatch(shown, /实现正在执行|需要你确认业务决定|下一步 · 核实旧执行/);
  assert.equal(h.panel.querySelector(".task-activity-block").children.length, 0);
  assert.equal(h.run("old.status"), "IMPLEMENTING");
  assert.match(text(h.panel), /角色执行队列/);
});

test("Task detail reconciles parent and current sibling changes while retaining complete history and source reports", () => {
  const h = detailState();
  const history = h.panel.querySelector(".execution-history");
  const artifact = h.panel.querySelector(".artifact-document");
  artifact.open = true;
  const dialog = h.panel.querySelector('[aria-modal="true"]');
  h.run('current.role_queue = []; renderDetail({incremental: true});');
  assert.match(visibleText(h.panel), /当前需求.*等待工程处理/);
  assert.equal(h.panel.querySelector(".execution-history"), history);
  assert.equal(h.panel.querySelector(".artifact-document"), artifact);
  assert.equal(artifact.open, true);
  h.run('request.stage = "DONE"; renderDetail({incremental: true});');
  assert.match(visibleText(h.panel), /当前需求.*已完成/);
  assert.equal(h.panel.querySelector('[aria-modal="true"]'), dialog);
  assert.equal(h.panel.querySelector(".execution-history"), history);
  assert.equal(history.children.length, 13);
  assert.equal(h.panel.querySelector(".artifact-document"), artifact);
  h.run('request.scopes[0].delivery_id = old.id; request.stage = "DELIVERING"; renderDetail({incremental: true});');
  assert.doesNotMatch(visibleText(h.panel), /历史执行记录|当次执行结果|查看当前需求/);
  assert.match(visibleText(h.panel), /当前进展/);
  assert.equal(h.panel.querySelector(".detail-panel-heading").textContent, "任务详情");
  assert.equal(h.panel.querySelector(".artifact-document"), artifact);
});

test("parent delivery Operation changes update a historical detail without modifying the Task", () => {
  const h = detailState();
  h.run('request.stage = "PLANNING"; request.scopes[0].delivery_id = null; renderDetail({incremental: true});');
  const before = h.run("JSON.stringify(old)");
  h.run(`operationsAvailable = true; operations = [{operation_id: "parent_operation", status: "RUNNING",
    updated_at: "2026-10-10T00:00:00Z", intent: {action: "CONTINUE_DELIVERY", project_id: "p",
      delivery_id: request.id}}]; renderDetail({incremental: true});`);
  assert.match(visibleText(h.panel), /当前需求.*计划编排.*执行中/);
  assert.equal(h.run("JSON.stringify(old)"), before);
});

test("historical Task reading pause also freezes parent changes until an explicit read resume", async () => {
  const h = detailState();
  await control(h.panel, "暂停详情更新").events.click();
  h.run('request.stage = "DONE"; renderDetail({incremental: true});');
  assert.match(visibleText(h.panel), /当前需求.*实现.*执行中/);
  assert.match(visibleText(h.panel), /有新进展/);
  assert.doesNotMatch(visibleText(h.panel.querySelector(".task-historical-context")), /当前需求.*已完成/);
  h.run('pausedTaskDetailKey = null; renderDetail({incremental: true});');
  assert.match(visibleText(h.panel), /当前需求.*已完成/);
  assert.match(visibleText(h.panel), /实时更新/);
});

test("current Task and unmatched parents retain their truthful current detail contract", () => {
  const h = detailState();
  h.run('selected.id = current.id; renderDetail({incremental: true});');
  assert.match(visibleText(h.panel), /当前进展.*当前执行 · 执行中/);
  assert.match(visibleText(h.panel), /实现正在执行/);
  assert.doesNotMatch(visibleText(h.panel), /历史执行记录|当次执行结果|查看当前需求/);
  for (const change of ['old.request_id = "missing"', 'old.request_id = request.id; old.project_id = "other"']) {
    h.run(`${change}; selected.id = old.id; renderDetail({incremental: true});`);
    assert.doesNotMatch(visibleText(h.panel), /历史执行记录|当前需求|查看当前需求/);
  }
});

test("historical parent navigation rechecks exact scope and cannot use a stale callback", async () => {
  for (const change of [
    'snapshot.selected_project_id = "other"',
    'requestedProjectId = "other"',
    'snapshot.team_id = "other"',
    'selected.id = current.id',
    'request.project_id = "other"',
    'old.request_id = "missing"',
    'request.scopes[0].delivery_id = old.id',
  ]) {
    const h = detailState();
    const back = control(h.panel, "查看当前需求");
    assert.ok(back);
    h.run(change);
    await back.events.click();
    assert.equal(h.run("navigations.length"), 0, change);
  }
  const h = detailState();
  const back = control(h.panel, "查看当前需求");
  h.run('teamReadIssue = "busy";');
  await back.events.click();
  assert.equal(h.run("navigations.length"), 1, "saved history remains read-only navigable during a Team outage");
});
