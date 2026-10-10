const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");
const { supportedActions } = require("./console-capabilities-fixture.cjs");

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
  querySelector(selector) {
    return selector.startsWith(".") ? all(this).slice(1).find(node =>
      node.className.split(/\s+/).includes(selector.slice(1))) || null : null;
  }
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
    document: { getElementById: get, createElement: tag => new Element(tag), createTextNode: s => s,
      querySelectorAll: selector => selector === '[data-delivery-control="true"]'
        ? [...new Set([...nodes.values()].flatMap(all))].filter(node => node.attributes["data-delivery-control"] === "true") : [] },
    fetch: fetcher, crypto: webcrypto, TextEncoder, setTimeout: () => 0, clearTimeout() {},
    AbortController, structuredClone, supportedActions,
  });
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.replace(/\nrefresh\(\);\nsetInterval\(refresh, 5000\);\s*$/, "\n"), context);
  vm.runInContext(`
    snapshot = {team_id: "team_test", selected_project_id: "project_test", requests: [{id: "r1", project_id: "project_test", title: "Requirement", stage: "WAITING_HUMAN", checkpoint_sha256: "checkpoint-a", scopes: [], documents: [], dialogue: []}], tasks: [], agents: [], projects: []};
    selected = {kind: "request", id: "r1"}; page = "requests";
    consoleAvailable = true; consoleDeliveryReady = true; operationsAvailable = true; consoleTeamId = "team_test";
    consoleOperationContractVersion = 1; consoleSupportedActions = [...supportedActions];
    renderDetail();
  `, context);
  return { context, get, detail: () => get("detail"), render: () => vm.runInContext("renderDetail()", context) };
}
const gap = {gap_id: "gap-a", question: "请确认范围 <script>not executable</script>", required_decision: "Provide verified facts and approve the exact resolution."};
const pending = {gap, is_current: true};
const resolution = {gap_id: gap.gap_id, resolution_id: "resolution-a", answer: "A", sources: [{uri: "产品确认", content: "A"}]};
const approved = {...pending, resolution};
const findButton = (h, label) => all(h.detail()).find(n => n.tag === "button" && n.textContent === label);

test("Planner rejection guidance distinguishes coverage, legacy validation and provider failures", () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  for (const [code, expected] of [
    ["PLANNER_TEST_MATRIX_REJECTED", /测试覆盖.*不符合设计/],
    ["COMMAND_REJECTED", /平台校验未通过/],
    ["MODEL_INVALID_OUTPUT", /输出格式未通过校验/],
    ["MODEL_PROVIDER_UNAVAILABLE", /模型服务/],
    ["UNKNOWN", /检查失败记录/],
  ]) {
    h.context.code = code;
    vm.runInContext(`
      snapshot.requests[0].stage = "PLANNING";
      operations = [{operation_id: "op", status: "FAILED", error_code: code,
        error_summary: "fixture rejection", intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1"}}];
      renderDetail();
    `, h.context);
    assert.match(text(h.detail()), expected, code);
    assert.ok(findButton(h, "重试 Planner"), code);
    if (code !== "MODEL_PROVIDER_UNAVAILABLE") assert.doesNotMatch(text(h.detail()), /修复模型服务/);
  }
  vm.runInContext(`
    snapshot.requests[0].stage_budget = {exhausted: true, role: "planner",
      attempts: 3, max_attempts: 3, transient_failures: 0, max_transient_failures: 5};
    renderDetail();
  `, h.context);
  assert.equal(findButton(h, "重试 Planner"), undefined);
  assert.match(text(h.detail()), /提高对应预算/);
  vm.runInContext(`
    snapshot.requests[0].stage_budget.exhausted = false;
    operations[0].status = "RUNNING"; renderDetail();
  `, h.context);
  assert.equal(findButton(h, "重试 Planner"), undefined);
});

test("local execution limit shows geometric window and prevents a futile retry", () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  vm.runInContext(`
    snapshot.requests[0].stage = "PLANNING";
    snapshot.requests[0].stage_budget = {role: "planner", attempts: 0, max_attempts: 3,
      transient_failures: 0, max_transient_failures: 5, capacity_timeouts: 2,
      max_capacity_timeouts: 3, next_timeout_seconds: 2400};
    operations = [{operation_id: "op", status: "FAILED", error_code: "MODEL_EXECUTION_LIMIT",
      error_summary: "local execution limit", intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1"}}];
    renderDetail();
  `, h.context);
  assert.match(text(h.detail()), /本地执行触顶 2\/3.*当前可用执行窗口 2400 秒/);
  assert.ok(findButton(h, "重试 Planner"));
  vm.runInContext(`
    snapshot.requests[0].stage_budget.capacity_timeouts = 3;
    snapshot.requests[0].stage_budget.next_timeout_seconds = null;
    snapshot.requests[0].stage_budget.exhausted = "capacity";
    renderDetail();
  `, h.context);
  assert.match(text(h.detail()), /本地执行触顶 3\/3.*已达上限/);
  assert.equal(findButton(h, "重试 Planner"), undefined);
  assert.match(text(h.detail()), /当前无法直接继续/);
  vm.runInContext(`
    snapshot.requests[0].stage = "DESIGNING";
    snapshot.requests[0].design_recovery_available = true;
    renderDetail();
  `, h.context);
  assert.equal(findButton(h, "恢复设计"), undefined);
});

test("knowledge waits retain their durable origin instead of falling back to Product", () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  for (const [origin, label] of [["DESIGNING", "设计"], ["PLANNING", "计划"], [null, null]]) {
    h.context.origin = origin;
    const flow = vm.runInContext("deliveryFlow({...snapshot.requests[0], knowledge_wait_stage: origin})", h.context);
    const blocked = all(flow).find(n => n.tag === "li" && n.className === "blocked");
    assert.equal(blocked ? blocked.children[1].textContent : null, label);
    assert.equal(all(flow).some(n => n.tag === "li" && n.className === "current"), false);
  }
});

test("blocked delivery flow highlights the durable failed stage", () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  const flow = vm.runInContext(
    'deliveryFlow({...snapshot.requests[0], stage: "BLOCKED", failed_stages: ["PLANNING"]})',
    h.context,
  );
  const steps = all(flow).filter((node) => node.tag === "li");
  assert.deepEqual(
    steps.map((node) => node.className),
    ["done", "done", "blocked", "", "", "", ""],
  );
  assert.match(text(steps[2]), /3.*计划.*已阻塞/);
  assert.equal(steps[2].attributes.title, "计划：阻塞");
  const dispatchFlow = vm.runInContext(
    'deliveryFlow({...snapshot.requests[0], stage: "BLOCKED", failed_stages: ["DISPATCHING"]})',
    h.context,
  );
  assert.equal(
    all(dispatchFlow).filter((node) => node.tag === "li")[2].className,
    "blocked",
  );
  const deliveryFlowWithoutRoleQueue = vm.runInContext(
    'deliveryFlow({...snapshot.requests[0], stage: "BLOCKED", failed_stages: ["DELIVERING"]})',
    h.context,
  );
  assert.equal(
    all(deliveryFlowWithoutRoleQueue).filter((node) => node.tag === "li")[3].className,
    "blocked",
  );
});

test("blocked delivery flow uses a visible warning treatment", () => {
  const styles = fs.readFileSync(
    path.join(__dirname, "../../src/ai_software_engineer/team_view/style.css"),
    "utf8",
  );
  assert.match(styles, /\.delivery-flow li\.blocked\s*\{[^}]*color:\s*#c62828;/s);
  assert.match(
    styles,
    /\.delivery-flow li\.blocked span\s*\{[^}]*background:\s*#c62828;/s,
  );
});

test("blocked delivery flow exposes Manager coordination state without adding a fake gate", () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  const manager = vm.runInContext(
    'managerFlowStatus({...snapshot.requests[0], stage: "BLOCKED", failed_stages: ["PLANNING"]})',
    h.context,
  );
  assert.match(text(manager), /Manager 协调.*等待恢复/);
  assert.equal(manager.className, "flow-manager blocked");
});

test("design recheck requires confirmation and sends only the exact checkpoint intent", async () => {
  const sent = [];
  const h = harness(async (url, options = {}) => {
    sent.push(JSON.parse(options.body).intent);
    return {ok: true, json: async () => ({operation_id: "op-recheck", status: "QUEUED", intent: sent.at(-1)})};
  });
  vm.runInContext(`
    snapshot.requests[0].design_recheck_available = true;
    snapshot.requests[0].knowledge_wait_stage = "PLANNING";
    confirmMutation = (title, message, label, action) => { globalThis.confirmation = message; return action(); };
    renderDetail();
  `, h.context);
  await findButton(h, "重新核对设计").events.click();
  assert.match(h.context.confirmation, /不批准.*不重置预算.*不会立即调用模型/);
  assert.deepEqual(sent, [{action: "RECHECK_DESIGN", project_id: "project_test", delivery_id: "r1", expected_checkpoint_sha256: "checkpoint-a"}]);
  assert.equal(findButton(h, "重新核对设计"), undefined);
});

test("rechecked history is not approved and an idle handoff exposes Continue after reload", async () => {
  const h = harness(async () => ({ok: true, json: async () => [{...pending, is_current: false}]}));
  vm.runInContext(`
    snapshot.requests[0].stage = "DESIGNING";
    snapshot.requests[0].checkpoint_sha256 = "checkpoint-b";
    snapshot.requests[0].knowledge_rechecked_gap_ids = ["gap-a"];
    snapshot.requests[0].design_recheck_pending = true;
    renderDetail();
  `, h.context);
  assert.ok(findButton(h, "继续交付"));
  await findButton(h, "查看知识核对记录").events.click();
  assert.match(text(h.detail()), /已交回设计核对 · 非批准/);
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 0);
  vm.runInContext('operations = [{operation_id: "op", status: "RUNNING", intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1"}}]; renderDetail()', h.context);
  assert.equal(findButton(h, "继续交付"), undefined);
});

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

test("stale Team pauses knowledge approval while keeping the readable question and editable draft", async () => {
  for (const issue of ["busy", "unavailable", "timeout"]) {
    const writes = [];
    const h = harness(async (_url, options = {}) => {
      if (options.method === "POST") {writes.push(JSON.parse(options.body)); return {ok: true, json: async () => resolution};}
      return {ok: true, json: async () => [pending]};
    });
    await findButton(h, "查看待确认的知识").events.click();
    const form = all(h.detail()).find(node => node.tag === "form");
    const answer = all(form).find(node => node.tag === "textarea");
    const source = all(form).find(node => node.tag === "input");
    const submit = all(form).find(node => node.tag === "button" && node.type === "submit");
    answer.value = "保留的产品决定"; source.value = "产品负责人确认";
    h.context.failure = issue;
    vm.runInContext("teamReadIssue = failure; renderDetail(); syncDeliveryControls();", h.context);
    await form.events.submit({preventDefault() {}});
    assert.equal(writes.length, 0, issue + " retained knowledge form must not POST");
    assert.equal(submit.disabled, true);
    assert.equal(all(h.detail()).find(node => node.tag === "form"), form);
    assert.equal(answer.value, "保留的产品决定");
    assert.equal(source.value, "产品负责人确认");
    assert.match(text(h.detail()), /请确认范围/);
    assert.match(text(form), /当前操作已暂停|最新的团队数据/);
    assert.equal(findButton(h, "收起知识详情").disabled, false, "reading remains available");
    vm.runInContext("teamReadIssue = null; renderDetail(); syncDeliveryControls();", h.context);
    assert.equal(submit.disabled, false);
    assert.equal(all(h.detail()).find(node => node.tag === "form"), form);
    await form.events.submit({preventDefault() {}});
    assert.equal(writes.length, 1, "fresh current facts restore explicit approval without a new draft");
    assert.equal(writes[0].answer, "保留的产品决定");
  }
});

test("retained knowledge approval checks the frozen Project, checkpoint and exact unresolved gap", async () => {
  for (const mutation of [
    'snapshot.selected_project_id = "other_project"',
    'snapshot.requests[0].checkpoint_sha256 = "checkpoint-new"',
    'snapshot.requests[0].stage = "PLANNING"',
    'snapshot.requests[0].knowledge_gap.gap.gap_id = "new-gap"',
    'snapshot.requests[0].knowledge_gap.gap.question = "changed question with the same claimed digest"',
    'snapshot.requests[0].knowledge_gap.is_current = false',
    'snapshot.requests[0].knowledge_gap.resolution = {resolution_id: "already-approved"}',
    'snapshot.requests = []',
    'operationsAvailable = false',
  ]) {
    let writes = 0;
    const h = harness(async (_url, options = {}) => {
      if (options.method === "POST") {writes++; return {ok: true, json: async () => resolution};}
      return {ok: true, json: async () => structuredClone([pending])};
    });
    await findButton(h, "查看待确认的知识").events.click();
    const form = all(h.detail()).find(node => node.tag === "form");
    all(form).find(node => node.tag === "textarea").value = "已确认";
    all(form).find(node => node.tag === "input").value = "产品决定";
    assert.equal(vm.runInContext("snapshot.requests[0].knowledge_gap.gap.gap_id", h.context), gap.gap_id,
      "the verified pending detail supplies the exact current binding");
    vm.runInContext(mutation, h.context);
    await form.events.submit({preventDefault() {}});
    assert.equal(writes, 0, mutation + " cannot authorize the retained form");
  }
});

test("knowledge approval rechecks Team authority after asynchronous answer hashing", async () => {
  for (const mutation of [
    'teamReadIssue = "busy"',
    'snapshot.requests[0].checkpoint_sha256 = "checkpoint-new"',
    'snapshot.requests[0].knowledge_gap.resolution = {resolution_id: "already-approved"}',
  ]) {
    let writes = 0, release;
    const h = harness(async (_url, options = {}) => {
      if (options.method === "POST") {writes++; return {ok: true, json: async () => resolution};}
      return {ok: true, json: async () => structuredClone([pending])};
    });
    await findButton(h, "查看待确认的知识").events.click();
    const form = all(h.detail()).find(node => node.tag === "form");
    all(form).find(node => node.tag === "textarea").value = "决定在异步边界期间保留";
    all(form).find(node => node.tag === "input").value = "产品决定";
    const hashPending = new Promise(resolve => {release = resolve;});
    h.context.crypto = {subtle: {digest: () => hashPending}};
    const submitting = form.events.submit({preventDefault() {}});
    vm.runInContext(mutation + '; syncDeliveryControls()', h.context);
    release(new Uint8Array(32).buffer);
    await submitting;
    assert.equal(writes, 0, mutation + " during hashing must revoke the already-started callback");
    assert.equal(all(form).find(node => node.tag === "button" && node.type === "submit").disabled, true);
    assert.equal(all(form).find(node => node.tag === "textarea").value, "决定在异步边界期间保留");
  }
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
  for (const region of [".request-detail-overview", ".request-blocking-section", ".knowledge-gap-section"]) {
    const current = h.detail().querySelector(region);
    assert.ok(current, region);
    assert.doesNotMatch(text(current), /Resolve and approve|需要你的确认/, region);
  }
  assert.match(text(h.detail().querySelector(".execution-history")), /Resolve and approve knowledge gap gap-a before resuming/);
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

test("in-progress delivery stages do not expose a continuation action", () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  for (const stage of ["DESIGNING", "PLANNING", "DISPATCHING", "DELIVERING", "INTEGRATING", "CLOSED"]) {
    vm.runInContext(`
      snapshot.requests[0] = {
        ...snapshot.requests[0],
        stage: ${JSON.stringify(stage)},
        next_action: "当前阶段仍在运行。",
      };
      renderDetail();
    `, h.context);
    assert.equal(findButton(h, "继续交付"), undefined, `${stage} must not offer recovery`);
  }
  assert.match(text(h.detail()), /当前阶段仍在运行/);
});

test("failed Design exposes an exact-checkpoint retry, but a running retry hides it", async () => {
  const submitted = [];
  const h = harness(async (url, options = {}) => {
    if (options.method) {
      submitted.push(JSON.parse(options.body).intent);
      return {
        ok: true,
        json: async () => ({
          operation_id: "op-retry",
          status: "QUEUED",
          updated_at: "2026-09-22",
          intent: submitted.at(-1),
        }),
      };
    }
    return {ok: true, json: async () => []};
  });
  vm.runInContext(`
    snapshot.requests[0] = {
      ...snapshot.requests[0],
      stage: "DESIGNING",
      next_action: "Designer 操作失败后可重试。",
    };
    operations = [{
      operation_id: "op-failed",
      status: "FAILED",
      error_summary: "MODEL_PROVIDER_UNAVAILABLE",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1", project_id: "project_test"},
      updated_at: "2026-09-21",
    }];
    renderDetail(); renderOperationStatus();
  `, h.context);
  assert.equal(findButton(h, "继续交付"), undefined);
  assert.ok(findButton(h, "重试 Design"));
  await findButton(h, "重试 Design").events.click();
  assert.deepEqual(submitted, [{
    action: "CONTINUE_DELIVERY",
    project_id: "project_test",
    delivery_id: "r1",
    expected_checkpoint_sha256: "checkpoint-a",
  }]);
  vm.runInContext(`
    operations = [{
      operation_id: "op-retry",
      status: "RUNNING",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1", project_id: "project_test"},
      updated_at: "2026-09-22",
    }];
    renderDetail();
  `, h.context);
  assert.equal(findButton(h, "重试 Design"), undefined);
  assert.equal(findButton(h, "继续交付"), undefined);
});

test("interrupted approved upstream work continues the current stage with the current checkpoint", async () => {
  for (const [stage, previousAction, buttonLabel] of [
    ["DESIGNING", "PRODUCT_APPROVAL", "继续设计"],
    ["DESIGNING", "CONTINUE_DELIVERY", "继续设计"],
    ["PLANNING", "CONTINUE_DELIVERY", "继续计划"],
  ]) {
    const submitted = [];
    const h = harness(async (_url, options = {}) => {
      if (options.method) submitted.push(JSON.parse(options.body).intent);
      return {ok: true, json: async () => options.method
        ? {operation_id: "continue-new", status: "QUEUED", updated_at: "2026-10-05T12:34:00Z", intent: submitted.at(-1)} : []};
    });
    h.context.stage = stage; h.context.previousAction = previousAction;
    vm.runInContext(`
      snapshot.requests[0].stage = stage; snapshot.requests[0].checkpoint_sha256 = "checkpoint-after-attempt";
      snapshot.requests[0].execution = {state: "UNKNOWN", responsibility: "engineering", reason: "尚无执行器心跳。", next_action: "核对状态。"};
      operations = [{operation_id: "original", status: "INTERRUPTED", result: null,
        error_code: "HOST_INTERRUPTED", error_summary: "The console host stopped before the operation completed.",
        updated_at: "2026-10-05T12:32:00Z", intent: {action: previousAction, project_id: "project_test", delivery_id: "r1",
          expected_checkpoint_sha256: "checkpoint-before-attempt"}}];
      renderDetail();
    `, h.context);
    assert.ok(findButton(h, buttonLabel), stage + " " + previousAction);
    const engineeringSections = all(h.detail()).filter(node => node.className.split(/\s+/).includes("engineering-details"));
    assert.equal(engineeringSections.some(node => all(node).includes(findButton(h, buttonLabel))), false,
      "normal stage continuation is visible without opening engineering controls");
    assert.equal(findButton(h, "批准 ProductSpec 并开始交付"), undefined);
    await findButton(h, buttonLabel).events.click();
    assert.deepEqual(submitted, [{action: "CONTINUE_DELIVERY", project_id: "project_test", delivery_id: "r1",
      expected_checkpoint_sha256: "checkpoint-after-attempt"}]);
  }
});

test("upstream continuation keeps budget, exact approval, source and execution gates", () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  vm.runInContext(`
    snapshot.requests[0].stage = "DESIGNING";
    snapshot.requests[0].execution = {state: "UNKNOWN", responsibility: "team", reason: "待核验", next_action: "待核验"};
    operations = []; renderDetail();
  `, h.context);
  assert.ok(findButton(h, "继续设计"), "an idle admitted stage can continue");
  assert.match(text(h.detail()), /待继续/);
  vm.runInContext(`operations = [{operation_id: "old", status: "INTERRUPTED", result: null,
    error_code: "HOST_INTERRUPTED", error_summary: "host stopped", updated_at: "2026-10-05T12:32:00Z",
    intent: {action: "PRODUCT_APPROVAL", delivery_id: "r1", project_id: "project_test"}}];`, h.context);
  const cases = [
    'snapshot.requests[0].stage_budget = {exhausted: "work", role: "designer", attempts: 3, max_attempts: 3}',
    'snapshot.requests[0].design_recovery_available = true',
    'snapshot.requests[0].execution.state = "WAITING"',
    'snapshot.requests[0].execution.reason_code = "EXECUTION_CLAIM_EXPIRED"',
    'operations[0].status = "RUNNING"',
    'operations[0].error_code = "SOURCE_REVISION_DRIFT"; operations[0].status = "FAILED"',
    'operations[0].intent.action = "CLOSE_REQUIREMENT"',
    'operations[0].intent.project_id = "other-project"',
    'operations.push({operation_id: "exact", status: "SUCCEEDED", updated_at: "2026-10-05T12:33:00Z", intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1", project_id: "project_test"}, result: {delivery_id: "r1", checkpoint_sha256: "checkpoint-a", approval: {kind: "coder_scope", title: "新增范围", plan_sha256: "exact", facts: [], risks: []}}})',
  ];
  for (const mutation of cases) {
    vm.runInContext(`snapshot.requests[0].stage_budget = null; snapshot.requests[0].design_recovery_available = false;
      snapshot.requests[0].execution.state = "UNKNOWN"; snapshot.requests[0].execution.reason_code = "EXECUTION_UNCONFIRMED";
      operations = [operations[0]]; operations[0].status = "INTERRUPTED"; operations[0].error_code = "HOST_INTERRUPTED";
      operations[0].intent.action = "PRODUCT_APPROVAL"; operations[0].intent.project_id = "project_test";
      ${mutation}; renderDetail();`, h.context);
    assert.equal(findButton(h, "继续设计"), undefined, mutation);
  }
});

test("failed initial Product approval retries the approved upstream stage without approving Product again", async () => {
  const submitted = [];
  const h = harness(async (_url, options = {}) => {
    if (options.method) submitted.push(JSON.parse(options.body).intent);
    return {ok: true, json: async () => options.method
      ? {operation_id: "retry", status: "QUEUED", updated_at: "2026-10-05T12:34:00Z", intent: submitted.at(-1)} : []};
  });
  vm.runInContext(`snapshot.requests[0].stage = "DESIGNING";
    operations = [{operation_id: "initial", status: "FAILED", result: null,
      error_code: "MODEL_PROVIDER_ERROR", error_summary: "provider unavailable", updated_at: "2026-10-05T12:32:00Z",
      intent: {action: "PRODUCT_APPROVAL", delivery_id: "r1", project_id: "project_test", expected_checkpoint_sha256: "old"}}];
    renderDetail();`, h.context);
  assert.ok(findButton(h, "重试 Design"));
  assert.equal(findButton(h, "批准 ProductSpec 并开始交付"), undefined);
  await findButton(h, "重试 Design").events.click();
  assert.deepEqual(submitted, [{action: "CONTINUE_DELIVERY", project_id: "project_test", delivery_id: "r1",
    expected_checkpoint_sha256: "checkpoint-a"}]);
});

test("exhausted Design recovery outranks a failed retry and submits the recovery intent", async () => {
  const submitted = [];
  const h = harness(async (_url, options = {}) => {
    if (options.method) submitted.push(JSON.parse(options.body).intent);
    return {ok: true, json: async () => ({operation_id: "op-recovery", status: "QUEUED",
      updated_at: "2026-09-22", intent: submitted.at(-1)})};
  });
  vm.runInContext(`
    snapshot.requests[0].stage = "DESIGNING";
    snapshot.requests[0].design_recovery_available = true;
    operations = [{operation_id: "op-failed", status: "FAILED", error_summary: "design budget exhausted",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1"}, updated_at: "2026-09-21"}];
    renderDetail();
  `, h.context);
  assert.equal(findButton(h, "重试 Design"), undefined);
  assert.equal(findButton(h, "继续交付"), undefined);
  assert.ok(findButton(h, "恢复设计"));
  assert.match(text(h.detail()), /设计待恢复/);
  await findButton(h, "恢复设计").events.click();
  assert.deepEqual(submitted, [{action: "RECOVER_DESIGN", project_id: "project_test",
    delivery_id: "r1", expected_checkpoint_sha256: "checkpoint-a"}]);
  assert.equal(findButton(h, "恢复设计"), undefined);
});

test("exhausted transient budget shows settings guidance without an impossible retry", () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  vm.runInContext(`
    snapshot.requests[0].stage = "DESIGNING";
    snapshot.requests[0].design_budget = {design_attempts: 1, max_design_attempts: 3,
      transient_failures: 5, max_transient_failures: 5, exhausted: "transient"};
    operations = [{operation_id: "op-failed", status: "FAILED", error_summary: "HTTP 504",
      intent: {action: "CONTINUE_DELIVERY", delivery_id: "r1"}, updated_at: "2026-09-21"}];
    renderDetail();
  `, h.context);
  assert.equal(findButton(h, "重试 Design"), undefined);
  assert.equal(findButton(h, "继续交付"), undefined);
  assert.match(text(h.detail()), /临时故障.*5.*5/);
  assert.match(text(h.detail()), /设置/);
  assert.match(text(h.detail()), /设计预算已用尽/);
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
  assert.equal(h.get("operations").hidden, true);
  assert.equal(h.get("notification").hidden, true, "project notices wait for a verified current Project");
  assert.doesNotMatch(text(h.get("notification")), /解答已批准/);
  assert.equal(all(h.get("notification")).some(
    n => n.tag === "button" && n.textContent === "打开需求工作区",
  ), false, "without a verified Team snapshot there is no navigable Requirement target");
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
  assert.ok(all(h.detail()).some(n => n.tag === "h3" && n.textContent === "已确认的知识"));
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

test("approved knowledge remains reachable after delivery resumes and completes", async () => {
  let reads = 0;
  const h = harness(async () => {
    reads++;
    return {ok: true, json: async () => [{...approved, is_current: false}]};
  });
  for (const stage of ["DELIVERING", "INTEGRATING", "DONE"]) {
    h.context.nextStage = stage;
    vm.runInContext("snapshot.requests[0].stage = nextStage; renderDetail()", h.context);
    const show = findButton(h, "查看知识核对记录");
    assert.ok(show, stage);
    await show.events.click();
    assert.match(text(h.detail()), /已回答的内容.*A/);
    assert.match(text(h.detail()), /resolution-a/);
    assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 0);
  }
  assert.equal(reads, 3);
});

test("same-checkpoint stage change discards an obsolete pending knowledge form", async () => {
  let records = [pending];
  const h = harness(async () => ({ok: true, json: async () => records}));
  await findButton(h, "查看待确认的知识").events.click();
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 1);
  records = [{...approved, is_current: false}];
  vm.runInContext('snapshot.requests[0].stage = "DELIVERING"; renderDetail()', h.context);
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 0);
  await findButton(h, "查看知识核对记录").events.click();
  assert.match(text(h.detail()), /已回答的内容/);
  assert.equal(all(h.detail()).filter(n => n.tag === "form").length, 0);
});

test("empty diagnostics distinguish valid role execution from completed call records", async () => {
  const h = harness(async () => ({ok: true, json: async () => []}));
  vm.runInContext(`
    snapshot.requests[0].scopes = [{delivery_id: "native-1"}];
    snapshot.tasks = [{id: "native-1", request_id: "r1", project_id: "project_test",
      status: "IMPLEMENTING", terminal: false, last_activity: "2026-10-01T14:09:00Z",
      role_queue: [{role: "coder", status: "RUNNING", lease_liveness: "LEASE_VALID",
        heartbeat_at: "2026-10-01T14:09:00Z"}]}];
  `, h.context);
  for (const [status, liveness, active] of [
    ["RUNNING", "LEASE_VALID", true], ["RUNNING", "LEASE_EXPIRED", false],
    ["CLOSED", "LEASE_VALID", false], ["WAITING_HUMAN", "UNKNOWN", false],
  ]) {
    Object.assign(h.context, {queueStatus: status, leaseLiveness: liveness});
    vm.runInContext(`snapshot.tasks[0].role_queue[0].status = queueStatus;
      snapshot.tasks[0].role_queue[0].lease_liveness = leaseLiveness;`, h.context);
    const details = vm.runInContext(`modelCallDiagnostics({operation_id: "op-running",
      status: "RUNNING", intent: {delivery_id: "r1", project_id: "project_test"}})`, h.context);
    details.open = true;
    await details.events.toggle();
    if (active) assert.match(text(details), /正在执行.*最近心跳/);
    else assert.doesNotMatch(text(details), /正在执行/);
    assert.match(text(details), /已完成.*阶段调用/);
    assert.match(text(details), /查看角色执行记录/);
    assert.doesNotMatch(text(details), /历史缺失记录无法补回/);
  }
  vm.runInContext(`snapshot.tasks[0].role_queue[0].status = "RUNNING";
    snapshot.tasks[0].role_queue[0].lease_liveness = "LEASE_VALID";`, h.context);
  const otherProject = vm.runInContext(`modelCallDiagnostics({operation_id: "op-foreign",
    status: "RUNNING", intent: {delivery_id: "r1", project_id: "project_other"}})`, h.context);
  otherProject.open = true;
  await otherProject.events.toggle();
  assert.doesNotMatch(text(otherProject), /正在执行|查看角色执行记录/);
  vm.runInContext('snapshot.tasks[0].terminal = true', h.context);
  assert.doesNotMatch(text(vm.runInContext('roleExecutionActivity(snapshot.tasks[0])', h.context)), /正在执行/);
  vm.runInContext('snapshot.tasks[0].terminal = false; snapshot.tasks[0].role_queue[0].role = "reviewer"', h.context);
  assert.doesNotMatch(text(vm.runInContext('roleExecutionActivity(snapshot.tasks[0])', h.context)), /正在执行/);
});

test("model call details present CLI results without HTTP placeholders", async () => {
  const h = harness(async () => ({ok: true, json: async () => [
    {route_index: 1, provider: "codex", model: "gpt-6-sol", reasoning_effort: "high", route_kind: "codex_cli", connection_mode: "proxy", phase: "stage_reply", role: "designer", outcome: "SUCCEEDED", duration_ms: 135590, http_status: null, request_id: null},
    {route_index: 2, provider: "codex", model: "backup", reasoning_effort: "high", route_kind: "responses", phase: "stage_reply", role: "designer", outcome: "FAILED", duration_ms: 1200, http_status: null, request_id: null},
  ]}));
  const details = vm.runInContext('modelCallDiagnostics({operation_id:"op-cli", status:"SUCCEEDED"})', h.context);
  details.open = true;
  await details.events.toggle();
  const cards = all(details).filter(node => node.className === "model-call-card");
  assert.match(text(cards[0]), /Codex CLI · CLIProxyAPI/);
  assert.match(text(cards[0]), /阶段回复 · 成功 · 135\.59 秒/);
  assert.doesNotMatch(text(cards[0]), /HTTP|请求编号|服务未提供/);
  assert.match(text(cards[1]), /未收到 HTTP 响应/);
});
