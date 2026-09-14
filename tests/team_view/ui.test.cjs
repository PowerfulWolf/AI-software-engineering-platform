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
    this.value = "";
    this.checked = false;
    this.hidden = false;
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

test("long Requirement identifiers cannot expand the master column", () => {
  const styles = fs.readFileSync(
    path.join(__dirname, "../../src/ai_software_engineer/team_view/style.css"),
    "utf8",
  );
  assert.match(
    styles,
    /\.request-list\s*\{[^}]*min-width:\s*0;/s,
    "the Requirement list must be allowed to shrink inside its grid column",
  );
  assert.match(
    styles,
    /\.request-list \.request\s*\{[^}]*min-width:\s*0;/s,
    "a Requirement card must not use its opaque ID as a minimum width",
  );
  assert.match(
    styles,
    /\.request-id\s*\{[^}]*overflow-wrap:\s*anywhere;/s,
    "opaque Requirement identifiers must wrap before crossing into detail",
  );
});

test("long selected directory paths cannot turn actions vertical", () => {
  const styles = fs.readFileSync(
    path.join(__dirname, "../../src/ai_software_engineer/team_view/style.css"),
    "utf8",
  );
  assert.match(
    styles,
    /\.directory-chip > button\s*\{[^}]*flex-shrink:\s*0;[^}]*white-space:\s*nowrap;/s,
    "the remove action must keep its readable horizontal width",
  );
});

test("team, multi-directory requests, detail, refresh preservation and stale errors", async () => {
  const nodes = new Map();
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, new Element("div"));
    return nodes.get(id);
  };
  const malicious = '<img src=x onerror="alert(1)">';
  const fixture = {
    schema_version: "v0.2",
    as_of: "2026-09-05T01:00:00Z",
    team_id: "team_fixture",
    team_name: "Fixture team",
    selected_project_id: "project_fixture",
    projects: [
      { id: "project_fixture", name: "Fixture project" },
      { id: "project_other", name: "Other project" },
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
        history_delivery_ids: ["d3", "d4"],
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
        project_id: "project_fixture",
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
      project_id: "project_fixture",
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
    deliveryReady = true,
    interval = null,
    urls = [],
    submittedIntents = [],
    storedOperations = [],
    createdProjects = [],
    savedSettings = [],
    mysqlTests = [],
    knowledgeSelections = [],
    knowledgeImports = [],
    knowledgeUpdates = [],
    knowledgeUpdateBodies = [],
    knowledgeContentReads = [],
    knowledgeDeletes = [],
    specActivations = [],
    createdSpecs = [],
    specDeletes = [],
    learningDecisions = [],
    screenshotUploads = [];
  const settingsFixture = {
    config: {
      schema_version: "v0.2",
      platform_root: "/data/ase",
      team_id: "team_fixture",
      team_name: "Fixture team",
      team_knowledge_paths: [
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
          image_input: null,
          enabled: true,
        },
        {
          provider: "deepseek",
          model: "deepseek-v4",
          kind: "responses",
          endpoint: "https://example.invalid/v1/responses",
          api_key_env: "DEEPSEEK_API_KEY",
          reasoning_effort: "high",
          image_input: true,
          enabled: false,
        },
      ],
      codex_executable: "codex",
      live_model_execution: true,
      console_port: 8765,
    },
    config_path: "/config/production.json",
    config_source: "saved",
    secret_status: [
      { environment_name: "ASE_MYSQL_DSN", configured: true },
      { environment_name: "DEEPSEEK_API_KEY", configured: false },
    ],
    restart_required: false,
  };
  const statusFixture = {
    config_path: "/config/production.json",
    config_source: "saved",
    runtime_environment_path: "/config/runtime.env",
    restart_required: false,
    delivery_runtime: "READY",
    live_model_execution: true,
    database: {
      environment_name: "ASE_MYSQL_DSN",
      configured: true,
      source: "runtime.env",
      connection: "CONNECTED",
    },
    codex: {
      executable: "codex",
      available: true,
      resolved_path: "/usr/local/bin/codex",
    },
    team_prepared: true,
    team_knowledge_imported: 1,
    team_knowledge_selected: 1,
    model_routes: [
      {
        provider: "codex",
        model: "gpt-5.6-terra",
        reasoning_effort: "high",
        kind: "codex_cli",
        enabled: true,
        ready: true,
      },
      {
        provider: "codex",
        model: "gpt-5.6-terra",
        reasoning_effort: "medium",
        kind: "codex_cli",
        enabled: true,
        ready: true,
      },
      {
        provider: "deepseek",
        model: "deepseek-v4",
        reasoning_effort: "high",
        kind: "responses",
        enabled: false,
        ready: true,
        credential_environment_name: "DEEPSEEK_API_KEY",
        credential_configured: false,
      },
    ],
    agent_model_routes: [
      "manager",
      "product",
      "designer",
      "planner",
      "coder",
      "qa",
      "reviewer",
    ].map((role) => ({
      role,
      policy_source: "agent_policy",
      routes: [
        {
          provider: "codex",
          model: "gpt-5.6-terra",
          reasoning_effort: role === "coder" ? "high" : "medium",
          kind: "codex_cli",
          enabled: true,
          ready: true,
        },
        {
          provider: "codex",
          model: "gpt-5.6-terra",
          reasoning_effort: role === "coder" ? "medium" : "high",
          kind: "codex_cli",
          enabled: true,
          ready: true,
        },
      ],
    })),
  };
  const knowledgeFixture = [
    {
      scope: "team",
      project_id: null,
      selected: true,
      manifest: {
        schema_version: "v0.1",
        document_id: "knowledge_document_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        team_id: "team_fixture",
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
  const projectKnowledgeFixture = [
    {
      ...structuredClone(knowledgeFixture[0]),
      scope: "project",
      project_id: "project_other",
      selected: false,
      manifest: {
        ...structuredClone(knowledgeFixture[0].manifest),
        project_id: "project_other",
        source_name: "project-guide.md",
      },
    },
  ];
  const projectSpecFixture = [
    {
      scope: "project",
      project_id: "project_other",
      active: false,
      document: {
        schema_version: "v0.1",
        spec_id: "spec_document_" + "d".repeat(32),
        scope: "project",
        team_id: "team_fixture",
        project_id: "project_other",
        spec_key: "python.testing",
        version: 1,
        title: "Python testing",
        body_markdown: "# Testing\n\nRun focused tests.",
        roles: ["coder", "qa", "reviewer"],
        stages: ["implementing", "qa", "review"],
        repository_ids: [],
        path_globs: ["*"],
        verification: "Record passing pytest evidence.",
        created_at: "2026-09-14T00:00:00Z",
        spec_sha256: "e".repeat(64),
      },
    },
  ];
  const learningFixture = [
    {
      proposal: {
        schema_version: "v0.1",
        proposal_id: "learning_proposal_" + "f".repeat(32),
        team_id: "team_fixture",
        project_id: "project_other",
        trigger: "QA_FAILURE",
        recurrence_key: "a".repeat(64),
        occurrence_count: 2,
        title: "Prevent recurrence: MISSING_REGRESSION",
        observation: "The edge case has no regression test.",
        proposed_improvement: "Require a regression test.",
        verification: "Record passing regression evidence.",
        suggested_target: "SPEC",
        evidence: [
          {
            repository_id: "repository_fixture",
            task_id: "task_fixture",
            artifact_id: "art_qa_fixture",
            artifact_sha256: "b".repeat(64),
            finding_id: "finding_regression",
            evidence_uris: ["evidence://qa"],
          },
        ],
        created_at: "2026-09-14T00:00:00Z",
        proposal_sha256: "c".repeat(64),
      },
      decision: null,
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
      if (url === "/api/v1/admin/directories/select")
        return {
          ok: true,
          json: async () => ({
            directories: ["/backend/module-a", "/frontend"],
            cancelled: false,
          }),
        };
      if (
        String(url).includes("/requirements/") &&
        String(url).includes("/screenshots?")
      ) {
        screenshotUploads.push({ url: String(url), body: options.body });
        return {
          ok: true,
          json: async () => ({
            id: "requirement_attachment_" + "e".repeat(40),
          }),
        };
      }
      if (url === "/api/v1/admin/projects" && options.method === "POST") {
        createdProjects.push(JSON.parse(options.body));
        return {
          ok: true,
          json: async () => ({
            project_id: "project_other",
            name: createdProjects.at(-1).name,
            repository_count: 0,
            requirement_count: 0,
            created_at: "2026-09-14T00:00:00Z",
          }),
        };
      }
      if (url === "/api/v1/admin/projects")
        return {
          ok: true,
          json: async () =>
            structuredClone(fixture.projects).map((item) => ({
              project_id: item.id,
              name: item.name,
              repository_count: 1,
              requirement_count: 1,
              created_at: "2026-09-12T00:00:00Z",
            })),
        };
      if (url === "/api/v1/admin/settings" && options.method === "PUT") {
        savedSettings.push(JSON.parse(options.body));
        return {
          ok: true,
          json: async () => ({
            ...structuredClone(settingsFixture),
            restart_required: true,
          }),
        };
      }
      if (url === "/api/v1/admin/settings")
        return { ok: true, json: async () => structuredClone(settingsFixture) };
      if (url === "/api/v1/admin/settings/test-mysql") {
        mysqlTests.push(JSON.parse(options.body));
        return {
          ok: true,
          json: async () => ({ connected: true, message: "MySQL 连接成功。" }),
        };
      }
      if (url === "/api/v1/admin/status")
        return { ok: true, json: async () => structuredClone(statusFixture) };
      if (url === "/api/v1/admin/team/knowledge")
        return {
          ok: true,
          json: async () => structuredClone(knowledgeFixture),
        };
      if (
        String(url).endsWith(
          "/knowledge_document_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/content",
        ) &&
        (!options.method || options.method === "GET")
      ) {
        knowledgeContentReads.push(String(url));
        return {
          ok: true,
          json: async () => ({
            scope: "project",
            project_id: "project_other",
            document_id: "knowledge_document_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            source_name: projectKnowledgeFixture[0].manifest.source_name,
            content_markdown: "# Existing project guide\n\nCurrent content.\n",
          }),
        };
      }
      if (
        String(url).startsWith(
          "/api/v1/admin/projects/project_other/knowledge?filename=",
        ) &&
        options.method === "POST"
      ) {
        knowledgeImports.push(String(url));
        return {
          ok: true,
          json: async () => structuredClone(projectKnowledgeFixture[0]),
        };
      }
      if (
        String(url).startsWith(
          "/api/v1/admin/projects/project_other/knowledge/knowledge_document_",
        ) &&
        options.method === "PUT"
      ) {
        knowledgeUpdates.push(String(url));
        knowledgeUpdateBodies.push(options.body);
        projectKnowledgeFixture[0].manifest.source_name = decodeURIComponent(
          String(url).split("filename=")[1],
        );
        return {
          ok: true,
          json: async () => structuredClone(projectKnowledgeFixture[0]),
        };
      }
      if (
        String(url).startsWith(
          "/api/v1/admin/projects/project_other/knowledge/knowledge_document_",
        ) &&
        options.method === "DELETE"
      ) {
        knowledgeDeletes.push(String(url));
        projectKnowledgeFixture.splice(0);
        return { ok: true, json: async () => [] };
      }
      if (url === "/api/v1/admin/projects/project_other/knowledge")
        return {
          ok: true,
          json: async () => structuredClone(projectKnowledgeFixture),
        };
      if (
        url === "/api/v1/admin/projects/project_other/specs" &&
        options.method === "POST"
      ) {
        createdSpecs.push(JSON.parse(options.body));
        return {
          ok: true,
          json: async () => structuredClone(projectSpecFixture[0]),
        };
      }
      if (url === "/api/v1/admin/projects/project_other/specs")
        return {
          ok: true,
          json: async () => structuredClone(projectSpecFixture),
        };
      if (
        url === "/api/v1/admin/projects/project_other/specs/python.testing" &&
        options.method === "DELETE"
      ) {
        specDeletes.push(String(url));
        projectSpecFixture.splice(0);
        return { ok: true, json: async () => [] };
      }
      if (
        url === "/api/v1/admin/projects/project_other/specs/activation" &&
        options.method === "PUT"
      ) {
        specActivations.push(JSON.parse(options.body));
        projectSpecFixture[0].active = true;
        return {
          ok: true,
          json: async () => structuredClone(projectSpecFixture),
        };
      }
      if (url === "/api/v1/admin/projects/project_other/learnings")
        return {
          ok: true,
          json: async () => structuredClone(learningFixture),
        };
      if (
        String(url).endsWith("/decision") &&
        String(url).includes("/learnings/") &&
        options.method === "POST"
      ) {
        learningDecisions.push(JSON.parse(options.body));
        learningFixture[0].decision = {
          action: "APPROVE",
          target: "SPEC",
          published_uri: "project://project_other/specs/spec_document_new",
          rationale: "Approved",
        };
        return {
          ok: true,
          json: async () => structuredClone(learningFixture[0]),
        };
      }
      if (
        url === "/api/v1/admin/projects/project_other/knowledge/selection" &&
        options.method === "PUT"
      ) {
        knowledgeSelections.push(JSON.parse(options.body));
        projectKnowledgeFixture[0].selected = true;
        return {
          ok: true,
          json: async () => structuredClone(projectKnowledgeFixture),
        };
      }
      if (url === "/api/v1/console")
        return {
          ok: true,
          json: async () => ({
            schema_version: "v0.2",
            team_id: "team_fixture",
            delivery_ready: deliveryReady,
          }),
        };
      if (url === "/api/v1/operations" && options.method === "POST") {
        const command = JSON.parse(options.body);
        submittedIntents.push(command.intent);
        const operation = {
          operation_id: `operation_${String(storedOperations.length + 1).padStart(32, "0")}`,
          team_id: "team_fixture",
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
        json: async () => {
          const value = structuredClone(fixture);
          if (String(url).includes("project_id=project_other"))
            value.selected_project_id = "project_other";
          return value;
        },
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
  assert.equal(get("scope-label").textContent, "Team 级");
  assert.equal(get("scope-title").textContent, "Fixture team");
  assert.equal(get("project-context-label").textContent, "工作负载筛选");
  assert.match(text(get("content")), /2 项当前 Project 未结束任务/);
  assert.match(text(get("content")), /\/backend\/module-a/);
  assert.match(text(get("content")), /\/frontend/);
  assert.ok(text(get("content")).includes(malicious));
  const roster = descend(get("content")).find(
    (node) => node.className === "agent-roster",
  );
  const agentCards = roster.children;
  assert.match(text(agentCards[0]), /规划/);
  assert.match(text(agentCards[1]), /实现/);
  assert.match(text(agentCards[2]), /测试/);
  assert.match(text(agentCards[3]), /评审/);
  assert.match(text(get("content")), /实现 · 任务队列/);
  assert.match(text(get("content")), /待完成 1/);
  assert.match(text(get("content")), /进行中 1/);
  assert.match(text(get("content")), /已阻塞 1/);
  assert.match(text(get("content")), /已完成 1/);
  await agentCards[2].events.click();
  assert.match(text(get("content")), /测试 · 任务队列/);
  assert.match(text(get("content")), /待完成 1/);
  const projectPicker = get("projects").children[0];
  assert.equal(projectPicker.className, "project-picker");
  assert.match(text(projectPicker), /2 个 Project · 可搜索切换/);
  const projectSearch = descend(projectPicker).find(
    (node) => node.tag === "input" && node.type === "search",
  );
  projectSearch.value = "Other";
  await projectSearch.events.input();
  const otherProject = descend(projectPicker).find(
    (node) => node.tag === "button" && node.textContent === "Other project",
  );
  await otherProject.events.click();
  assert.ok(urls.includes("/api/v1/team?project_id=project_other"));
  await get("nav-knowledge").events.click();
  assert.equal(get("scope-label").textContent, "Team 知识");
  assert.equal(
    get("operations").hidden,
    true,
    "full operation cards stay on the Requirements page",
  );
  assert.equal(
    get("projects").hidden,
    true,
    "Team Knowledge is not presented under the global Project selector",
  );
  const knowledgeNavigation = descend(get("content")).find(
    (node) => node.className === "knowledge-navigation",
  );
  assert.match(text(knowledgeNavigation), /知识库归属/);
  assert.match(text(knowledgeNavigation), /团队知识库/);
  assert.match(text(knowledgeNavigation), /项目知识库/);
  const teamContentNavigation = descend(get("content")).find(
    (node) => node.className === "knowledge-content-navigation",
  );
  assert.match(text(teamContentNavigation), /内容类型/);
  assert.match(text(teamContentNavigation), /通用知识/);
  assert.doesNotMatch(text(teamContentNavigation), /背景知识/);
  assert.match(text(teamContentNavigation), /开发规范/);
  assert.doesNotMatch(text(teamContentNavigation), /学习改进/);
  assert.match(text(get("content")), /team-guide.md/);
  assert.match(text(get("content")), /已用于新需求/);
  assert.ok(
    descend(get("content")).some(
      (node) => node.tag === "button" && node.textContent === "导入通用知识",
    ),
    "Team knowledge exposes the Team-specific import action",
  );
  const projectKnowledge = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "项目知识库",
  );
  await projectKnowledge.events.click();
  assert.equal(get("scope-label").textContent, "Project 知识");
  const projectSelector = descend(get("content")).find(
    (node) => node.className === "knowledge-project-selector",
  );
  assert.match(text(projectSelector), /选择 Project/);
  assert.match(text(projectSelector), /Other project/);
  const selectedKnowledgeProject = descend(projectSelector).find(
    (node) => node.tag === "button" && node.textContent === "Other project",
  );
  assert.match(
    selectedKnowledgeProject.className,
    /selected/,
    "the active knowledge Project remains visibly selected",
  );
  const projectContentNavigation = descend(get("content")).find(
    (node) => node.className === "knowledge-content-navigation",
  );
  assert.match(text(projectContentNavigation), /背景知识/);
  assert.doesNotMatch(text(projectContentNavigation), /通用知识/);
  assert.match(text(get("content")), /学习改进/);
  assert.match(text(get("content")), /project-guide.md/);
  assert.equal(
    descend(get("content")).some(
      (node) => node.className === "knowledge-upload",
    ),
    false,
    "the knowledge page defaults to its imported document inventory",
  );
  const importBackgroundKnowledge = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "导入背景知识",
  );
  await importBackgroundKnowledge.events.click();
  assert.match(text(get("composer")), /导入背景知识/);
  const backgroundFiles = descend(get("composer")).find(
    (node) => node.tag === "input" && node.type === "file",
  );
  assert.equal(
    backgroundFiles.multiple,
    true,
    "background import accepts multiple files",
  );
  backgroundFiles.files = [{ name: "one.md" }, { name: "two.txt" }];
  const backgroundForm = descend(get("composer")).find(
    (node) => node.className === "knowledge-upload",
  );
  assert.doesNotMatch(text(get("composer")), /维护方式/);
  await backgroundForm.events.submit({ preventDefault() {} });
  assert.equal(knowledgeImports.length, 2);
  assert.match(text(get("content")), /已导入 2 份背景知识/);
  assert.equal(get("composer").hidden, true);
  const enableProjectKnowledge = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "用于新需求",
  );
  await enableProjectKnowledge.events.click();
  assert.deepEqual(knowledgeSelections, [
    {
      document_ids: ["knowledge_document_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
    },
  ]);
  assert.match(text(get("content")), /无需重启/);
  const refreshedImportBackgroundKnowledge = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "导入背景知识",
  );
  await refreshedImportBackgroundKnowledge.events.click();
  const refreshedKnowledgeForm = descend(get("composer")).find(
    (node) => node.className === "knowledge-upload",
  );
  const refreshedKnowledgeFiles = descend(refreshedKnowledgeForm).find(
    (node) => node.tag === "input" && node.type === "file",
  );
  refreshedKnowledgeFiles.files = [{ name: "project-guide.md" }];
  await refreshedKnowledgeForm.events.submit({ preventDefault() {} });
  assert.equal(
    knowledgeUpdates.length,
    0,
    "same-name upload waits for approval",
  );
  assert.match(text(get("composer")), /覆盖风险/);
  const confirmKnowledgeReplacement = descend(get("composer")).find(
    (node) => node.tag === "button" && node.textContent === "确认替换并上传",
  );
  await confirmKnowledgeReplacement.events.click();
  assert.equal(knowledgeUpdates.length, 1);
  const updateKnowledge = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "更新文档",
  );
  await updateKnowledge.events.click();
  assert.equal(knowledgeContentReads.length, 1);
  assert.match(text(get("composer")), /更新背景知识/);
  const updateKnowledgeContent = descend(get("composer")).find(
    (node) => node.className === "knowledge-content-editor",
  );
  assert.equal(
    updateKnowledgeContent.value,
    "# Existing project guide\n\nCurrent content.\n",
  );
  updateKnowledgeContent.value =
    "# Edited project guide\n\nSaved in the browser.\n";
  updateKnowledgeContent.events.input();
  await interval.fn();
  assert.equal(
    descend(get("composer")).find(
      (node) => node.className === "knowledge-content-editor",
    ).value,
    "# Edited project guide\n\nSaved in the browser.\n",
    "automatic refresh must not discard modal edits",
  );
  const updateKnowledgeForm = descend(get("composer")).find((node) =>
    node.className.includes("knowledge-content-edit-form"),
  );
  await updateKnowledgeForm.events.submit({ preventDefault() {} });
  assert.equal(knowledgeUpdates.length, 2);
  assert.match(knowledgeUpdates[1], /filename=project-guide.md/);
  assert.equal(
    knowledgeUpdateBodies[1],
    "# Edited project guide\n\nSaved in the browser.\n",
  );
  assert.match(text(get("content")), /背景知识已更新/);
  const deleteKnowledge = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "删除",
  );
  await deleteKnowledge.events.click();
  assert.match(text(get("composer")), /历史交付仍保留原引用/);
  const confirmKnowledgeDelete = descend(get("composer")).find(
    (node) => node.tag === "button" && node.textContent === "确认删除",
  );
  await confirmKnowledgeDelete.events.click();
  assert.equal(knowledgeDeletes.length, 1);
  const specsMode = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "开发规范",
  );
  await specsMode.events.click();
  assert.match(text(get("content")), /Python testing/);
  assert.match(text(get("content")), /强约束开发规范/);
  assert.doesNotMatch(text(get("content")), /规范键/);
  assert.equal(
    descend(get("content")).some((node) =>
      node.className.includes("spec-create-form"),
    ),
    false,
    "the Spec page defaults to its existing Spec inventory",
  );
  const importSpecs = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "导入开发规范",
  );
  await importSpecs.events.click();
  assert.match(text(get("composer")), /导入开发规范/);
  const multiSelects = descend(get("composer")).filter((node) =>
    node.className.includes("multi-select"),
  );
  assert.equal(
    multiSelects.filter((node) => node.tag === "details").length,
    2,
    "roles and stages use multi-select dropdowns",
  );
  const verificationInput = descend(get("composer")).find(
    (node) =>
      node.tag === "textarea" && String(node.placeholder).startsWith("可选"),
  );
  assert.notEqual(verificationInput.required, true);
  const specForm = descend(get("composer")).find(
    (node) => node.className === "knowledge-upload spec-create-form",
  );
  const specFile = descend(specForm).find(
    (node) => node.tag === "input" && node.type === "file",
  );
  assert.equal(specFile.multiple, true, "Spec import accepts multiple files");
  assert.doesNotMatch(text(get("composer")), /维护方式/);
  const roleChoices = descend(
    multiSelects.find((node) => node.tag === "details"),
  ).filter((node) => node.tag === "input" && node.type === "checkbox");
  specFile.files = [
    { name: "quality.md", text: async () => "# Quality\n\nFollow the rule." },
    { name: "security.txt", text: async () => "# Security\n\nCheck inputs." },
  ];
  for (const choice of roleChoices) {
    choice.checked = false;
    choice.events.change();
  }
  await specForm.events.submit({ preventDefault() {} });
  assert.equal(createdSpecs.length, 0);
  assert.match(text(get("composer")), /至少需要选择一项/);
  for (const choice of roleChoices.filter((item) => item.value !== "manager")) {
    choice.checked = true;
    choice.events.change();
  }
  await specForm.events.submit({ preventDefault() {} });
  assert.equal(createdSpecs[0].spec_key, "quality");
  assert.equal(createdSpecs[1].spec_key, "security");
  assert.equal(createdSpecs[0].verification, "");
  assert.deepEqual(createdSpecs[0].stages, ["implementing", "qa", "review"]);
  assert.equal(createdSpecs[0].roles.length, 6);
  assert.equal(createdSpecs[0].roles.includes("manager"), false);
  const enableSpec = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "启用规范",
  );
  await enableSpec.events.click();
  assert.deepEqual(specActivations, [
    { spec_ids: ["spec_document_" + "d".repeat(32)] },
  ]);
  const updateSpec = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "更新规范",
  );
  await updateSpec.events.click();
  assert.match(text(get("composer")), /更新开发规范/);
  const updateSpecForm = descend(get("composer")).find((node) =>
    node.className.includes("spec-content-edit-form"),
  );
  const updateSpecContent = descend(updateSpecForm).find(
    (node) => node.className === "spec-content-editor",
  );
  updateSpecContent.value = "# Updated testing rule\n";
  await updateSpecForm.events.submit({ preventDefault() {} });
  assert.equal(createdSpecs[2].spec_key, "python.testing");
  const deleteSpec = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "删除",
  );
  await deleteSpec.events.click();
  assert.match(text(get("composer")), /历史交付仍保留原规范引用/);
  const confirmSpecDelete = descend(get("composer")).find(
    (node) => node.tag === "button" && node.textContent === "确认删除",
  );
  await confirmSpecDelete.events.click();
  assert.deepEqual(specDeletes, [
    "/api/v1/admin/projects/project_other/specs/python.testing",
  ]);
  const learningMode = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "学习改进",
  );
  await learningMode.events.click();
  assert.match(text(get("content")), /项目知识库/);
  assert.doesNotMatch(text(get("content")), /团队通用知识/);
  assert.match(text(get("content")), /MISSING_REGRESSION/);
  assert.match(text(get("content")), /重复出现 2 次/);
  const approveLearning = descend(get("content")).find(
    (node) =>
      node.tag === "button" && node.textContent === "批准为 Project Spec",
  );
  await approveLearning.events.click();
  assert.equal(learningDecisions[0].action, "APPROVE");
  assert.equal(learningDecisions[0].target, "SPEC");
  await get("nav-settings").events.click();
  assert.equal(get("scope-label").textContent, "平台级");
  assert.equal(get("context-controls").hidden, true);
  assert.doesNotMatch(text(get("content")), /创建新 Project/);
  assert.match(text(get("content")), /平台数据目录/);
  assert.doesNotMatch(text(get("content")), /MySQL DSN/);
  const modelSettings = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "模型路由",
  );
  await modelSettings.events.click();
  assert.ok(
    descend(get("content")).some((node) => node.value === "gpt-5.6-terra"),
  );
  const modelSelects = descend(get("content")).filter((node) =>
    node.className.split(" ").includes("single-select"),
  );
  assert.ok(modelSelects.length > 0);
  assert.ok(
    modelSelects.every((node) => node.tag === "details"),
    "every Model Routing dropdown uses the shared styled disclosure",
  );
  const duplicateRouteMessage = vm.runInContext(
    `modelRouteValidationMessage({ model_routes: [
      { provider: "codex", model: "gpt-5.6-sol", reasoning_effort: "high", enabled: true },
      { provider: " codex ", model: "gpt-5.6-sol ", reasoning_effort: "high", enabled: true }
    ] })`,
    context,
  );
  assert.match(duplicateRouteMessage, /第 2 条模型路由/);
  assert.match(duplicateRouteMessage, /第 1 条重复/);
  assert.match(duplicateRouteMessage, /codex \/ gpt-5\.6-sol/);
  const distinctReasoningMessage = vm.runInContext(
    `modelRouteValidationMessage({ model_routes: [
      { provider: "codex", model: "gpt-5.6-sol", reasoning_effort: "medium", enabled: true },
      { provider: "codex", model: "gpt-5.6-sol", reasoning_effort: "high", enabled: true }
    ] })`,
    context,
  );
  assert.equal(distinctReasoningMessage, null);
  vm.runInContext(
    `settingsDraft.model_routes.push({
      provider: "codex",
      model: "gpt-5.6-terra",
      kind: "codex_cli",
      endpoint: null,
      api_key_env: null,
      reasoning_effort: "high",
      image_input: null,
      enabled: true
    }); render();`,
    context,
  );
  const duplicateSettingsForm = descend(get("content")).find(
    (node) => node.tag === "form" && node.className === "settings-form",
  );
  await duplicateSettingsForm.events.submit({ preventDefault() {} });
  assert.equal(
    savedSettings.length,
    0,
    "duplicate model routes are rejected before the Settings API is called",
  );
  assert.match(text(duplicateSettingsForm), /第 3 条模型路由/);
  assert.match(text(duplicateSettingsForm), /第 1 条重复/);
  vm.runInContext("settingsDraft.model_routes.pop(); render();", context);
  vm.runInContext(
    `settingsDraft.model_routes.push({
      provider: "codex",
      model: "gpt-5.6-terra",
      kind: "codex_cli",
      endpoint: null,
      api_key_env: null,
      reasoning_effort: "medium",
      image_input: null,
      enabled: true
    }); render();`,
    context,
  );
  const coderReasoningChoices = descend(get("content"))
    .find((node) => node.dataset.role === "coder")
    .children.flatMap(descend)
    .filter((node) => node.tag === "button")
    .map((node) => node.textContent);
  assert.ok(coderReasoningChoices.includes("codex / gpt-5.6-terra · high"));
  assert.ok(coderReasoningChoices.includes("codex / gpt-5.6-terra · medium"));
  vm.runInContext("settingsDraft.model_routes.pop(); render();", context);
  assert.doesNotMatch(text(get("content")), /密钥状态/);
  assert.match(text(get("content")), /Agent 模型分配/);
  assert.equal(
    descend(get("content")).filter((node) =>
      node.className.includes("agent-model-card"),
    ).length,
    7,
  );
  const responseRoute = descend(get("content")).filter(
    (node) => node.className === "route-card",
  )[1];
  const enableResponseRoute = descend(responseRoute)
    .filter((node) => node.tag === "input" && node.type === "checkbox")
    .at(-1);
  enableResponseRoute.checked = true;
  enableResponseRoute.events.change();
  const productModel = descend(get("content"))
    .find((node) => node.dataset.role === "product")
    .children.flatMap(descend)
    .find((node) => node.dataset.key === "agent-primary-model-product");
  const deepseekModelOption = descend(productModel).find(
    (node) =>
      node.tag === "button" &&
      node.textContent === "deepseek / deepseek-v4 · high",
  );
  await deepseekModelOption.events.click();
  const modelRuntimeInputs = descend(get("content")).filter(
    (node) => node.tag === "input" && node.type === "password",
  );
  modelRuntimeInputs[0].value = "deepseek-key";
  modelRuntimeInputs[0].events.input();
  const mysqlSettings = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "MySQL",
  );
  await mysqlSettings.events.click();
  assert.match(text(get("content")), /MySQL DSN/);
  const dsnInput = descend(get("content")).find(
    (node) => node.tag === "input" && node.type === "password",
  );
  dsnInput.value = "mysql+pymysql://user:password@127.0.0.1:3307/database";
  dsnInput.events.input();
  const testConnection = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "测试连接",
  );
  await testConnection.events.click();
  assert.deepEqual(mysqlTests, [
    { dsn: "mysql+pymysql://user:password@127.0.0.1:3307/database" },
  ]);
  const settingsForm = descend(get("content")).find(
    (node) => node.tag === "form" && node.className === "settings-form",
  );
  await settingsForm.events.submit({ preventDefault() {} });
  assert.deepEqual(savedSettings[0].runtime_variables, [
    {
      environment_name: "ASE_MYSQL_DSN",
      value: "mysql+pymysql://user:password@127.0.0.1:3307/database",
    },
    {
      environment_name: "DEEPSEEK_API_KEY",
      value: "deepseek-key",
    },
  ]);
  const agentRoutes = Object.fromEntries(
    savedSettings[0].config.agent_model_routes.map((policy) => [
      policy.role,
      policy.routes,
    ]),
  );
  assert.equal(agentRoutes.product[0].model, "deepseek-v4");
  assert.equal(agentRoutes.coder[0].model, "gpt-5.6-terra");
  assert.equal(agentRoutes.coder[0].reasoning_effort, "high");
  await get("nav-status").events.click();
  assert.equal(get("scope-label").textContent, "平台级");
  assert.match(text(get("content")), /平台状态|配置与启动/);
  assert.match(text(get("content")), /MySQL 连接正常/);
  assert.match(text(get("content")), /已导入 1 份 · 已启用 1 份/);
  assert.match(text(get("content")), /Agent 模型路由/);
  assert.match(text(get("content")), /Manager Agent/);
  assert.match(text(get("content")), /Coder Agent/);
  assert.match(text(get("content")), /独立策略/);
  assert.match(text(get("content")), /主模型 codex \/ gpt-5.6-terra · high/);
  assert.match(text(get("content")), /备用 1 codex \/ gpt-5.6-terra · medium/);
  assert.match(text(get("content")), /可用模型目录/);
  assert.doesNotMatch(text(get("content")), /user:password/);
  const statusReads = urls.filter(
    (url) => url === "/api/v1/admin/status",
  ).length;
  await interval.fn();
  assert.equal(
    urls.filter((url) => url === "/api/v1/admin/status").length,
    statusReads,
    "the five-second Team poll does not repeatedly probe MySQL",
  );
  await get("refresh").events.click();
  assert.equal(
    urls.filter((url) => url === "/api/v1/admin/status").length,
    statusReads + 1,
    "manual refresh updates runtime status",
  );
  await get("nav-team").events.click();
  fixture.tasks[0].status = "QA";
  fixture.tasks[0].assignments[0].current_stage = false;
  fixture.tasks[0].assignments[1].current_stage = true;
  fixture.agents[0].current_stage_delivery_ids = [];
  fixture.agents[1].current_stage_delivery_ids = ["d1"];
  await interval.fn();
  const qaStageRoster = descend(get("content")).find(
    (node) => node.className === "agent-roster",
  );
  assert.match(text(qaStageRoster.children[1]), /等待当前阶段/);
  assert.match(text(qaStageRoster.children[2]), /执行中/);
  assert.match(text(get("content")), /测试 · 任务队列/);
  assert.match(text(get("content")), /进行中 1/);
  get("nav-requests").events.click();
  assert.equal(get("scope-label").textContent, "Project 级");
  assert.equal(get("scope-title").textContent, "Other project");
  assert.equal(
    get("operations").hidden,
    true,
    "successful or empty operation history does not dominate the page",
  );
  assert.doesNotMatch(text(get("content")), /创建 Project/);
  assert.match(text(get("project-creator")), /新建 Project/);
  const openProjectCreator = descend(get("project-creator")).find(
    (node) => node.tag === "button" && node.textContent === "新建 Project",
  );
  await openProjectCreator.events.click();
  const projectCreator = descend(get("composer")).find(
    (node) => node.className === "modal-dialog",
  );
  assert.match(text(projectCreator), /新建 Project/);
  const createProjectForm = descend(projectCreator).find(
    (node) => node.tag === "form",
  );
  descend(createProjectForm).find((node) => node.tag === "input").value =
    "New product";
  await createProjectForm.events.submit({ preventDefault() {} });
  assert.deepEqual(createdProjects, [{ name: "New product" }]);
  const newRequest = descend(get("content")).find(
    (node) => node.tag === "button" && node.textContent === "新建需求",
  );
  assert.ok(newRequest, "new Requirement action is beside the list count");
  assert.match(text(get("content")), /进行中 1/);
  assert.match(text(get("content")), /阻塞中 0/);
  assert.match(text(get("content")), /已完成 0/);
  assert.equal(get("detail").hidden, false);
  assert.match(text(get("detail")), /交付流程/);
  newRequest.events.click();
  const projectForm = descend(get("composer")).find(
    (node) => node.className === "project-form",
  );
  const projectName = descend(projectForm).find((node) => node.tag === "input");
  const chooseProjectRoots = descend(projectForm).find(
    (node) => node.tag === "button" && node.textContent === "选择代码目录",
  );
  projectName.value = "跨仓登录升级";
  await chooseProjectRoots.events.click();
  assert.match(text(projectForm), /\/backend\/module-a/);
  assert.match(text(projectForm), /\/frontend/);
  await projectForm.events.submit({ preventDefault() {} });
  assert.deepEqual(submittedIntents[0], {
    action: "CREATE_REQUIREMENT",
    project_id: "project_other",
    name: "跨仓登录升级",
    repository_roots: ["/backend/module-a", "/frontend"],
  });
  assert.match(text(get("operations")), /等待 Manager/);
  vm.runInContext('showDetail("request","r1")', context);
  const continueButton = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "继续交付",
  );
  await continueButton.events.click();
  assert.deepEqual(submittedIntents[1], {
    action: "CONTINUE_DELIVERY",
    project_id: "project_fixture",
    delivery_id: "r1",
    expected_checkpoint_sha256: "a".repeat(64),
  });
  assert.doesNotMatch(text(get("detail")), /a{64}/);

  const planSha = "b".repeat(64);
  storedOperations[1].status = "SUCCEEDED";
  storedOperations[1].updated_at = "2026-09-05T01:00:05Z";
  storedOperations[1].result = {
    project_id: "project_fixture",
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
    project_id: "project_fixture",
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
  deliveryReady = false;
  await interval.fn();
  assert.equal(
    descend(get("content")).some(
      (node) => node.tag === "button" && node.textContent === "新建需求",
    ),
    false,
  );
  assert.match(text(get("operations")), /待配置运行时/);
  await get("nav-settings").events.click();
  assert.equal(
    descend(get("content")).some(
      (node) => node.tag === "h2" && node.textContent === "创建 Project",
    ),
    false,
  );
  assert.match(text(get("content")), /交付运行时尚未就绪/);
  await get("nav-team").events.click();
  vm.runInContext('showDetail("task","d1")', context);
  deliveryReady = true;
  failure = true;
  await interval.fn();
  assert.match(get("connection").textContent, /旧数据/);
  assert.match(text(get("detail")), /测试中/);
  failure = false;
  await interval.fn();
  assert.equal(get("connection").className, "");

  fixture.requests[0].stage = "READY_FOR_DISCUSSION";
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  const discussionForm = descend(get("detail")).find(
    (node) => node.className === "discussion-form",
  );
  assert.equal(
    descend(discussionForm).some(
      (node) => node.tag === "input" && node.type === "file",
    ),
    false,
    "Product screenshots are pasted directly instead of selected through a file field",
  );
  const discussion = descend(discussionForm).find(
    (node) => node.tag === "textarea",
  );
  const pastedScreenshotSection = descend(discussionForm).find(
    (node) => node.className === "pasted-screenshot-section",
  );
  assert.equal(
    pastedScreenshotSection.hidden,
    true,
    "the screenshot preview stays hidden before an image is pasted",
  );
  const pastedScreenshot = {
    name: "checkout.png",
    type: "image/png",
    size: 1024,
  };
  discussion.events.paste({
    clipboardData: {
      items: [
        {
          kind: "file",
          type: "image/png",
          getAsFile: () => pastedScreenshot,
        },
      ],
    },
  });
  assert.equal(pastedScreenshotSection.hidden, false);
  assert.match(text(discussionForm), /checkout.png/);
  const removeScreenshot = descend(pastedScreenshotSection).find(
    (node) => node.tag === "button" && node.textContent === "移除",
  );
  await removeScreenshot.events.click();
  assert.equal(
    pastedScreenshotSection.hidden,
    true,
    "removing the last pasted screenshot hides the preview",
  );
  assert.doesNotMatch(
    text(discussionForm),
    /截图已添加/,
    "removing the last pasted screenshot clears the stale success feedback",
  );
  discussion.events.paste({
    clipboardData: {
      items: [
        {
          kind: "file",
          type: "image/png",
          getAsFile: () => pastedScreenshot,
        },
      ],
    },
  });
  await discussionForm.events.submit({ preventDefault() {} });
  assert.equal(screenshotUploads.length, 1);
  assert.deepEqual(submittedIntents.at(-1), {
    action: "PRODUCT_REPLY",
    project_id: "project_fixture",
    delivery_id: "r1",
    expected_checkpoint_sha256: "a".repeat(64),
    message: "",
    screenshot_ids: ["requirement_attachment_" + "e".repeat(40)],
  });
});
