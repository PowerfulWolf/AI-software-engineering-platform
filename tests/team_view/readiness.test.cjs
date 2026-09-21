// Independent QA regression harness: execute the shipped script with fake HTTP and timers.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    Object.assign(this, { tag, children: [], events: {}, attributes: {}, dataset: {},
      textContent: "", className: "", value: "", hidden: false, checked: false });
    this.classList = { toggle() {} };
  }
  append(...nodes) { for (const node of nodes) if (typeof node !== "string") node.parentElement = this; this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, callback) { this.events[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(node => node !== this); }
  removeAttribute(name) { delete this.attributes[name]; }
  querySelectorAll(selector) {
    return descendants(this).slice(1).filter((node) => matchesSelector(node, selector));
  }
  focus() {}
  scrollIntoView() {}
  set innerHTML(value) { throw new Error("Unsafe HTML: " + value); }
}
const text = (node) => typeof node === "string"
  ? node : node.textContent + node.children.map(text).join(" ");
const descendants = (node) => [node, ...node.children
  .filter((child) => typeof child !== "string").flatMap(descendants)];
const matchesSelector = (node, selector) => selector.split(",").some((part) => {
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
  let reject;
  const promise = new Promise((_, rejectPromise) => { reject = rejectPromise; });
  return { promise, reject };
};
const successMessage = "配置已应用，Web Console 已使用保存的运行配置重新启动。";

async function browser(options = {}) {
  const nodes = new Map(), timers = new Map(), storage = new Map(), requests = [];
  let timerId = 0, poll;
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, new Element("div"));
    return nodes.get(id);
  };
  const state = {
    ready: options.ready ?? false,
    restart: options.restart ?? true,
    teamFailure: options.teamFailure ?? false,
    consoleFailure: false,
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
    projects: options.project ? [{ id: "project_fixture", name: "Fixture project" }] : [],
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
        if (state.teamFailure) throw new Error("Team projection unavailable");
        return response(team);
      }
      if (url === "/api/v1/console") {
        if (state.consoleFailure) throw new Error("Console offline");
        return response({ schema_version: "v0.2", team_id: config.team_id,
          delivery_ready: state.ready });
      }
      if (url === "/api/v1/operations") {
        if (request.method === "POST" && options.operationPost)
          return await options.operationPost;
        if (state.operationsFailure) throw new Error("Operations unavailable");
        return response([]);
      }
      if (url === "/api/v1/admin/settings") return response({ config,
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
