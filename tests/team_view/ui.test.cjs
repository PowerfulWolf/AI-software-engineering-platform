// Small DOM contract harness: no browser automation, dependencies, network or real timers.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.events = {};
    this.dataset = {};
    this.textContent = "";
    this.className = "";
    this.classList = { toggle() {} };
  }
  append(...nodes) {
    this.children.push(...nodes);
  }
  replaceChildren(...nodes) {
    this.children = nodes;
  }
  addEventListener(key, fn) {
    this.events[key] = fn;
  }
  setAttribute() {}
  removeAttribute() {}
  scrollIntoView() {}
  focus() {}
  set innerHTML(value) {
    throw new Error("Unsafe HTML assignment: " + value);
  }
}
const text = (node) =>
  typeof node === "string"
    ? node
    : node.textContent + node.children.map(text).join(" ");
const descend = (node) => [
  node,
  ...node.children.filter((n) => typeof n !== "string").flatMap(descend),
];

test("team, multi-directory requests, detail, refresh preservation and stale errors", async () => {
  const nodes = new Map();
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, new Element("div"));
    return nodes.get(id);
  };
  const malicious = '<img src=x onerror="alert(1)">';
  const fixture = {
    schema_version: "v0.1",
    as_of: "2026-09-05T01:00:00Z",
    company_id: "company_fixture",
    company_name: "Fixture company",
    companies: [
      { id: "company_fixture", name: "Fixture company" },
      { id: "company_other", name: "Other company" },
    ],
    agents: [
      {
        id: "agent_coder",
        name: "实现",
        roles: ["coder"],
        enabled: true,
        max_parallel_assignments: 8,
        current_stage_delivery_ids: ["d1"],
        assigned_delivery_ids: ["d1", "d2"],
        history_delivery_ids: [],
      },
      {
        id: "agent_qa",
        name: "测试",
        roles: ["qa"],
        enabled: true,
        max_parallel_assignments: 8,
        current_stage_delivery_ids: [],
        assigned_delivery_ids: ["d1"],
        history_delivery_ids: [],
      },
      {
        id: "agent_reviewer",
        name: "评审",
        roles: ["reviewer"],
        enabled: true,
        max_parallel_assignments: 8,
        current_stage_delivery_ids: [],
        assigned_delivery_ids: ["d1"],
        history_delivery_ids: [],
      },
      {
        id: "agent_planner",
        name: "规划",
        roles: ["planner"],
        enabled: true,
        max_parallel_assignments: 8,
        current_stage_delivery_ids: [],
        assigned_delivery_ids: [],
        history_delivery_ids: [],
      },
    ],
    requests: [
      {
        id: "r1",
        title: malicious,
        stage: "DELIVERING",
        next_action: "Continue",
        checkpoint_sha256: "a".repeat(64),
        scopes: [
          { root: "/backend", selected_paths: ["module-a"], delivery_id: "d1" },
          { root: "/frontend", selected_paths: ["."], delivery_id: "d2" },
        ],
        documents: [],
      },
    ],
    tasks: ["d1", "d2"].map((id, i) => ({
      id,
      request_id: "r1",
      title: malicious,
      status: i ? "NEW" : "IMPLEMENTING",
      terminal: false,
      scope: {
        root: i ? "/frontend" : "/backend",
        selected_paths: i ? ["."] : ["module-a"],
      },
      last_activity: "2026-09-05T01:00:00Z",
      next_action: "Continue",
      assignments: [
        {
          agent_id: "agent_coder",
          role: "coder",
          planned_provider: "codex",
          planned_model: "gpt-5.5",
          current_stage: !i,
        },
        ...(i
          ? []
          : [
              {
                agent_id: "agent_qa",
                role: "qa",
                planned_provider: "codex",
                planned_model: "gpt-5.5",
                current_stage: false,
              },
              {
                agent_id: "agent_reviewer",
                role: "reviewer",
                planned_provider: "codex",
                planned_model: "gpt-5.5",
                current_stage: false,
              },
            ]),
      ],
      timeline: [],
      runs: [
        {
          role: "coder",
          provider: "codex",
          model: "gpt-5.5",
          route_index: 1,
          outcome: "FALLBACK",
          error_code: "RATE_LIMITED",
          duration_ms: 1000,
          completed_at: "2026-09-05T01:00:00Z",
          source_uri: "model-route://run_test/1",
        },
        {
          role: "coder",
          provider: "deepseek",
          model: "test-fallback-model",
          route_index: 2,
          outcome: "SUCCEEDED",
          duration_ms: 2500,
          completed_at: "2026-09-05T01:00:03Z",
          source_uri: "model-route://run_test/2",
        },
      ],
      documents: [
        {
          name: "plan",
          source_uri: "artifact://art_test",
          sha256: "a".repeat(64),
          content: malicious,
        },
      ],
    })),
  };
  fixture.tasks.push(
    {
      ...structuredClone(fixture.tasks[1]),
      id: "d3",
      status: "BLOCKED",
      terminal: true,
      blocker: "等待人工处理",
      assignments: [],
    },
    {
      ...structuredClone(fixture.tasks[1]),
      id: "d4",
      status: "DONE",
      terminal: true,
      assignments: [],
    },
  );
  let failure = false,
    interval = null,
    urls = [],
    submittedIntents = [],
    storedOperations = [];
  const settingsFixture = {
    config: {
      schema_version: "v0.1",
      platform_root: "/data/ase",
      company_id: "company_fixture",
      company_name: "Fixture company",
      company_knowledge_paths: [
        "documents/knowledge_document_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/content.md",
      ],
      database: { backend: "mysql", dsn_env: "ASE_MYSQL_DSN" },
      model_routes: [
        {
          provider: "codex",
          model: "gpt-5.6-terra",
          kind: "codex_cli",
          endpoint: null,
          api_key_env: null,
          reasoning_effort: "high",
          enabled: true,
        },
      ],
      codex_executable: "codex",
      live_model_execution: true,
      console_port: 8765,
    },
    config_path: "/config/production.json",
    secret_status: [
      { environment_name: "ASE_MYSQL_DSN", configured: true },
    ],
    restart_required: false,
  };
  const knowledgeFixture = [
    {
      selected: true,
      manifest: {
        schema_version: "v0.1",
        document_id:
          "knowledge_document_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        company_id: "company_fixture",
        source_name: "team-guide.md",
        media_type: "text/markdown",
        source_relative_path: "source.md",
        normalized_relative_path:
          "documents/knowledge_document_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/content.md",
        source_bytes: 42,
        normalized_bytes: 42,
        source_sha256: "a".repeat(64),
        normalized_sha256: "b".repeat(64),
        imported_at: "2026-09-12T01:00:00Z",
        manifest_sha256: "c".repeat(64),
      },
    },
  ];
  const context = vm.createContext({
    document: {
      getElementById: get,
      createElement: (tag) => new Element(tag),
      createTextNode: (t) => t,
      querySelectorAll: (selector) =>
        [...nodes.values()]
          .flatMap(descend)
          .filter(
            (n) =>
              n.tag === "details" && (selector !== "details[open]" || n.open),
          ),
    },
    fetch: async (url, options = {}) => {
      urls.push(url);
      if (url === "/api/v1/admin/companies")
        return {
          ok: true,
          json: async () => structuredClone(fixture.companies).map((item) => ({
            company_id: item.id,
            name: item.name,
            active: item.id === "company_fixture",
            created_at: "2026-09-12T00:00:00Z",
          })),
        };
      if (url === "/api/v1/admin/settings")
        return { ok: true, json: async () => structuredClone(settingsFixture) };
      if (String(url).includes("/api/v1/admin/companies/company_fixture/knowledge"))
        return { ok: true, json: async () => structuredClone(knowledgeFixture) };
      if (url === "/api/v1/console")
        return {
          ok: true,
          json: async () => ({
            schema_version: "v0.1",
            company_id: "company_fixture",
          }),
        };
      if (url === "/api/v1/operations" && options.method === "POST") {
        const command = JSON.parse(options.body);
        submittedIntents.push(command.intent);
        const operation = {
          operation_id: `operation_${String(storedOperations.length + 1).padStart(32, "0")}`,
          company_id: "company_fixture",
          idempotency_key: command.idempotency_key,
          intent: command.intent,
          status: "QUEUED",
          requested_at: "2026-09-05T01:00:04Z",
          updated_at: "2026-09-05T01:00:04Z",
        };
        storedOperations.push(operation);
        return { ok: true, json: async () => structuredClone(operation) };
      }
      if (url === "/api/v1/operations")
        return {
          ok: true,
          json: async () => structuredClone(storedOperations),
        };
      return {
        ok: !failure,
        json: async () => structuredClone(fixture),
      };
    },
    setTimeout: () => 1,
    clearTimeout: () => {},
    setInterval: (fn, ms) => {
      interval = { fn, ms };
    },
    AbortController,
    structuredClone,
  });
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"),
      "utf8",
    ),
    context,
  );
  await new Promise(setImmediate);
  assert.equal(interval.ms, 5000);
  assert.match(text(get("content")), /2 项未结束分配/);
  assert.match(text(get("content")), /\/backend\/module-a/);
  assert.match(text(get("content")), /\/frontend/);
  assert.ok(text(get("content")).includes(malicious));
  const agentCards = get("content").children.filter(
    (node) => node.className === "agent",
  );
  assert.match(text(agentCards[0]), /实现中/);
  assert.doesNotMatch(text(agentCards[1]), /实现中/);
  assert.match(text(agentCards[1]), /等待测试阶段/);
  assert.doesNotMatch(text(agentCards[2]), /实现中/);
  assert.match(text(agentCards[2]), /等待评审阶段/);
  assert.match(text(agentCards[3]), /空闲中/);
  const companyTabs = get("companies").children;
  assert.equal(companyTabs.length, 2);
  await companyTabs[1].events.click();
  assert.ok(urls.includes("/api/v1/team/company_other"));
  await get("nav-knowledge").events.click();
  assert.match(text(get("content")), /team-guide.md/);
  assert.match(text(get("content")), /已用于新需求/);
  await get("nav-settings").events.click();
  assert.match(text(get("content")), /接入新公司/);
  assert.match(text(get("content")), /平台数据目录/);
  assert.ok(descend(get("content")).some((node) => node.value === "gpt-5.6-terra"));
  assert.match(text(get("content")), /ASE_MYSQL_DSN · 已提供/);
  await get("nav-team").events.click();
  fixture.tasks[0].status = "QA";
  fixture.tasks[0].assignments[0].current_stage = false;
  fixture.tasks[0].assignments[1].current_stage = true;
  fixture.agents[0].current_stage_delivery_ids = [];
  fixture.agents[1].current_stage_delivery_ids = ["d1"];
  await interval.fn();
  const qaStageCards = get("content").children.filter(
    (node) => node.className === "agent",
  );
  assert.match(text(qaStageCards[0]), /本轮已完成/);
  assert.doesNotMatch(text(qaStageCards[0]), /测试中/);
  assert.match(text(qaStageCards[1]), /测试中/);
  assert.match(text(qaStageCards[2]), /等待评审阶段/);
  get("nav-requests").events.click();
  assert.equal(get("new-request").hidden, false);
  assert.match(text(get("content")), /执行中 2/);
  assert.match(text(get("content")), /阻塞中 1/);
  assert.match(text(get("content")), /已完成 1/);
  get("new-request").events.click();
  const projectForm = descend(get("composer")).find(
    (node) => node.className === "project-form",
  );
  const projectName = descend(projectForm).find((node) => node.tag === "input");
  const projectRoots = descend(projectForm).find(
    (node) => node.tag === "textarea",
  );
  projectName.value = "跨仓登录升级";
  projectRoots.value = "/backend/module-a\n/frontend";
  await projectForm.events.submit({ preventDefault() {} });
  assert.deepEqual(submittedIntents[0], {
    action: "CREATE_REQUIREMENT_PROJECT",
    name: "跨仓登录升级",
    project_roots: ["/backend/module-a", "/frontend"],
  });
  assert.match(text(get("operations")), /等待 Project Manager/);
  vm.runInContext('showDetail("request","r1")', context);
  const continueButton = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "继续交付",
  );
  await continueButton.events.click();
  assert.deepEqual(submittedIntents[1], {
    action: "CONTINUE_DELIVERY",
    delivery_id: "r1",
    expected_checkpoint_sha256: "a".repeat(64),
  });
  assert.doesNotMatch(text(get("detail")), /a{64}/);

  const planSha = "b".repeat(64);
  storedOperations[1].status = "SUCCEEDED";
  storedOperations[1].updated_at = "2026-09-05T01:00:05Z";
  storedOperations[1].result = {
    delivery_id: "r1",
    checkpoint_sha256: "a".repeat(64),
    stage: "WAITING_HUMAN",
    next_action: "Approve exact recovery",
    approval: {
      kind: "coder_recovery",
      plan_sha256: planSha,
      title: "批准 Coder 恢复任务",
      facts: ["保留改动 2 个文件"],
    },
  };
  fixture.requests[0].stage = "WAITING_HUMAN";
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  const approvePlan = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "批准并继续",
  );
  assert.ok(approvePlan, "WAITING_HUMAN renders its exact recovery approval");
  assert.doesNotMatch(text(get("detail")), /b{64}/);
  await approvePlan.events.click();
  assert.deepEqual(submittedIntents[2], {
    action: "CONTINUE_DELIVERY",
    delivery_id: "r1",
    expected_checkpoint_sha256: "a".repeat(64),
    approved_plan_sha256: planSha,
  });

  storedOperations[2].status = "FAILED";
  storedOperations[2].updated_at = "2026-09-05T01:00:06Z";
  storedOperations[2].error_summary = "Provider unavailable";
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  assert.ok(
    descend(get("detail")).find(
      (node) => node.tag === "button" && node.textContent === "继续交付",
    ),
    "a consumed exact plan is not offered again; unified continue can propose the next plan",
  );
  assert.doesNotMatch(text(get("detail")), /批准并继续/);

  vm.runInContext('showDetail("task","d1")', context);
  assert.match(text(get("detail")), /任务详情/);
  assert.match(text(get("detail")), /codex \/ gpt-5.5/);
  assert.match(text(get("detail")), /deepseek \/ test-fallback-model/);
  assert.match(text(get("detail")), /RATE_LIMITED/);
  assert.match(text(get("detail")), /2.5 秒/);
  assert.ok(text(get("detail")).includes(malicious));
  const details = descend(get("detail")).find((n) => n.tag === "details");
  details.open = true;
  await interval.fn();
  assert.equal(
    descend(get("detail")).find((n) => n.tag === "details"),
    details,
    "unchanged poll does not replace reader's open document",
  );
  fixture.tasks[0].status = "QA";
  await interval.fn();
  assert.match(text(get("detail")), /测试中/);
  assert.equal(
    descend(get("detail")).find((n) => n.tag === "details").open,
    true,
  );
  failure = true;
  await interval.fn();
  assert.match(get("connection").textContent, /旧数据/);
  assert.match(text(get("detail")), /测试中/);
  failure = false;
  await interval.fn();
  assert.equal(get("connection").className, "");
});
