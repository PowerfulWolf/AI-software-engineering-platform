// Independent QA regression harness: execute the shipped script with fake HTTP and timers.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { operationManifest } = require("./console-capabilities-fixture.cjs");

class Element {
  constructor(tag) {
    Object.assign(this, { tag, children: [], events: {}, attributes: {}, dataset: {},
      textContent: "", className: "", value: "", hidden: false, checked: false });
    this.classList = { toggle() {}, add: (...names) => {
      this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(" ");
    } };
  }
  append(...nodes) { for (const node of nodes) if (typeof node !== "string") node.parentElement = this; this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, callback) { this.events[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(node => node !== this); }
  removeAttribute(name) { delete this.attributes[name]; }
  get firstElementChild() { return this.children.find(node => typeof node !== "string"); }
  querySelectorAll(selector) {
    return descendants(this).slice(1).filter((node) => matchesSelector(node, selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  focus() {}
  scrollIntoView() {}
  set innerHTML(value) { throw new Error("Unsafe HTML: " + value); }
}
const text = (node) => typeof node === "string"
  ? node : node.textContent + node.children.map(text).join(" ");
const descendants = (node) => [node, ...node.children
  .filter((child) => typeof child !== "string").flatMap(descendants)];
const matchesSelector = (node, selector) => selector.split(",").some((part) => {
  const ancestor = part.trim().match(/^#([\w-]+) \*$/);
  if (ancestor) {
    for (let parent = node.parentElement; parent; parent = parent.parentElement)
      if (parent.attributes.id === ancestor[1]) return true;
    return false;
  }
  const className = part.trim().match(/^\.([\w-]+)$/);
  if (className) return node.className.split(/\s+/).includes(className[1]);
  const match = part.trim().match(/^(\w+)?(?:\[([\w-]+)(?:=["']?([^"'\]]+)["']?)?\])?$/);
  if (!match) throw new Error("Unsupported QA selector: " + part);
  const [, tag, attribute, expected] = match;
  if (tag && node.tag !== tag) return false;
  if (!attribute) return true;
  const value = attribute.startsWith("data-")
    ? node.dataset[attribute.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())]
      ?? node.attributes[attribute]
    : node.attributes[attribute] ?? (attribute === "open" && node.open ? "" : undefined);
  return value !== undefined && (expected === undefined || value === expected);
});
const settled = () => new Promise(setImmediate);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise; reject = rejectPromise;
  });
  return { promise, resolve, reject };
};
const successMessage = "配置已应用，Web Console 已使用保存的运行配置重新启动。";

async function browser(options = {}) {
  const nodes = new Map(), timers = new Map(), storage = new Map(), requests = [];
  let timerId = 0, poll;
  const get = (id) => {
    if (!nodes.has(id)) {
      const node = new Element("div");
      node.setAttribute("id", id);
      nodes.set(id, node);
    }
    return nodes.get(id);
  };
  const state = {
    ready: options.ready ?? false,
    restart: options.restart ?? true,
    teamFailure: options.teamFailure ?? false,
    consoleFailure: false,
    consoleStatus: 200,
    consoleInvalid: false,
    consoleInvalidJson: false,
    operationsFailure: false,
    statusFailure: false,
    applyStatus: options.applyStatus ?? null,
    statusRuntime: "READY",
    databaseConnection: "CONNECTED",
  };
  const config = {
    schema_version: "v0.2", platform_root: "/fixture/platform", team_id: "team_fixture",
    team_name: "Fixture team", team_knowledge_paths: [],
    database: { backend: "mysql", dsn_env: "ASE_MYSQL_DSN" },
    model_routes: [], agent_model_routes: [], codex_executable: "codex",
    live_model_execution: false, console_port: 8765,
  };
  const team = {
    schema_version: "v0.2", as_of: "2026-09-19T00:00:00Z", team_id: "team_fixture",
    team_name: "Fixture team", selected_project_id: options.project ? "project_fixture" : null,
    projects: options.projects || (options.project ? [{ id: "project_fixture", name: "Fixture project" }] : []),
    agents: [], requests: options.requests || [], tasks: [],
  };
  const response = (value, ok = true) => ({ ok, json: async () => structuredClone(value) });
  const context = vm.createContext({
    document: { getElementById: get, createElement: (tag) => new Element(tag),
      createTextNode: (value) => value,
      querySelectorAll: (selector) => [...new Set([...nodes.values()].flatMap(descendants))]
        .filter((node) => matchesSelector(node, selector)) },
    fetch: async (url, request = {}) => {
      requests.push({ url, method: request.method || "GET" });
      if (url.startsWith("/api/v1/team")) {
        if (options.teamRead) return options.teamRead(url, request, team, response);
        if (state.teamFailure) throw new Error("Team projection unavailable");
        return response(team);
      }
      if (url === "/api/v1/console") {
        if (state.consoleFailure) throw new Error("Console offline");
        if (state.consoleStatus !== 200)
          return { ok: false, status: state.consoleStatus };
        if (state.consoleInvalid) return response({ schema_version: "invalid" });
        if (state.consoleInvalidJson)
          return { ok: true, json: async () => { throw new SyntaxError("invalid JSON"); } };
        return response({ schema_version: "v0.2", team_id: config.team_id,
          delivery_ready: state.ready, ...operationManifest });
      }
      if (url === "/api/v1/operations") {
        if (request.method === "POST" && options.operationPost)
          return await options.operationPost;
        if (state.operationsFailure) throw new Error("Operations unavailable");
        if (options.operationsRead) return options.operationsRead(request, response);
        return response([]);
      }
      if (url === "/api/v1/admin/settings") return response({ settings_contract_version: 2, config,
        config_path: "/fixture/production.json", config_source: "saved",
        restart_required: state.restart, secret_status: [] });
      if (url === "/api/v1/admin/settings/apply") {
        if (request.method === "POST") state.applyStatus = "PENDING";
        if (state.applyStatus === null)
          return response({ error: { message: "No configuration apply exists" } }, false);
        return response({ request_id: "configuration_apply_" + "a".repeat(32),
          status: state.applyStatus, effective_console_port: 8765,
          safe_summary: "Configuration state" });
      }
      if (url === "/api/v1/admin/status") {
        if (state.statusFailure) throw new Error("Status offline");
        if (options.statusRead) return options.statusRead(request, response);
        return response({ config_path: "/fixture/production.json", config_source: "saved",
          runtime_environment_path: "/fixture/runtime.env", restart_required: state.restart,
          delivery_runtime: state.statusRuntime, live_model_execution: false,
          database: { connection: state.databaseConnection, source: "runtime.env" },
          codex: { available: true, executable: "codex", resolved_path: "/bin/codex" },
          team_prepared: true, team_knowledge_imported: 0, team_knowledge_selected: 0,
          model_routes: [], agent_model_routes: [] });
      }
      if (url === "/api/v1/admin/projects" && request.method === "POST" && options.projectPost)
        return await options.projectPost;
      if (url === "/api/v1/admin/projects" || url === "/api/v1/admin/team/knowledge")
        return response([]);
      if (url === "/api/v1/admin/team/knowledge/index") return response(null);
      if (/^\/api\/v1\/admin\/projects\/[^/]+\/knowledge$/.test(url))
        return options.knowledgeRead ? options.knowledgeRead(url, response, request) : response([]);
      if (/^\/api\/v1\/admin\/projects\/[^/]+\/knowledge\/index$/.test(url))
        return response(null);
      throw new Error("Unexpected request: " + url);
    },
    setTimeout: (callback, delay) => {
      const id = ++timerId;
      timers.set(id, { callback, delay });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
    setInterval: (callback) => { poll = callback; },
    localStorage: { getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
    location: { href: "http://127.0.0.1:8765/", port: "8765", assign() {} },
    URL, AbortController, structuredClone,
  });
  const script = process.env.ASE_READINESS_APP_JS || path.join(
    __dirname, "../../src/ai_software_engineer/team_view/app.js");
  vm.runInContext(fs.readFileSync(script, "utf8"), context, { filename: script });
  await settled();
  return {
    state, config, requests, context, get,
    content: () => text(get("content")),
    navigate: async (target) => { await get("nav-" + target).events.click(); await settled(); },
    tick: async () => { await poll(); await settled(); },
    click: async (title) => {
      const control = descendants(get("content"))
        .find((node) => node.tag === "button" && node.textContent === title);
      assert.ok(control, "Missing button: " + title);
      await control.events.click();
      await settled();
    },
    input: (value) => descendants(get("content"))
      .find((node) => node.tag === "input" && node.value === value),
    runTimer: async (delay) => {
      const entry = [...timers].find(([, timer]) => timer.delay === delay);
      assert.ok(entry, "Missing timeout of " + delay + " ms");
      timers.delete(entry[0]);
      await entry[1].callback();
      await settled();
    },
  };
}

test("Project click during an in-flight poll is retained without another click or timer", async () => {
  const options = { ready: true, restart: false, project: true, projects: [
    { id: "project_fixture", name: "Fixture project" },
    { id: "project_other", name: "Other project" },
  ] };
  const ui = await browser(options);
  const held = deferred();
  options.teamRead = async (url, _request, team, response) => {
    const target = new URL(url, "http://fixture").searchParams.get("project_id");
    if (target === "project_fixture") await held.promise;
    return response({ ...team, selected_project_id: target });
  };
  const polling = ui.tick();
  await settled();
  const option = descendants(ui.get("projects"))
    .find(node => node.tag === "button" && node.textContent === "Other project");
  assert.ok(option);
  option.events.click();
  assert.match(text(ui.get("connection")), /正在切换到「Other project」.*仍显示「Fixture project」/);
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), false);
  held.resolve();
  await polling;
  await settled();
  assert.equal(vm.runInContext("currentProjectId()", ui.context), "project_other");
  assert.equal(ui.requests.filter(({ url }) => url.endsWith("project_id=project_other")).length, 1);
  assert.equal(ui.get("refresh").disabled, false);
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), true);
});

test("validated Team facts publish while independent Operations are still pending", async () => {
  const options = { ready: true, restart: false, project: true };
  const ui = await browser(options);
  const held = deferred();
  options.operationsRead = async (_request, response) => {
    await held.promise;
    return response([]);
  };
  options.teamRead = async (_url, _request, team, response) =>
    response({ ...team, team_name: "Updated team" });
  const polling = ui.tick();
  await settled();
  assert.equal(vm.runInContext("snapshot.team_name", ui.context), "Updated team");
  assert.equal(ui.get("team").textContent, "Updated team");
  assert.equal(vm.runInContext("refreshing", ui.context), true,
    "the serial refresh still owns the unfinished independent read");
  held.resolve();
  await polling;
  assert.equal(vm.runInContext("refreshing", ui.context), false);
});

test("a late exact edit result cannot reopen detail after the user explicitly closes it", async () => {
  const request = {id: "request_saved", title: "Original requirement", project_id: "project_fixture",
    stage: "READY_FOR_DISCUSSION", checkpoint_sha256: "a".repeat(64), scopes: [], documents: [], dialogue: []};
  const options = {ready: true, restart: false, project: true, requests: [request]};
  const ui = await browser(options);
  vm.runInContext('showDetail("request", "request_saved")', ui.context);
  const teamHeld = deferred(), operationsHeld = deferred();
  options.teamRead = async (_url, _request, team, response) => {
    await teamHeld.promise;
    return response({...team, requests: [{...request, id: "request_replacement", title: "Edited requirement"}]});
  };
  options.operationsRead = async (_request, response) => {
    await operationsHeld.promise;
    return response([{operation_id: "operation_edit", status: "SUCCEEDED", updated_at: "2026-10-09T00:00:00Z",
      intent: {action: "UPDATE_REQUIREMENT", project_id: "project_fixture", delivery_id: request.id},
      result: {delivery_id: "request_replacement"}}]);
  };
  const polling = ui.tick();
  await settled();
  const close = descendants(ui.get("detail")).find(node => node.tag === "button" && node.textContent === "关闭详情");
  assert.ok(close);
  close.events.click();
  teamHeld.resolve();
  await settled();
  operationsHeld.resolve();
  await polling;
  assert.equal(vm.runInContext("selected", ui.context), null);
  assert.equal(ui.get("detail").hidden, true);
});

test("Operations read failure preserves complete historical rows but revokes current authority", async () => {
  const ui = await browser({ ready: true, restart: false, project: true });
  const saved = { operation_id: "operation_saved", status: "RUNNING",
    updated_at: "2026-10-09T00:00:00Z",
    intent: { action: "CONTINUE_DELIVERY", project_id: "project_fixture", delivery_id: "request_saved" } };
  ui.context.saved = saved;
  vm.runInContext("operations = [saved]; operationsAvailable = true;", ui.context);
  ui.state.operationsFailure = true;
  await ui.tick();
  assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(operations)", ui.context)), [saved]);
  assert.equal(vm.runInContext("operationsAvailable", ui.context), false);
  assert.equal(vm.runInContext('activeOperation("request_saved")', ui.context), undefined);
  assert.equal(vm.runInContext('latestApproval("request_saved", "checkpoint")', ui.context), null);
  assert.equal(vm.runInContext('engineeringBaselineProposalOperation({})', ui.context), null);
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), false);
  assert.match(text(ui.get("connection")), /操作记录.*读取失败/);
});

test("Knowledge reads obey the refresh deadline and release the serial lane after timeout", async () => {
  const options = { ready: true, restart: false, project: true };
  const ui = await browser(options);
  await ui.navigate("knowledge");
  vm.runInContext('knowledgeScope = "project";', ui.context);
  let signal;
  options.knowledgeRead = async (_url, _response, request) => {
    signal = request.signal;
    return new Promise((_resolve, reject) => {
      signal?.addEventListener("abort", () => reject(new Error("fixture read timeout")), { once: true });
    });
  };
  const polling = ui.tick();
  await settled();
  assert.ok(signal instanceof AbortSignal, "the knowledge GET has an explicit read deadline");
  await ui.runTimer(40000);
  await polling;
  assert.equal(signal.aborted, true);
  assert.match(vm.runInContext("knowledgeError", ui.context), /知识读取等待超时或连接已中断/);
  assert.equal(vm.runInContext("refreshing || refreshFlight !== null", ui.context), false);
  assert.equal(ui.get("refresh").disabled, false);
  options.knowledgeRead = undefined;
  await ui.tick();
  assert.equal(vm.runInContext("knowledgeError", ui.context), null);
});

for (const phase of ["headers", "body"]) test(`independent Status navigation has a read deadline and recovers after timeout: ${phase}`, async () => {
  const options = {ready: true, restart: false, project: true};
  const ui = await browser(options);
  let signal;
  options.statusRead = async (request) => {
    signal = request.signal;
    const pending = new Promise((_resolve, reject) => {
      signal?.addEventListener("abort", () => reject(Object.assign(new Error("fixture status timeout"),
        {name: "AbortError"})), {once: true});
    });
    return phase === "body" ? {ok: true, json: () => pending} : pending;
  };
  const navigation = ui.navigate("status");
  await settled();
  assert.ok(signal instanceof AbortSignal, "the standalone Status GET has a bounded signal");
  assert.equal(vm.runInContext("runtimeStatusLoading", ui.context), true);
  await ui.runTimer(40000);
  await navigation;
  assert.equal(signal.aborted, true);
  assert.equal(vm.runInContext("runtimeStatusLoading", ui.context), false);
  assert.equal(vm.runInContext("runtimeStatusSnapshot", ui.context), null);
  assert.match(ui.content(), /平台状态读取等待超时或连接已中断/);
  options.statusRead = undefined;
  await ui.navigate("status");
  assert.match(ui.content(), /平台可以接收交付任务/);
});

async function projectBrowser() {
  const options = { ready: true, restart: false, project: true, projects: [
    { id: "project_fixture", name: "Fixture project" },
    { id: "project_b", name: "Project B" }, { id: "project_c", name: "Project C" },
  ] };
  const ui = await browser(options);
  const choose = name => {
    const option = descendants(ui.get("projects"))
      .find(node => node.tag === "button" && node.textContent === name);
    assert.ok(option, name);
    return option.events.click();
  };
  const current = () => vm.runInContext("currentProjectId()", ui.context);
  return { ui, options, choose, current };
}
const projectTarget = url => new URL(url, "http://fixture").searchParams.get("project_id");

for (const oldFails of [false, true]) test(`only the latest queued Project is read; old failure=${oldFails}`, async () => {
  const { ui, options, choose, current } = await projectBrowser();
  const old = deferred(), latest = deferred(), reads = [];
  options.teamRead = async (url, _request, team, response) => {
    const target = projectTarget(url); reads.push(target);
    if (target === "project_fixture") {
      await old.promise;
      if (oldFails) throw new Error("old project read failed");
    } else await latest.promise;
    return response({ ...team, selected_project_id: target });
  };
  const poll = ui.tick();
  choose("Project B");
  const chosen = choose("Project C");
  const ticks = [ui.tick(), ui.tick(), ui.tick()];
  old.resolve(); await settled();
  assert.equal(current(), "project_fixture", "old data must not be relabelled as the pending Project");
  assert.deepEqual(reads, ["project_fixture", "project_c"]);
  assert.match(text(ui.get("connection")), /正在切换到「Project C」/);
  latest.resolve(); await Promise.all([poll, chosen, ...ticks]);
  assert.equal(current(), "project_c");
  assert.equal(ui.get("connection").className, "");
  assert.equal(vm.runInContext("refreshing || refreshFlight !== null", ui.context), false);
});

test("selecting the current Project cancels a queued switch without reading the discarded Project", async () => {
  const { ui, options, choose, current } = await projectBrowser();
  const held = deferred(), reads = [];
  options.teamRead = async (url, _request, team, response) => {
    reads.push(projectTarget(url)); await held.promise; return response(team);
  };
  const poll = ui.tick();
  choose("Project B"); choose("Fixture project");
  held.resolve(); await poll;
  assert.equal(current(), "project_fixture");
  assert.deepEqual(reads, ["project_fixture"]);
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), true);
});

test("a superseded response body cannot publish while the latest Project is loading", async () => {
  const { ui, options, choose, current } = await projectBrowser();
  const body = deferred(), latest = deferred();
  let original;
  options.teamRead = async (url, _request, team, response) => {
    original = team;
    if (projectTarget(url) === "project_b") return { ok: true, json: () => body.promise };
    await latest.promise;
    return response({ ...team, selected_project_id: "project_c" });
  };
  const first = choose("Project B"); await settled();
  const second = choose("Project C");
  body.resolve({ ...original, selected_project_id: "project_b" }); await settled();
  assert.equal(current(), "project_fixture");
  assert.doesNotMatch(text(ui.get("projects")), /Project B当前/);
  latest.resolve(); await Promise.all([first, second]);
  assert.equal(current(), "project_c");
});

test("Knowledge loading keeps the rendered Project aligned before a later switch fails", async () => {
  const { ui, options, choose, current } = await projectBrowser();
  await ui.navigate("knowledge");
  await ui.click("项目知识库");
  const knowledge = deferred();
  options.knowledgeRead = async (_url, response) => {
    await knowledge.promise;
    return response([]);
  };
  options.teamRead = async (url, _request, team, response) => {
    const target = projectTarget(url);
    if (target === "project_c") throw new Error("latest project unavailable");
    return response({ ...team, selected_project_id: target });
  };
  const first = choose("Project B"); await settled();
  assert.equal(current(), "project_b");
  const selectedTab = () => descendants(ui.get("content"))
    .find(node => node.getAttribute("aria-current") === "true");
  assert.equal(selectedTab()?.textContent, "Project B");
  assert.match(ui.content(), /正在读取当前知识库/);
  const second = choose("Project C");
  knowledge.resolve(); await Promise.all([first, second]);
  assert.equal(current(), "project_b");
  assert.equal(selectedTab()?.textContent, "Project B");
  assert.match(ui.content(), /Project B · Project 知识/);
  assert.doesNotMatch(ui.content(), /正在读取当前知识库/);
  assert.match(text(ui.get("connection")), /切换到「Project C」失败/);
});

for (const failure of ["network", "wrong_project"]) test(`a failed target preserves prior data and retry intent: ${failure}`, async () => {
  const { ui, options, choose, current } = await projectBrowser();
  const reads = []; let fail = true;
  options.teamRead = async (url, _request, team, response) => {
    const target = projectTarget(url); reads.push(target);
    if (fail && failure === "network") throw new Error("fixture unavailable");
    return response({ ...team, selected_project_id: fail ? "project_fixture" : target });
  };
  await choose("Project B");
  assert.equal(current(), "project_fixture");
  assert.match(text(ui.get("connection")), /切换到「Project B」失败.*刷新将重试/);
  assert.equal(ui.get("refresh").disabled, false);
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), false);
  fail = false; await ui.tick();
  assert.deepEqual(reads, ["project_b", "project_b"]);
  assert.equal(current(), "project_b");
  assert.equal(ui.get("connection").className, "");
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), true);
});

test("an old timed out poll releases the lane to the pending Project", async () => {
  const { ui, options, choose, current } = await projectBrowser();
  options.teamRead = async (url, request, team, response) => {
    const target = projectTarget(url);
    if (target === "project_fixture") await new Promise((_, reject) =>
      request.signal.addEventListener("abort", () => reject(new Error("fixture timeout")), { once: true }));
    return response({ ...team, selected_project_id: target });
  };
  const poll = ui.tick();
  choose("Project B");
  await ui.runTimer(40000); await poll;
  assert.equal(current(), "project_b");
  assert.equal(vm.runInContext("refreshing", ui.context), false);
  assert.equal(ui.get("connection").className, "");
});

test("manual runtime status refresh is retained while periodic ticks are coalesced", async () => {
  const { ui, options } = await projectBrowser();
  await ui.navigate("status");
  const held = deferred(); let teamReads = 0;
  options.teamRead = async (_url, _request, team, response) => {
    if (++teamReads === 1) await held.promise;
    return response(team);
  };
  const statusReads = () => ui.requests.filter(({ url }) => url === "/api/v1/admin/status").length;
  const before = statusReads();
  const poll = ui.tick(); await settled();
  const manual = vm.runInContext("refresh(undefined, true)", ui.context);
  const extra = ui.tick(); held.resolve();
  await Promise.all([poll, manual, extra]);
  assert.equal(teamReads, 2);
  assert.equal(statusReads(), before + 1);
});

for (const guard of ["dirty", "busy"]) test(`Project switching respects the ${guard} composer guard`, async () => {
  const { ui, choose, current } = await projectBrowser();
  const dialog = new Element("form"); ui.get("composer").append(dialog);
  ui.context.confirm = () => false;
  vm.runInContext(guard === "dirty"
    ? 'dirtyComposers.add(document.getElementById("composer").firstElementChild)'
    : 'uiCommands.set(document.getElementById("composer").firstElementChild, [])', ui.context);
  const reads = ui.requests.length;
  await choose("Project B");
  assert.equal(ui.requests.length, reads);
  assert.equal(current(), "project_fixture");
  assert.equal(vm.runInContext("requestedProjectId", ui.context), null);
  assert.equal(ui.get("composer").firstElementChild, dialog);
});

async function applySuccessfully(ui) {
  await vm.runInContext("applySavedConfiguration()", ui.context);
  ui.state.ready = true;
  ui.state.restart = false;
  ui.state.applyStatus = "SUCCEEDED";
  await ui.runTimer(1000);
}

test("confirmed apply refreshes false readiness immediately, and success expires without returning", async () => {
  const ui = await browser();
  await ui.navigate("settings");
  assert.match(ui.content(), /当前交付运行时尚未就绪/);
  await applySuccessfully(ui);
  assert.doesNotMatch(ui.content(), /当前交付运行时尚未就绪/);
  assert.match(ui.content(), /当前配置已生效/);
  assert.ok(ui.content().includes(successMessage));
  await ui.runTimer(5000);
  assert.ok(!ui.content().includes(successMessage));
  await ui.navigate("team");
  await ui.navigate("settings");
  assert.ok(!ui.content().includes(successMessage));
});

test("acknowledging apply success stays dismissed when Settings is reopened", async () => {
  const ui = await browser();
  await ui.navigate("settings");
  await applySuccessfully(ui);
  await ui.click("关闭配置提示");
  assert.ok(!ui.content().includes(successMessage));
  await ui.navigate("team");
  await ui.navigate("settings");
  assert.ok(!ui.content().includes(successMessage));
});

test("historical successful apply never starts a new success notification", async () => {
  const ui = await browser({ ready: true, restart: false, applyStatus: "SUCCEEDED" });
  await ui.navigate("settings");
  assert.ok(!ui.content().includes(successMessage));
  await ui.navigate("team");
  await ui.navigate("settings");
  assert.ok(!ui.content().includes(successMessage));
});

test("confirmed apply preserves edits entered while waiting for the process to restart", async () => {
  const ui = await browser();
  await ui.navigate("settings");
  await vm.runInContext("applySavedConfiguration()", ui.context);
  const root = ui.input("/fixture/platform");
  root.value = "/fixture/edited-during-restart";
  root.events.input();
  await ui.click("MySQL");
  const password = ui.input("");
  password.value = "fake-secret-during-restart";
  password.events.input();
  ui.state.ready = true;
  ui.state.restart = false;
  ui.state.applyStatus = "SUCCEEDED";
  await ui.runTimer(1000);
  assert.ok(ui.input("fake-secret-during-restart"));
  await ui.click("基础配置");
  assert.ok(ui.input("/fixture/edited-during-restart"));
});

test("Team failure does not prevent console/settings refresh after manual restart or erase unsaved fields", async () => {
  const ui = await browser();
  await ui.navigate("settings");
  const root = ui.input("/fixture/platform");
  root.value = "/fixture/unsaved";
  root.events.input();
  await ui.click("MySQL");
  const password = ui.input("");
  password.value = "fake-unsaved-dsn";
  password.events.input();
  ui.state.teamFailure = true;
  ui.state.ready = true;
  ui.state.restart = false;
  const requestStart = ui.requests.length;
  await ui.tick();
  assert.ok(ui.requests.slice(requestStart).some(({ url }) => url === "/api/v1/console"));
  assert.ok(ui.requests.slice(requestStart).some(({ url }) => url === "/api/v1/admin/settings"));
  assert.match(ui.content(), /当前配置已生效/);
  assert.doesNotMatch(ui.content(), /当前交付运行时尚未就绪|已保存 · 需要重启/);
  assert.equal(ui.input("fake-unsaved-dsn").type, "password");
  await ui.click("基础配置");
  assert.ok(ui.input("/fixture/unsaved"));
  assert.match(text(ui.get("connection")), /刷新失败/);
});

test("Settings and Status remain usable when the first Team projection is unavailable", async () => {
  const ui = await browser({ teamFailure: true, ready: true, restart: false });
  assert.equal(vm.runInContext("snapshot", ui.context), null);
  await ui.navigate("settings");
  assert.match(ui.content(), /平台设置/);
  assert.match(ui.content(), /当前配置已生效/);
  assert.equal(vm.runInContext("snapshot", ui.context), null);
  await ui.navigate("status");
  assert.match(ui.content(), /平台可以接收交付任务/);
  assert.equal(vm.runInContext("snapshot", ui.context), null);
  assert.match(text(ui.get("connection")), /暂时无法读取|不可用/);
});

test("Team busy is a read-in-progress message, not a database failure", async () => {
  let busy = true;
  const ui = await browser({ ready: true, restart: false,
    teamRead: (_url, _request, team, response) => busy
      ? response({error: {code: "TEAM_READ_IN_PROGRESS", message: "untrusted provider detail"}}, false)
      : response(team),
  });
  assert.match(text(ui.get("connection")), /上一轮.*读取.*未完成/);
  assert.match(ui.content(), /团队数据.*读取中/);
  assert.doesNotMatch(text(ui.get("connection")) + ui.content(), /MySQL|untrusted provider/);
  busy = false;
  await ui.tick();
  assert.match(text(ui.get("connection")), /已连接/);
  const snapshotBefore = vm.runInContext("snapshot", ui.context);
  busy = true;
  await ui.tick();
  assert.equal(vm.runInContext("snapshot", ui.context), snapshotBefore);
  assert.match(text(ui.get("connection")), /旧数据/);
  assert.doesNotMatch(text(ui.get("connection")), /MySQL|刷新失败/);
});

for (const failure of ["busy", "unavailable", "timeout"]) {
  test(`stale Team ${failure} pauses controls, retains the draft and recovers with unchanged facts`, async () => {
    let fail = false;
    const ui = await browser({ready: true, restart: false, project: true,
      requests: [{id: "request_fixture", project_id: "project_fixture", title: "Retained Requirement",
        stage: "READY_FOR_DISCUSSION", next_action: "Start discussion", checkpoint_sha256: "a".repeat(64),
        scopes: [], documents: []}],
      teamRead: (_url, request, team, response) => {
        if (!fail) return response(team);
        if (failure === "timeout") return new Promise((_resolve, reject) => {
          request.signal.addEventListener("abort", () => reject(new Error("fixture timeout")), {once: true});
        });
        return response({error: {code: failure === "busy" ? "TEAM_READ_IN_PROGRESS" : "TEAM_UNAVAILABLE"}}, false);
      },
    });
    await ui.navigate("requests");
    assert.ok(descendants(ui.get("detail")).find(node => node.tag === "button" && node.textContent === "删除需求"));
    await ui.click("新建需求");
    const form = descendants(ui.get("composer")).find(node => node.tag === "form");
    const name = descendants(form).find(node => node.tag === "input");
    const submit = descendants(form).find(node => node.tag === "button" && node.type === "submit");
    name.value = "Do not lose this Requirement draft";
    const original = vm.runInContext("snapshot", ui.context);
    fail = true;
    const polling = ui.tick();
    if (failure === "timeout") {
      await settled();
      await ui.runTimer(40000);
    }
    await polling;
    assert.equal(vm.runInContext("snapshot", ui.context), original);
    assert.equal(vm.runInContext("operationsAvailable && consoleDeliveryReady", ui.context), true);
    assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), false,
      "successful independent Operations/Console reads cannot authorize an old Team snapshot");
    assert.equal(submit.disabled, true);
    assert.equal(descendants(ui.get("composer")).find(node => node.tag === "form"), form);
    assert.equal(name.value, "Do not lose this Requirement draft");
    assert.equal(descendants(ui.get("detail")).some(node => node.tag === "button" && node.textContent === "删除需求"), false,
      "the actual detail must rerender even when only Team freshness changed");
    assert.match(text(ui.get("connection")), /旧数据/);
    const result = await vm.runInContext('submitOperation({action: "CONTINUE_DELIVERY", project_id: "project_fixture", delivery_id: "request_fixture"})', ui.context);
    assert.equal(result, null);
    assert.equal(ui.requests.filter(request => request.method === "POST").length, 0);
    fail = false;
    await ui.tick();
    assert.equal(vm.runInContext("teamReadIssue", ui.context), null);
    assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), true);
    assert.equal(submit.disabled, false);
    assert.ok(descendants(ui.get("detail")).find(node => node.tag === "button" && node.textContent === "删除需求"),
      "unchanged recovered Team facts refresh detail controls even with a composer open");
    assert.equal(descendants(ui.get("composer")).find(node => node.tag === "form"), form);
    assert.equal(name.value, "Do not lose this Requirement draft");
    assert.doesNotMatch(text(ui.get("connection")), /旧数据/);
  });
}

test("a failed Team branch revokes old controls before an independent Operations read settles", async () => {
  const options = {ready: true, restart: false, project: true};
  const ui = await browser(options);
  await ui.navigate("requests");
  await ui.click("新建需求");
  const form = descendants(ui.get("composer")).find(node => node.tag === "form");
  const submit = descendants(form).find(node => node.tag === "button" && node.type === "submit");
  const held = deferred();
  options.operationsRead = async (_request, response) => {await held.promise; return response([]);};
  options.teamRead = (_url, _request, _team, response) =>
    response({error: {code: "TEAM_READ_IN_PROGRESS"}}, false);
  const polling = ui.tick();
  await settled();
  const controlWhileHeld = vm.runInContext("canControlCurrentTeam()", ui.context);
  const issueWhileHeld = vm.runInContext("teamReadIssue", ui.context);
  const disabledWhileHeld = submit.disabled;
  if (!controlWhileHeld) {
    await vm.runInContext('submitOperation({action: "CONTINUE_DELIVERY", project_id: "project_fixture", delivery_id: "request_fixture"})', ui.context);
  }
  held.resolve();
  await polling;
  assert.equal(issueWhileHeld, "busy");
  assert.equal(controlWhileHeld, false, "Team failure must not wait for an unrelated read to revoke authority");
  assert.equal(disabledWhileHeld, true);
  assert.equal(ui.requests.filter(request => request.method === "POST").length, 0);
  assert.equal(descendants(ui.get("composer")).find(node => node.tag === "form"), form);
});

test("a published Team remains current when a later Knowledge auxiliary branch fails", async () => {
  const ui = await browser({ready: true, restart: false, project: true});
  await ui.navigate("knowledge");
  vm.runInContext('loadKnowledge = async () => {throw new Error("fixture auxiliary failure");}', ui.context);
  await ui.tick();
  assert.equal(vm.runInContext("teamReadIssue", ui.context), null);
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), true);
  assert.match(text(ui.get("connection")), /团队数据已更新.*辅助记录刷新失败/);
  assert.doesNotMatch(text(ui.get("connection")), /旧数据|团队数据读取失败/);
});

test("Team read timeout is distinct and cannot claim the backend execution stopped", async () => {
  const ui = await browser({ready: true, restart: false,
    teamRead: (_url, request) => new Promise((_resolve, reject) => {
      request.signal.addEventListener("abort", () => reject(new Error("aborted")), {once:true});
    }),
  });
  await ui.runTimer(40000);
  assert.match(text(ui.get("connection")), /读取超时/);
  assert.match(text(ui.get("connection")), /后台读取可能仍在进行/);
  assert.doesNotMatch(text(ui.get("connection")), /MySQL|停止执行/);
});

test("a stalled error response body still reports the Team read deadline", async () => {
  const ui = await browser({ready: true, restart: false,
    teamRead: (_url, request) => ({ok: false, json: () => new Promise((_resolve, reject) => {
      request.signal.addEventListener("abort", () => reject(new Error("body aborted")), {once:true});
    })}),
  });
  await ui.runTimer(40000);
  assert.match(text(ui.get("connection")), /读取超时/);
  assert.match(ui.content(), /后台读取可能仍在进行/);
  assert.equal(ui.get("refresh").disabled, false);
});

test("Team unavailable never exposes the server body or guesses database failure", async () => {
  const ui = await browser({ ready: true, restart: false,
    teamRead: (_url, _request, _team, response) => response({error: {
      code: "TEAM_UNAVAILABLE", message: "mysql+pymysql://user:private-secret@host/db",
    }}, false),
  });
  assert.match(text(ui.get("connection")), /团队数据读取失败/);
  assert.doesNotMatch(text(ui.get("connection")) + ui.content(), /private-secret|MySQL/);
});

test("manual restart updates an open save-result dialog without leaving stale apply instructions", async () => {
  const ui = await browser();
  await ui.navigate("settings");
  const form = descendants(ui.get("content")).find((node) => node.tag === "form");
  await form.events.submit({ preventDefault() {} });
  assert.match(text(ui.get("composer")), /应用配置/);
  assert.match(text(ui.get("composer")), /重启 Web Console/);
  ui.state.ready = true;
  ui.state.restart = false;
  await ui.tick();
  assert.match(text(ui.get("composer")), /配置已生效/);
  assert.doesNotMatch(text(ui.get("composer")), /应用配置|重启 Web Console/);
  assert.match(ui.content(), /当前配置已生效/);
  assert.doesNotMatch(ui.content(), /当前交付运行时尚未就绪/);
});

test("Status follows readiness transitions and does not probe dependencies on unchanged polls", async () => {
  const ui = await browser();
  await ui.navigate("status");
  assert.match(ui.content(), /请重启 Web Console/);
  const reads = () => ui.requests.filter(({ url }) => url === "/api/v1/admin/status").length;
  const before = reads();
  await ui.tick();
  assert.equal(reads(), before);
  ui.state.ready = true;
  ui.state.restart = false;
  await ui.tick();
  assert.equal(reads(), before + 1);
  assert.match(ui.content(), /平台可以接收交付任务/);
  assert.doesNotMatch(ui.content(), /请重启|等待重启|待重启/);
});

test("an unready dependency with restart_required=false does not ask for another restart", async () => {
  const ui = await browser({ restart: false });
  ui.state.statusRuntime = "UNAVAILABLE";
  ui.state.databaseConnection = "FAILED";
  await ui.navigate("status");
  assert.match(ui.content(), /尚未就绪的运行依赖/);
  assert.match(ui.content(), /连接失败/);
  assert.doesNotMatch(ui.content(), /重启/);
});

test("Console/status network failures never manufacture ready state", async () => {
  const ui = await browser({ restart: false });
  await ui.navigate("settings");
  ui.state.consoleFailure = true;
  await ui.tick();
  assert.notEqual(vm.runInContext("consoleDeliveryReady", ui.context), true);
  assert.ok(!ui.content().includes(successMessage));
  ui.state.statusFailure = true;
  await ui.navigate("status");
  assert.doesNotMatch(ui.content(), /平台可以接收交付任务/);
  assert.match(ui.content(), /暂时无法读取|Status offline/);
});

test("Operations failure keeps runtime facts readable while disabling delivery controls", async () => {
  const ui = await browser({ ready: true, restart: false });
  await ui.navigate("requests");
  assert.equal(ui.get("project-creator").hidden, false);
  ui.state.operationsFailure = true;
  await ui.tick();
  assert.equal(vm.runInContext("consoleDeliveryReady", ui.context), true);
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), false);
  assert.equal(ui.get("project-creator").hidden, true);
  await ui.navigate("settings");
  assert.match(ui.content(), /当前配置已生效/);
  assert.doesNotMatch(ui.content(), /当前交付运行时尚未就绪/);
  ui.state.operationsFailure = false;
  await ui.tick();
  await ui.navigate("requests");
  assert.equal(ui.get("project-creator").hidden, false);
});

test("Console disconnection is not a read-only dashboard and reconnect restores control", async () => {
  const ui = await browser({ ready: true, restart: false, project: true });
  await ui.navigate("requests");
  await ui.click("新建需求");
  const name = descendants(ui.get("composer")).find((node) => node.tag === "input");
  name.value = "Preserve the Requirement draft";
  ui.state.consoleFailure = true;
  await ui.tick();
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), false);
  const notices = vm.runInContext("JSON.stringify(systemOperationNotices())", ui.context);
  assert.match(notices, /连接.*中断|暂时无法连接/);
  assert.doesNotMatch(notices, /当前连接的是只读看板/);
  assert.equal(descendants(ui.get("composer")).find((node) => node.tag === "input"), name);
  ui.state.consoleFailure = false;
  await ui.tick();
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), true);
  assert.doesNotMatch(vm.runInContext("JSON.stringify(systemOperationNotices())", ui.context), /连接.*中断|暂时无法连接/);
  assert.equal(name.value, "Preserve the Requirement draft");
});

for (const failure of ["404", "503", "invalid", "json"]) test(`Console metadata failure classification: ${failure}`, async () => {
  const ui = await browser({ ready: true, restart: false });
  if (failure === "invalid") ui.state.consoleInvalid = true;
  else if (failure === "json") ui.state.consoleInvalidJson = true;
  else ui.state.consoleStatus = Number(failure);
  await ui.tick();
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), false);
  assert.equal(vm.runInContext("consoleDeliveryReady", ui.context), null);
  const notices = vm.runInContext("JSON.stringify(systemOperationNotices())", ui.context);
  if (failure === "404") assert.match(notices, /未提供交付控制接口/);
  else {
    assert.match(notices, /连接.*中断|暂时无法连接/);
    assert.doesNotMatch(notices, /只读看板/);
  }
});

test("success expiry cannot rebuild a new Project form on another page or erase its draft", async () => {
  const ui = await browser();
  await ui.navigate("settings");
  await applySuccessfully(ui);
  await ui.navigate("requests");
  const create = descendants(ui.get("project-creator"))
    .find((node) => node.tag === "button" && node.textContent === "新建 Project");
  await create.events.click();
  const name = descendants(ui.get("composer")).find((node) => node.tag === "input");
  name.value = "Project draft survives notification expiry";
  await ui.runTimer(5000);
  const current = descendants(ui.get("composer")).find((node) => node.tag === "input");
  assert.equal(current, name, "notification expiry must preserve the active form node");
  assert.equal(current.value, "Project draft survives notification expiry");
});

test("success expiry cannot reconstruct an unrelated pending confirmation dialog", async () => {
  const ui = await browser();
  await ui.navigate("settings");
  await applySuccessfully(ui);
  await ui.navigate("requests");
  vm.runInContext('confirmMutation("Confirm fixture", "Keep this dialog", "Confirm", async () => {})', ui.context);
  const dialog = ui.get("composer").children[0];
  await ui.runTimer(5000);
  assert.equal(ui.get("composer").children[0], dialog);
  assert.match(text(dialog), /Keep this dialog/);
});

test("simultaneous Team and Operations failure revokes existing delivery controls without losing the draft", async () => {
  const ui = await browser({ ready: true, restart: false, project: true });
  await ui.navigate("requests");
  await ui.click("新建需求");
  const name = descendants(ui.get("composer")).find((node) => node.tag === "input");
  const submit = descendants(ui.get("composer"))
    .find((node) => node.tag === "button" && node.type === "submit");
  name.value = "Unsaved Requirement";
  assert.notEqual(submit.disabled, true);
  assert.equal(ui.get("project-creator").hidden, false);
  ui.state.teamFailure = true;
  ui.state.operationsFailure = true;
  await ui.tick();
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), false);
  assert.equal(ui.get("project-creator").hidden, true);
  assert.equal(submit.disabled, true);
  assert.equal(ui.get("operations").hidden, true);
  assert.match(text(ui.get("notification")), /交付操作记录暂时无法读取/);
  assert.equal(descendants(ui.get("composer")).find((node) => node.tag === "input"), name);
  assert.equal(name.value, "Unsaved Requirement");
  ui.state.teamFailure = false;
  ui.state.operationsFailure = false;
  await ui.tick();
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), true);
  assert.equal(ui.get("project-creator").hidden, false);
  assert.equal(submit.disabled, false);
  assert.doesNotMatch(text(ui.get("notification")), /交付操作记录暂时无法读取/);
  assert.equal(descendants(ui.get("composer")).find((node) => node.tag === "input"), name);
  assert.equal(name.value, "Unsaved Requirement");
});

test("direct operation submission cannot POST after simultaneous Team and Operations failure", async () => {
  const ui = await browser({ ready: true, restart: false, project: true });
  await ui.navigate("requests");
  ui.state.teamFailure = true;
  ui.state.operationsFailure = true;
  await ui.tick();
  const result = await vm.runInContext('submitOperation({action: "CREATE_REQUIREMENT", project_id: "project_fixture", name: "fixture", repository_roots: ["/fixture/repository"]})', ui.context);
  assert.equal(result, null);
  assert.equal(ui.requests.filter(({ url, method }) => url === "/api/v1/operations" && method === "POST").length, 0);
});

test("an existing Project form cannot POST while delivery controls are unavailable and keeps its draft", async () => {
  const ui = await browser({ ready: true, restart: false });
  await ui.navigate("requests");
  const create = descendants(ui.get("project-creator"))
    .find((node) => node.tag === "button" && node.textContent === "新建 Project");
  await create.events.click();
  const form = descendants(ui.get("composer")).find((node) => node.tag === "form");
  const name = descendants(form).find((node) => node.tag === "input");
  const submit = descendants(form).find((node) => node.tag === "button" && node.type === "submit");
  name.value = "Keep Project draft";
  ui.state.teamFailure = true;
  ui.state.operationsFailure = true;
  await ui.tick();
  assert.equal(submit.disabled, true);
  await form.events.submit({ preventDefault() {} });
  assert.equal(ui.requests.filter(({ url, method }) => url === "/api/v1/admin/projects" && method === "POST").length, 0);
  assert.equal(descendants(ui.get("composer")).find((node) => node.tag === "form"), form);
  assert.equal(name.value, "Keep Project draft");
  ui.state.teamFailure = false;
  ui.state.operationsFailure = false;
  await ui.tick();
  assert.equal(submit.disabled, false);
  assert.equal(descendants(ui.get("composer")).find((node) => node.tag === "form"), form);
  assert.equal(name.value, "Keep Project draft");
});

for (const recoverBeforePostFailure of [false, true]) {
  test(recoverBeforePostFailure
    ? "Project remains busy if read connectivity recovers before its pending POST fails"
    : "Project submit recovers if its pending POST fails while read connectivity is unavailable", async () => {
    const projectPost = deferred();
    const ui = await browser({ ready: true, restart: false, projectPost: projectPost.promise });
    await ui.navigate("requests");
    const create = descendants(ui.get("project-creator"))
      .find((node) => node.tag === "button" && node.textContent === "新建 Project");
    await create.events.click();
    const form = descendants(ui.get("composer")).find((node) => node.tag === "form");
    const name = descendants(form).find((node) => node.tag === "input");
    const submit = descendants(form).find((node) => node.tag === "button" && node.type === "submit");
    name.value = "Project draft during connection loss";
    const submitting = form.events.submit({ preventDefault() {} });
    await settled();
    assert.equal(submit.disabled, true, "the pending POST must hold the busy state");
    assert.equal(ui.requests.filter(({ url, method }) => url === "/api/v1/admin/projects" && method === "POST").length, 1);
    ui.state.teamFailure = true;
    ui.state.operationsFailure = true;
    await ui.tick();
    assert.equal(submit.disabled, true);
    assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), false);
    const recover = async () => {
      ui.state.teamFailure = false;
      ui.state.operationsFailure = false;
      await ui.tick();
      assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), true);
    };
    if (recoverBeforePostFailure) {
      await recover();
      assert.equal(submit.disabled, true, "connectivity alone must not clear an in-flight POST");
    }
    projectPost.reject(new Error("Fixture Project POST failed"));
    await submitting;
    if (!recoverBeforePostFailure) {
      assert.equal(submit.disabled, true, "the unavailable control gate must still hold after POST failure");
      await recover();
    }
    assert.equal(submit.disabled, false, "completed POST failure and restored connectivity must allow retry");
    assert.equal(descendants(ui.get("composer")).find((node) => node.tag === "form"), form);
    assert.equal(name.value, "Project draft during connection loss");
    assert.match(text(form), /Project 创建失败|Fixture Project POST failed/);
  });
}

test("Requests confirmation recovers after its pending POST fails during read disconnection", async () => {
  const operationPost = deferred();
  const ui = await browser({ ready: true, restart: false, project: true,
    operationPost: operationPost.promise,
    requests: [{ id: "request_fixture", project_id: "project_fixture", title: "Fixture request",
      stage: "READY_FOR_DISCUSSION", next_action: "Start discussion",
      checkpoint_sha256: "a".repeat(64), scopes: [], documents: [] }] });
  await ui.navigate("requests");
  const remove = descendants(ui.get("detail"))
    .find((node) => node.tag === "button" && node.textContent === "删除需求");
  assert.ok(remove, "the actual Requirement detail must offer its delete confirmation");
  await remove.events.click();
  const dialog = ui.get("composer").children[0];
  const proceed = descendants(dialog)
    .find((node) => node.tag === "button" && node.textContent === "确认删除");
  assert.ok(proceed);
  const confirming = proceed.events.click();
  await settled();
  assert.equal(proceed.disabled, true);
  assert.equal(ui.requests.filter(({ url, method }) => url === "/api/v1/operations" && method === "POST").length, 1);
  ui.state.teamFailure = true;
  ui.state.operationsFailure = true;
  await ui.tick();
  assert.equal(proceed.disabled, true);
  operationPost.reject(new Error("Fixture confirmation POST failed"));
  await confirming;
  const stillGatedAfterPostFailure = proceed.disabled;
  ui.state.teamFailure = false;
  ui.state.operationsFailure = false;
  await ui.tick();
  assert.equal(vm.runInContext("canControlCurrentTeam()", ui.context), true);
  assert.equal(proceed.disabled, false, "a completed failed confirmation must become retryable after reconnect");
  assert.equal(stillGatedAfterPostFailure, true, "failed POST must not bypass the disconnected control gate");
  assert.equal(ui.get("composer").children[0], dialog);
  assert.match(text(dialog), /删除操作未被接受|操作失败/);
});
