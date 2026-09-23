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
    this.attributes = {};
    this.dataset = {};
    this.textContent = "";
    this.className = "";
    this.value = "";
    this.checked = false;
    this.hidden = false;
    this.classList = { toggle() {} };
  }
  append(...nodes) {
    for (const node of nodes) if (typeof node !== "string") node.parentElement = this;
    this.children.push(...nodes);
  }
  replaceChildren(...nodes) {
    this.children = nodes;
  }
  addEventListener(key, fn) {
    this.events[key] = fn;
  }
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
  getAttribute(key) { return this.attributes[key] ?? null; }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(node => node !== this); }
  removeAttribute(key) {
    delete this.attributes[key];
  }
  scrollIntoView() {
    this.scrollCount = (this.scrollCount || 0) + 1;
  }
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

test("agent queue cards keep long task metadata readable", () => {
  const styles = fs.readFileSync(
    path.join(__dirname, "../../src/ai_software_engineer/team_view/style.css"),
    "utf8",
  );
  assert.match(
    styles,
    /\.agent-queue-board\s*\{[^}]*grid-template-columns:\s*repeat\(4, minmax\(270px, 1fr\)\);[^}]*overflow-x:\s*auto;/s,
    "queue columns must scroll before shrinking cards below a readable width",
  );
  assert.match(
    styles,
    /\.work-row-path\s*\{[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis;[^}]*white-space:\s*nowrap;/s,
    "long repository paths must use a single truncated line",
  );
  assert.match(
    styles,
    /main #detail\.task-detail-modal\s*\{[^}]*position:\s*fixed;[^}]*background:\s*rgba\(20, 35, 55, 0\.48\);/s,
    "task details must open in a focused modal instead of extending the queue page",
  );
  assert.match(
    styles,
    /\.agent-queue \.work-row\s*\{[^}]*cursor:\s*pointer;/s,
    "overview cards must visibly communicate that the full card opens task details",
  );
  assert.match(
    styles,
    /\.agent-workspace\s*\{[^}]*align-items:\s*stretch;/s,
    "the queue panel must share its bottom edge with the Agent roster",
  );
  assert.match(
    styles,
    /\.agent-board\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*min-height:\s*0;/s,
    "the queue panel must consume the roster-defined grid height without growing it",
  );
  assert.match(
    styles,
    /\.agent-queue-board\s*\{[^}]*flex:\s*1 1 0;[^}]*min-height:\s*0;[^}]*overflow-x:\s*auto;[^}]*overflow-y:\s*hidden;/s,
    "the four-column board must fill the available height while retaining horizontal scrolling",
  );
  assert.match(
    styles,
    /\.agent-queue\s*\{[^}]*min-height:\s*0;[^}]*max-height:\s*100%;[^}]*overflow-y:\s*auto;/s,
    "each queue column must scroll vertically instead of extending the whole page",
  );
});

test("long blocker diagnostics stay inside the detail boundary", () => {
  const styles = fs.readFileSync(
    path.join(__dirname, "../../src/ai_software_engineer/team_view/style.css"),
    "utf8",
  );
  assert.match(
    styles,
    /\.request-blocking-primary\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/s,
    "blocker cards must remain constrained by the detail panel",
  );
  assert.match(
    styles,
    /\.request-blocking-reason\s*\{[^}]*overflow-wrap:\s*anywhere;[^}]*word-break:\s*break-word;/s,
    "opaque run IDs and hashes must wrap before crossing the detail boundary",
  );
});

test("Requirement detail uses one heading hierarchy and section rhythm", () => {
  const styles = fs.readFileSync(
    path.join(__dirname, "../../src/ai_software_engineer/team_view/style.css"),
    "utf8",
  );
  assert.match(
    styles,
    /\.request-detail-panel\s*\{[^}]*--detail-section-space:\s*18px;[^}]*padding:\s*20px;/s,
    "the Requirement detail panel must define one shared section spacing token",
  );
  assert.match(
    styles,
    /\.detail-section\s*\{[^}]*margin:\s*0;[^}]*padding:\s*var\(--detail-section-space\) 0;[^}]*border-top:\s*1px solid var\(--line\);/s,
    "every Requirement module must use the shared divider rhythm",
  );
  assert.match(
    styles,
    /\.request-detail-panel > \.detail-section h2\s*\{[^}]*font-size:\s*1\.2rem;[^}]*line-height:\s*1\.4;/s,
    "all Requirement module headings must have the same typography",
  );
  assert.match(
    styles,
    /\.discussion-form\s*\{[^}]*margin:\s*0;/s,
    "the Product discussion form must not add spacing outside the section rhythm",
  );
  assert.match(
    styles,
    /\.discussion-form \.form-feedback:empty\s*\{[^}]*display:\s*none;/s,
    "empty Product feedback must not leave a large gap above the submit button",
  );
  assert.match(
    styles,
    /\.stage-artifacts\s*\{[^}]*margin:\s*0;/s,
    "the stage-artifact divider must use the same spacing rhythm as other sections",
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
        history_delivery_ids: ["r1"],
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
    configurationApplyRequests = [],
    configurationApplyFailure = null,
    configurationApplyConnectionFailure = false,
    configurationApplyStatus = null,
    configurationApplyEffectivePort = 8765,
    settingsRestartRequired = false,
    assignedLocation = null,
    assignedLocations = [],
    locationAssignFailures = 0,
    browserStorage = new Map(),
    scheduledTimeouts = [],
    settingsSaveFailure = null,
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
    settings_contract_version: 1,
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
      execution_retry_policy: {
        product: {max_attempts: 20, max_transient_failures: 5},
        designer: {max_attempts: 3, max_transient_failures: 5},
        planner: {max_attempts: 3, max_transient_failures: 5},
        coder: {max_attempts: 3, max_transient_failures: 5},
        qa: {max_transient_failures: 5}, reviewer: {max_transient_failures: 5},
      },
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
      if (
        url === "/api/v1/admin/settings/apply" &&
        options.method === "POST"
      ) {
        configurationApplyRequests.push(JSON.parse(options.body));
        if (configurationApplyFailure)
          return {
            ok: false,
            json: async () => ({
              error: { message: configurationApplyFailure },
            }),
          };
        configurationApplyStatus = "PENDING";
        return {
          ok: true,
          json: async () => ({
            request_id: "configuration_apply_" + "a".repeat(32),
            status: "PENDING",
            safe_summary: "Configuration apply is in progress.",
            effective_console_port: configurationApplyEffectivePort,
          }),
        };
      }
      if (url === "/api/v1/admin/settings/apply")
        if (configurationApplyConnectionFailure)
          throw new Error("connection unavailable");
      if (url === "/api/v1/admin/settings/apply")
        return {
          ok: configurationApplyStatus !== null,
          json: async () => ({
            ...(configurationApplyStatus === null
              ? { error: { message: "No configuration apply request exists." } }
              : {}),
            request_id: "configuration_apply_" + "a".repeat(32),
            status: configurationApplyStatus,
            safe_summary:
              configurationApplyStatus === "FAILED"
                ? "Configuration remains saved but the Console could not be restarted. Use the service script to inspect status and retry safely."
                : configurationApplyStatus === "SUCCEEDED"
                  ? "Configuration was applied."
                  : "Configuration apply is in progress.",
            effective_console_port: configurationApplyEffectivePort,
          }),
        };
      if (url === "/api/v1/admin/settings" && options.method === "PUT") {
        if (settingsSaveFailure)
          return {
            ok: false,
            json: async () => ({
              error: { message: settingsSaveFailure },
            }),
          };
        savedSettings.push(JSON.parse(options.body));
        return {
          ok: true,
          json: async () => ({
            ...structuredClone(settingsFixture),
            restart_required: settingsRestartRequired,
          }),
        };
      }
      if (url === "/api/v1/admin/settings")
        return {
          ok: true,
          json: async () => ({
            ...structuredClone(settingsFixture),
            restart_required: settingsRestartRequired,
          }),
        };
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
      if (String(url).endsWith("/knowledge/index"))
        return {ok: true, json: async () => ({backlog: 1, failed: 1, oldest_pending_seconds: 3,
          jobs: [{job_id: "a".repeat(64), source_name: "pending.pdf", status: "QUEUED"},
            {job_id: "b".repeat(64), source_name: "broken.pdf", status: "FAILED", error_code: "DOCUMENT_INVALID"}]})};
      if (String(url).includes("/knowledge/index/") && String(url).endsWith("/retry"))
        return {ok: true, json: async () => ({status: "QUEUED"})};
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
    setTimeout: (fn) => {
      scheduledTimeouts.push(fn);
      return scheduledTimeouts.length;
    },
    clearTimeout: () => {},
    setInterval: (fn, ms) => {
      interval = { fn, ms };
    },
    AbortController,
    structuredClone,
    localStorage: {
      getItem: (key) => browserStorage.get(key) ?? null,
      setItem: (key, value) => browserStorage.set(key, value),
      removeItem: (key) => browserStorage.delete(key),
    },
    location: {
      href: "http://127.0.0.1:8765/",
      port: "8765",
      assign: (value) => {
        assignedLocations.push(value);
        if (locationAssignFailures > 0) {
          locationAssignFailures -= 1;
          throw new Error("navigation unavailable");
        }
        assignedLocation = value;
      },
    },
    URL: class extends URL {
      static createObjectURL() {
        return "blob:test-screenshot";
      }
      static revokeObjectURL() {}
    },
  });
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"),
      "utf8",
    ),
    context,
  );
  await new Promise(setImmediate);
  assert.equal(
    vm.runInContext(
      'humanizeBlockingText("Coder requested continuation after the configured run budget")',
      context,
    ),
    "Coder 已用完本轮连续执行次数，但实现尚未完成，需要创建恢复任务后继续。",
  );
  assert.equal(
    vm.runInContext(
      'humanizeBlockingText("Coder recovery stopped safely: failed Coder identity is missing, unsafe or ambiguous")',
      context,
    ),
    "系统未能确认唯一且可信的 Coder 执行记录，本次自动恢复已安全停止。",
  );
  assert.equal(
    vm.runInContext(
      'humanizeBlockingText("QA verification could not complete in the current environment; the candidate is retained for fresh verification")',
      context,
    ),
    "QA 未能在当前环境完成验证；候选代码已保留，继续交付时只会重新执行 QA/Review。",
  );
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
  const activeQueueCard = descend(get("content")).find(
    (node) =>
      node.className === "work-row" &&
      text(node).includes(malicious) &&
      text(node).includes("/backend/module-a"),
  );
  assert.match(text(activeQueueCard), /目录 \/backend\/module-a/);
  assert.match(text(activeQueueCard), /实现/);
  assert.doesNotMatch(text(activeQueueCard), /实现中|查看详情|等待人工处理/);
  assert.doesNotMatch(text(activeQueueCard), /模型 codex \/ gpt-5\.5/);
  assert.doesNotMatch(text(activeQueueCard), /最近活动/);
  assert.doesNotMatch(text(activeQueueCard), /当前交付阶段/);
  assert.equal(activeQueueCard.attributes.role, "button");
  assert.equal(activeQueueCard.attributes.tabindex, "0");
  await activeQueueCard.events.click();
  assert.equal(get("detail").className, "task-detail-modal");
  assert.match(text(get("detail")), /任务详情/);
  assert.match(text(get("detail")), /成员与分配模型/);
  vm.runInContext(`
    taskById("d1").role_queue = [{
      work_item_id: "work_ui_coder", role: "coder", attempt: 1,
      status: "RUNNING", lease_liveness: "LEASE_VALID",
      heartbeat_at: "2026-09-05T01:00:00Z"
    }];
    renderDetail();
  `, context);
  assert.match(text(get("detail")), /角色执行队列/);
  assert.match(text(get("detail")), /实现 · 第 1 次 · 执行中 · 租约有效/);
  assert.match(text(get("detail")), /最近心跳/);
  assert.equal(vm.runInContext(`taskGroup({
    status: "IMPLEMENTING", role_queue: [{status: "WAITING_HUMAN"}]
  })`, context), "blocked");
  vm.runInContext('taskById("d1").role_queue = [];', context);
  descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "关闭",
  ).events.click();
  await agentCards[0].events.click();
  assert.match(text(get("content")), /规划 · 任务队列/);
  assert.match(text(get("content")), /已完成 1/);
  const plannedRequirementCard = descend(get("content")).find(
    (node) => node.className === "work-row" && text(node).includes(malicious),
  );
  assert.ok(
    plannedRequirementCard,
    "upstream Agent queues resolve Requirement work items as well as repository Tasks",
  );
  await plannedRequirementCard.events.click();
  assert.equal(get("detail").className, "request-detail-panel");
  assert.match(text(get("detail")), /需求详情/);
  assert.equal(
    vm.runInContext(
      'compactPath("/Users/example/workspace/code/ai-workspace/example-project")',
      context,
    ),
    "…/ai-workspace/example-project",
  );
  await agentCards[2].events.click();
  assert.match(text(get("content")), /测试 · 任务队列/);
  assert.match(text(get("content")), /待完成 1/);
  fixture.tasks.push(
    {
      ...structuredClone(fixture.tasks[0]),
      id: "verification_old_blocked",
      status: "BLOCKED",
      terminal: true,
      blocker: "old verification failed",
      last_activity: "2026-09-04T01:00:00Z",
    },
    {
      ...structuredClone(fixture.tasks[0]),
      id: "verification_old_completed",
      status: "DONE",
      terminal: true,
      last_activity: "2026-09-04T02:00:00Z",
    },
    {
      ...structuredClone(fixture.tasks[0]),
      id: "verification_other_requirement",
      request_id: "r-other",
      title: "另一个需求",
      status: "BLOCKED",
      terminal: true,
      blocker: "another requirement failed verification",
      last_activity: "2026-09-04T03:00:00Z",
    },
  );
  fixture.agents[1].history_delivery_ids = [
    "verification_old_blocked",
    "verification_old_completed",
    "verification_other_requirement",
  ];
  await interval.fn();
  assert.equal(
    descend(get("content")).filter((node) => node.className === "work-row").length,
    2,
    "QA and Reviewer queues collapse attempts for the same Requirement without hiding a different Requirement",
  );
  assert.match(text(get("content")), /已阻塞 1/);
  assert.match(text(get("content")), /已完成 0/);
  fixture.agents[1].history_delivery_ids = [];
  fixture.tasks.splice(-3);
  await interval.fn();
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
  assert.doesNotMatch(text(get("content")), /已接收 2 份背景知识/);
  assert.match(text(get("notification")), /已接收 2 份背景知识/);
  await descend(get("notification")).find(
    (node) => node.tag === "button" && node.textContent === "知道了",
  ).events.click();
  assert.match(text(get("content")), /知识解析与索引/);
  assert.match(text(get("content")), /等待解析/);
  assert.match(text(get("content")), /解析失败/);
  const indexRetry = descend(get("content")).find((node) => node.tag === "button" && node.textContent === "重试索引");
  assert.ok(indexRetry);
  await indexRetry.events.click();
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
  assert.match(text(get("notification")), /无需重启/);
  await descend(get("notification")).find(
    (node) => node.tag === "button" && node.textContent === "知道了",
  ).events.click();
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
  assert.match(text(get("notification")), /背景知识更新已排队/);
  await descend(get("notification")).find(
    (node) => node.tag === "button" && node.textContent === "知道了",
  ).events.click();
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
  assert.equal(
    learningDecisions[0].rationale,
    "已在 Web Console 中核对来源证据并批准。",
  );
  await get("nav-settings").events.click();
  assert.equal(get("scope-label").textContent, "平台级");
  assert.equal(get("context-controls").hidden, true);
  assert.doesNotMatch(text(get("content")), /创建新 Project/);
  assert.match(text(get("content")), /平台数据目录/);
  assert.match(text(get("content")), /执行与重试策略/);
  vm.runInContext('settingsSnapshot.settings_contract_version = undefined; settingsDraft.codex_executable = "codex-stale"; render();', context);
  assert.match(text(get("content")), /服务版本不匹配.*重启 Web Console/);
  const staleSettingsForm = descend(get("content")).find(
    (node) => node.tag === "form" && node.className === "settings-form",
  );
  await staleSettingsForm.events.submit({ preventDefault() {} });
  assert.equal(savedSettings.length, 0, "a stale Settings server must not receive PUT");
  assert.match(text(get("composer")), /服务版本不匹配.*重启 Web Console/);
  vm.runInContext('settingsSnapshot.settings_contract_version = 1; settingsDraft.codex_executable = "codex"; render();', context);
  const designLimit = descend(get("content")).find(
    (node) => node.name === "retry-designer-max_attempts",
  );
  const transientLimit = descend(get("content")).find(
    (node) => node.name === "retry-designer-max_transient_failures",
  );
  assert.ok(designLimit);
  assert.ok(transientLimit);
  designLimit.value = "8";
  designLimit.events.input();
  transientLimit.value = "20";
  transientLimit.events.input();
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
  vm.runInContext("settingsDraft.model_routes[0].image_input = false; render();", context);
  const firstRouteCard = descend(get("content")).find((node) =>
    node.className.includes("model-route-disclosure"),
  );
  assert.match(text(firstRouteCard.children[0]), /仅文本/);
  vm.runInContext("settingsDraft.model_routes[0].image_input = null; render();", context);
  const defaultImageCard = descend(get("content")).find((node) =>
    node.className.includes("model-route-disclosure"),
  );
  assert.match(text(defaultImageCard.children[0]), /默认可传图/);
  assert.equal(vm.runInContext(`modelRouteValidationMessage({ model_routes: [
    { provider: "codex", model: "gpt-5.6-sol", kind: "codex_cli", reasoning_effort: "high" },
    { provider: "codex", model: "gpt-5.6-sol", kind: "responses", reasoning_effort: "high" }
  ] })`, context), null);
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
  assert.ok(coderReasoningChoices.includes("codex / gpt-5.6-terra · high · Codex CLI · 普通 CLI"));
  assert.ok(coderReasoningChoices.includes("codex / gpt-5.6-terra · medium · Codex CLI · 普通 CLI"));
  vm.runInContext(`settingsDraft.codex_cli_proxy_base_url = "http://127.0.0.1:8317/v1";
    settingsDraft.model_routes.push({...structuredClone(settingsDraft.model_routes[0]), connection_mode: "proxy"});
    render();`, context);
  const connectionChoices = descend(get("content"))
    .find((node) => node.dataset.role === "coder")
    .children.flatMap(descend)
    .filter((node) => node.tag === "button")
    .map((node) => node.textContent);
  assert.ok(connectionChoices.includes("codex / gpt-5.6-terra · high · Codex CLI · 普通 CLI"));
  assert.ok(connectionChoices.includes("codex / gpt-5.6-terra · high · Codex CLI · CLIProxyAPI"));
  assert.equal(vm.runInContext("modelRouteValidationMessage(settingsDraft)", context), null);
  assert.equal(vm.runInContext("recordedModelConnectionLabel({route_kind: 'codex_cli'})", context), "连接方式未记录");
  vm.runInContext("settingsDraft.model_routes.pop(); settingsDraft.codex_cli_proxy_base_url = null; render();", context);
  assert.doesNotMatch(text(get("content")), /密钥状态/);
  assert.match(text(get("content")), /Agent 模型分配/);
  assert.equal(
    descend(get("content")).filter((node) =>
      node.className.includes("agent-model-card"),
    ).length,
    7,
  );
  const responseRoute = descend(get("content")).filter(
    (node) => node.className.includes("route-card"),
  )[1];
  const enableResponseRoute = descend(responseRoute)
    .filter((node) => node.tag === "input" && node.type === "checkbox")
    .at(-1);
  enableResponseRoute.checked = true;
  enableResponseRoute.events.change();
  const coderCardBeforeFallback = descend(get("content")).find(
    (node) => node.dataset.role === "coder",
  );
  assert.match(text(coderCardBeforeFallback), /尚未添加备用模型/);
  assert.equal(
    descend(coderCardBeforeFallback).filter((node) => node.className === "agent-fallback-row").length,
    0,
    "enabling a catalog route must not silently add it to an Agent fallback policy",
  );
  const productModel = descend(get("content"))
    .find((node) => node.dataset.role === "product")
    .children.flatMap(descend)
    .find((node) => node.dataset.key === "agent-primary-model-product");
  const deepseekModelOption = descend(productModel).find(
    (node) =>
      node.tag === "button" &&
      node.textContent === "deepseek / deepseek-v4 · high · Responses API",
  );
  await deepseekModelOption.events.click();
  const selectedProductModel = descend(get("content"))
    .find((node) => node.dataset.key === "agent-primary-model-product");
  assert.equal(
    descend(selectedProductModel).find((node) => node.className === "single-select-value").textContent,
    "deepseek-v4",
    "selected summary stays compact while the options retain exact route labels",
  );
  const addProductFallback = async (label) => {
    const productCard = descend(get("content")).find(
      (node) => node.dataset.role === "product",
    );
    const fallbackSelect = descend(productCard).find(
      (node) => node.dataset.key === "agent-fallback-model-product",
    );
    const option = descend(fallbackSelect).find(
      (node) => node.tag === "button" && node.textContent === label,
    );
    await option.events.click();
  };
  await addProductFallback("codex / gpt-5.6-terra · high · Codex CLI · 普通 CLI");
  await addProductFallback("codex / gpt-5.6-terra · medium · Codex CLI · 普通 CLI");
  const productCardWithFallbacks = descend(get("content")).find(
    (node) => node.dataset.role === "product",
  );
  const secondFallback = descend(productCardWithFallbacks).find(
    (node) => node.dataset.fallbackIndex === "2",
  );
  await descend(secondFallback).find(
    (node) => node.tag === "button" && node.getAttribute("aria-label") === "上移备用 2",
  ).events.click();
  const productCardAfterMove = descend(get("content")).find(
    (node) => node.dataset.role === "product",
  );
  const removableFallback = descend(productCardAfterMove).find(
    (node) => node.dataset.fallbackIndex === "2",
  );
  await descend(removableFallback).find(
    (node) => node.tag === "button" && node.getAttribute("aria-label") === "移除备用 2",
  ).events.click();
  const productCardAfterRemove = descend(get("content")).find(
    (node) => node.dataset.role === "product",
  );
  assert.doesNotMatch(text(productCardAfterRemove), /备用 2/);
  await addProductFallback("codex / gpt-5.6-terra · high · Codex CLI · 普通 CLI");
  const responseKeyRow = descend(get("content")).find(
    (node) => node.className === "field settings-route-field" &&
      node.children[0]?.children[0]?.textContent === "API Key",
  );
  const responseKeyInput = descend(responseKeyRow).find(
    (node) => node.tag === "input" && node.type === "password",
  );
  responseKeyInput.value = "deepseek-key";
  responseKeyInput.events.input();
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
  settingsRestartRequired = true;
  await settingsForm.events.submit({ preventDefault() {} });
  assert.ok(savedSettings.length, text(get("composer")) + text(settingsForm));
  assert.equal(savedSettings.at(-1).config.execution_retry_policy.designer.max_attempts, 8);
  assert.equal(savedSettings.at(-1).config.execution_retry_policy.designer.max_transient_failures, 20);
  assert.match(text(get("composer")), /设置保存成功/);
  assert.match(text(get("composer")), /应用配置.*重启 Web Console/);
  assert.doesNotMatch(
    text(get("content")),
    /配置已保存，但尚未应用到当前 Web Console/,
  );
  assert.equal(descend(get("content")).some(
    (node) => node.tag === "button" && node.textContent === "应用配置",
  ), false);
  const applyConfiguration = descend(get("composer")).find(
    (node) => node.tag === "button" && node.textContent === "应用配置",
  );
  assert.ok(applyConfiguration);
  await Promise.all([
    applyConfiguration.events.click(),
    applyConfiguration.events.click(),
  ]);
  assert.deepEqual(configurationApplyRequests, [{}]);
  assert.match(text(get("content")), /正在重启/);
  assert.match(text(get("composer")), /正在重启/);
  assert.equal(descend(get("composer")).find(
    (node) => node.tag === "button" && node.textContent === "正在应用…",
  ).disabled, true);
  assert.match(browserStorage.get("ase-configuration-apply"), /configuration_apply_/);
  configurationApplyStatus = "SUCCEEDED";
  settingsRestartRequired = false;
  await interval.fn();
  assert.match(text(get("content")), /配置已应用/);
  assert.match(text(get("composer")), /配置已应用/);
  assert.equal(descend(get("composer")).some(
    (node) => node.tag === "button" && node.textContent === "应用配置",
  ), false);
  assert.equal(browserStorage.has("ase-configuration-apply"), false);
  assert.equal(assignedLocation, null);
  settingsRestartRequired = true;
  browserStorage.clear();
  vm.runInContext(
    "configurationApplyPending = null; configurationApplyInFlight = false; settingsSnapshot.restart_required = true;",
    context,
  );
  await vm.runInContext("resumeConfigurationApply()", context);
  vm.runInContext("render()", context);
  assert.equal(
    vm.runInContext("configurationApplyInFlight", context),
    false,
  );
  const applyAfterStaleSuccess = descend(get("composer")).find(
    (node) => node.tag === "button" && node.textContent === "应用配置",
  );
  assert.ok(applyAfterStaleSuccess);
  assert.equal(applyAfterStaleSuccess.disabled, false);
  settingsRestartRequired = false;
  configurationApplyStatus = "PENDING";
  configurationApplyEffectivePort = 8877;
  browserStorage.clear();
  assignedLocation = null;
  vm.runInContext(
    "configurationApplyPending = null; configurationApplyInFlight = false;",
    context,
  );
  await vm.runInContext("resumeConfigurationApply()", context);
  scheduledTimeouts.at(-1)();
  assert.match(assignedLocation, /127\.0\.0\.1:8877/);
  assignedLocations.length = 0;
  assignedLocation = null;
  locationAssignFailures = 1;
  vm.runInContext(
    "configurationApplyInFlight = true; configurationApplyStartedAt = Date.now();",
    context,
  );
  vm.runInContext("reconnectToConfigurationPort(8877)", context);
  scheduledTimeouts.at(-1)();
  scheduledTimeouts.at(-1)();
  assert.equal(assignedLocations.length, 2);
  assert.match(assignedLocation, /127\.0\.0\.1:8877/);
  assignedLocation = null;
  configurationApplyEffectivePort = 8765;
  vm.runInContext(
    "configurationApplyPending = null; configurationApplyInFlight = false;",
    context,
  );
  vm.runInContext(
    "settingsSnapshot.restart_required = true; configurationApplyResult = null; render();",
    context,
  );
  configurationApplyEffectivePort = 8877;
  await descend(get("composer"))
    .find((node) => node.tag === "button" && node.textContent === "应用配置")
    .events.click();
  scheduledTimeouts.at(-1)();
  assert.match(assignedLocation, /127\.0\.0\.1:8877/);
  configurationApplyStatus = "FAILED";
  browserStorage.clear();
  vm.runInContext(
    "configurationApplyPending = null; configurationApplyInFlight = false;",
    context,
  );
  await vm.runInContext("resumeConfigurationApply()", context);
  assert.match(text(get("content")), /could not be restarted/);
  assert.equal(browserStorage.has("ase-configuration-apply"), false);
  configurationApplyConnectionFailure = true;
  browserStorage.set(
    "ase-configuration-apply",
    JSON.stringify({
      request_id: "configuration_apply_" + "a".repeat(32),
      effective_console_port: 8765,
    }),
  );
  vm.runInContext(
    "configurationApplyPending = readConfigurationApplyPending(); configurationApplyInFlight = true; configurationApplyStartedAt = Date.now() - configurationApplyTimeoutMs - 1;",
    context,
  );
  await vm.runInContext("refreshConfigurationApply()", context);
  assert.match(text(get("content")), /未在预期时间内恢复连接/);
  assert.equal(
    vm.runInContext("configurationApplyInFlight", context),
    false,
  );
  assert.match(browserStorage.get("ase-configuration-apply"), /configuration_apply_/);
  configurationApplyConnectionFailure = false;
  configurationApplyStatus = "PENDING";
  vm.runInContext(
    "configurationApplyInFlight = true; configurationApplyStartedAt = Date.now() - configurationApplyTimeoutMs - 1;",
    context,
  );
  await vm.runInContext("refreshConfigurationApply()", context);
  assert.match(text(get("content")), /未在预期时间内恢复连接/);
  assert.equal(
    vm.runInContext("configurationApplyInFlight", context),
    false,
  );
  assert.match(browserStorage.get("ase-configuration-apply"), /configuration_apply_/);
  configurationApplyFailure = "配置仍已保存，但服务监督器暂不可用。";
  vm.runInContext(
    "settingsSnapshot.restart_required = true; configurationApplyResult = null; render();",
    context,
  );
  await descend(get("composer"))
    .find((node) => node.tag === "button" && node.textContent === "应用配置")
    .events.click();
  assert.match(text(get("content")), /配置仍已保存/);
  assert.match(text(get("composer")), /配置仍已保存，但服务监督器暂不可用/);
  assert.equal(descend(get("composer")).find(
    (node) => node.tag === "button" && node.textContent === "应用配置",
  ).disabled, false);
  assert.doesNotMatch(text(get("content")), /deepseek-key/);
  assert.equal(savedSettings.length, 1);
  configurationApplyFailure = null;
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
  assert.deepEqual(
    agentRoutes.product.slice(1).map((route) => route.reasoning_effort),
    ["medium", "high"],
  );
  assert.equal(agentRoutes.coder[0].model, "gpt-5.6-terra");
  assert.equal(agentRoutes.coder[0].reasoning_effort, "high");
  assert.equal(
    agentRoutes.coder.length,
    1,
    "unselected catalog routes are not serialized as Coder fallbacks",
  );
  settingsSaveFailure = "模型路由凭证无效。";
  const failedSettingsForm = descend(get("content")).find(
    (node) => node.tag === "form" && node.className === "settings-form",
  );
  vm.runInContext(
    "settingsDraft.model_routes.push(structuredClone(settingsDraft.model_routes[0]))",
    context,
  );
  await failedSettingsForm.events.submit({ preventDefault() {} });
  assert.match(text(get("composer")), /设置保存失败/);
  assert.match(text(get("composer")), /与第 1 条重复/);
  assert.equal(savedSettings.length, 1, "client validation must send no PUT");
  await descend(get("composer"))
    .find((node) => node.tag === "button" && node.textContent === "知道了")
    .events.click();
  vm.runInContext("settingsDraft.model_routes.pop()", context);
  await failedSettingsForm.events.submit({ preventDefault() {} });
  assert.match(text(get("composer")), /设置保存失败/);
  assert.match(text(get("composer")), /模型路由凭证无效/);
  assert.equal(
    get("composer").children[0].attributes.role,
    "alertdialog",
    "save failures must be announced as an alert dialog",
  );
  assert.equal(savedSettings.length, 1);
  settingsSaveFailure = null;
  const acknowledgeSettingsFailure = descend(get("composer")).find(
    (node) => node.tag === "button" && node.textContent === "知道了",
  );
  await acknowledgeSettingsFailure.events.click();
  settingsRestartRequired = false;
  await descend(get("content"))
    .find((node) => node.tag === "form" && node.className === "settings-form")
    .events.submit({ preventDefault() {} });
  assert.match(text(get("composer")), /保存成功/);
  assert.doesNotMatch(text(get("composer")), /应用配置|重启|监督器/);
  await descend(get("composer"))
    .find((node) => node.tag === "button" && node.textContent === "知道了")
    .events.click();
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
  fixture.requests.push({
    ...structuredClone(fixture.requests[0]),
    id: "r2",
    title: "第二个需求",
    checkpoint_sha256: "c".repeat(64),
  });
  await interval.fn();
  get("nav-requests").events.click();
  const secondRequirementCard = descend(get("content")).find(
    (node) =>
      node.tag === "article" &&
      node.className.includes("request") &&
      text(node).includes("第二个需求"),
  );
  assert.equal(
    typeof secondRequirementCard.events.click,
    "function",
    "the whole Requirement card must open its detail, not only its title",
  );
  await secondRequirementCard.events.click();
  assert.match(text(get("detail")), /第二个需求/);
  const selectedRequirementCards = descend(get("content")).filter(
    (node) =>
      node.tag === "article" &&
      node.className.split(" ").includes("request-selected"),
  );
  assert.equal(
    selectedRequirementCards.length,
    1,
    "exactly one Requirement card must show the selected state",
  );
  assert.match(
    text(selectedRequirementCards[0]),
    /第二个需求/,
    "the selected card must follow the Requirement opened in detail",
  );
  await interval.fn();
  assert.match(
    text(get("detail")),
    /第二个需求/,
    "polling preserves the selected Requirement",
  );
  const firstRequirementCard = descend(get("content")).find(
    (node) =>
      node.tag === "article" &&
      node.className.includes("request") &&
      text(node).includes(malicious),
  );
  let keyboardDefaultPrevented = false;
  await firstRequirementCard.events.keydown({
    key: "Enter",
    preventDefault() {
      keyboardDefaultPrevented = true;
    },
  });
  assert.equal(keyboardDefaultPrevented, true);
  assert.ok(text(get("detail")).includes(malicious));
  fixture.requests.pop();
  await interval.fn();
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
  assert.equal(get("operations").hidden, true);
  assert.match(text(get("notification")), /等待 Manager/);
  await descend(get("notification")).find(
    (node) => node.tag === "button" && node.textContent === "知道了",
  ).events.click();
  fixture.tasks.slice(0, 2).forEach((task) => {
    task.status = "BLOCKED";
    task.terminal = true;
    task.blocker = "Waiting for recovery";
  });
  await interval.fn();
  // The fixture holds all projects' requests; select the owner before its operation.
  fixture.selected_project_id = "project_fixture";
  await vm.runInContext('refresh("project_fixture")', context);
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
  assert.match(text(get("notification")), /继续交付.*已重新排队/);
  await descend(get("notification")).find(
    (node) => node.tag === "button" && node.textContent === "知道了",
  ).events.click();

  fixture.requests[0].stage = "BLOCKED";
  fixture.requests[0].blocker = "Old joint blocker";
  fixture.requests[0].next_action = "Inspect the old blocked checkpoint.";
  fixture.requests[0].dialogue = [
    { sequence: 1, speaker: "user", text: "Clarified requirement", attachments: [] },
  ];
  fixture.tasks[0].status = "QA";
  fixture.tasks[0].terminal = false;
  delete fixture.tasks[0].blocker;
  fixture.tasks[1].status = "NEW";
  fixture.tasks[1].terminal = false;
  delete fixture.tasks[1].blocker;
  fixture.agents.push({
    id: "agent_manager",
    name: "管理",
    roles: ["manager"],
    enabled: true,
    max_parallel_assignments: 1,
    current_stage_delivery_ids: [],
    assigned_delivery_ids: [],
    history_delivery_ids: [],
  });
  storedOperations[1].status = "RUNNING";
  await interval.fn();
  assert.equal(
    get("notification").hidden,
    true,
    "QUEUED to RUNNING does not reopen an acknowledged active-operation dialog",
  );
  assert.match(text(get("content")), /进行中 1/);
  assert.match(text(get("content")), /阻塞中 0/);
  const activeRequirementCard = descend(get("content")).find(
    (node) =>
      node.tag === "article" &&
      node.className.includes("request") &&
      text(node).includes(malicious),
  );
  assert.match(text(activeRequirementCard), /测试中/);
  assert.doesNotMatch(text(activeRequirementCard), /Old joint blocker/);
  const activeDeliveryFlow = descend(get("detail")).find(
    (node) =>
      node.className === "detail-section" && text(node).includes("交付流程"),
  );
  assert.match(text(activeDeliveryFlow), /产品.*设计.*计划.*实现.*测试.*评审.*交付/);
  assert.doesNotMatch(
    text(activeDeliveryFlow),
    /Manager|正在|可以离开|平台会按串行阶段继续推进/,
    "the delivery flow contains node states only",
  );
  fixture.requests[0].stage = "VERIFY_QA";
  fixture.tasks[0].status = "REVIEW";
  await interval.fn();
  const authoritativeQaFlow = descend(get("detail")).find(
    (node) => node.className === "delivery-flow",
  );
  const authoritativeQaCurrent = authoritativeQaFlow.children.find(
    (node) => node.className === "current",
  );
  assert.match(
    text(authoritativeQaCurrent),
    /5.*测试/,
    "the Requirement verification stage must not be overwritten by a stale repository REVIEW status",
  );
  fixture.requests[0].stage = "INTEGRATING";
  fixture.tasks.push({
    ...structuredClone(fixture.tasks[0]),
    id: "verification_current_plan",
    request_id: "r1",
    source_delivery_id: fixture.tasks[0].id,
    status: "VERIFY_QA",
    terminal: false,
    blocker: null,
    last_activity: "2026-09-17T03:27:20Z",
    next_action: "QA candidate verification is active.",
  });
  await interval.fn();
  const activeLeaseQaFlow = descend(get("detail")).find(
    (node) => node.className === "delivery-flow",
  );
  const activeLeaseQaCurrent = activeLeaseQaFlow.children.find(
    (node) => node.className === "current",
  );
  assert.match(
    text(activeLeaseQaCurrent),
    /5.*测试/,
    "an active QA verification lease must override the joint INTEGRATING checkpoint",
  );
  assert.match(text(get("detail")), /查看仓库任务 · 候选测试中/);
  assert.doesNotMatch(text(get("detail")), /VERIFY_QA/);
  assert.doesNotMatch(text(get("operations")), /Manager 正在执行/);
  fixture.tasks.pop();
  fixture.requests[0].stage = "BLOCKED";
  fixture.tasks[0].status = "QA";
  await interval.fn();
  const completedDiscussion = descend(get("detail")).find(
    (node) => node.className === "detail-section product-dialogue",
  );
  assert.doesNotMatch(
    text(completedDiscussion),
    /Manager 正在处理该需求|Product Agent 正在回复/,
    "delivery recovery must not be rendered as Product discussion activity",
  );
  await get("nav-team").events.click();
  const recoveryRoster = descend(get("content")).find(
    (node) => node.className === "agent-roster",
  );
  const recoveryCoder = recoveryRoster.children.find((node) =>
    text(node).includes("实现"),
  );
  const recoveryQa = recoveryRoster.children.find((node) =>
    text(node).includes("测试"),
  );
  const recoveryManager = recoveryRoster.children.find((node) =>
    text(node).includes("管理"),
  );
  assert.match(text(recoveryCoder), /等待当前阶段/);
  assert.match(text(recoveryQa), /执行中/);
  assert.match(text(recoveryManager), /空闲中/);
  await recoveryQa.events.click();
  assert.match(text(get("content")), /测试 · 任务队列/);
  assert.match(text(get("content")), /进行中 1/);
  assert.ok(
    descend(get("content")).find(
      (node) =>
        node.className === "work-row" &&
        text(node).includes(malicious) &&
        text(node).includes("/backend/module-a"),
    ),
    "the active recovery stays in the backend-reported QA queue",
  );
  await recoveryManager.events.click();
  assert.match(text(get("content")), /管理 · 任务队列/);
  assert.match(text(get("content")), /待完成 0/);
  get("nav-requests").events.click();
  fixture.agents.pop();
  fixture.tasks.slice(0, 2).forEach((task) => {
    task.status = "BLOCKED";
    task.terminal = true;
    task.blocker = "Waiting for recovery";
  });

  const planSha = "b".repeat(64);
  const scopeSha = "c".repeat(64);
  storedOperations[1].status = "SUCCEEDED";
  storedOperations[1].updated_at = "2026-09-05T01:00:05Z";
  storedOperations[1].result = {
    project_id: "project_fixture",
    delivery_id: "r1",
    checkpoint_sha256: "a".repeat(64),
    stage: "BLOCKED",
    next_action: "No automatic continuation is available.",
  };
  await interval.fn();
  assert.doesNotMatch(text(get("operations")), /No automatic continuation is available/);
  assert.match(
    text(get("notification")),
    /具体原因和下一步已收口到需求详情/,
    "the operation dialog points to the one authoritative blocker surface",
  );
  const openRequirementWorkspace = descend(get("notification")).find(
    (node) => node.tag === "button" && node.textContent === "打开需求工作区",
  );
  await openRequirementWorkspace.events.click();
  assert.equal(get("detail").className, "request-detail-panel");
  assert.ok(get("detail").scrollCount > 0, "the operation shortcut scrolls to Requirement detail");
  assert.doesNotMatch(text(get("content")), /Waiting for recovery/);
  vm.runInContext('showDetail("request","r1")', context);
  const blockedDetail = text(get("detail"));
  assert.equal(
    blockedDetail.match(/阻塞信息/g)?.length,
    1,
    "Requirement detail owns exactly one blocker module",
  );
  assert.equal(
    blockedDetail.match(/Waiting for recovery/g)?.length,
    1,
    "identical repository blockers are deduplicated",
  );
  assert.match(blockedDetail, /No automatic continuation is available/);
  assert.doesNotMatch(blockedDetail, /Old joint blocker/);
  storedOperations[1].result.next_action = "Waiting for recovery";
  await interval.fn();
  assert.equal(text(get("detail")).match(/Waiting for recovery/g)?.length, 1);
  storedOperations[1].result.next_action = "No automatic continuation is available.";
  fixture.tasks.push({
    ...structuredClone(fixture.tasks[0]),
    id: "verification_superseded_blocker",
    source_delivery_id: fixture.tasks[0].id,
    blocker: "Superseded QA failure",
    next_action: "Obsolete QA retry advice",
    last_activity: "2026-09-04T01:00:00Z",
  });
  await interval.fn();
  assert.doesNotMatch(
    text(get("detail")),
    /Superseded QA failure|Obsolete QA retry advice/,
    "old verification failures are audit evidence, not current requirement blockers",
  );
  fixture.tasks.push({
    ...structuredClone(fixture.tasks[0]),
    id: "verification_latest_blocker",
    source_delivery_id: fixture.tasks[0].id,
    blocker: "Current reviewer provider failure",
    last_activity: "2026-09-06T01:00:00Z",
  });
  await interval.fn();
  const currentBlockers = vm.runInContext(
    'requestBlockingSummary(snapshot.requests[0]).reasons',
    context,
  );
  assert.ok(currentBlockers.some((item) => item.reason === "Current reviewer provider failure"));
  assert.ok(currentBlockers.some((item) => item.reason === "Waiting for recovery"));
  assert.ok(currentBlockers.every((item) => item.reason !== "Superseded QA failure"));
  fixture.tasks.splice(-2);
  await interval.fn();
  assert.ok(
    descend(get("detail")).find(
      (node) => node.tag === "button" && node.textContent === "关闭需求",
    ),
    "blocked Requirements can be closed without losing their history",
  );
  assert.ok(
    descend(get("detail")).find(
      (node) => node.tag === "button" && node.textContent === "删除需求",
    ),
    "blocked Requirements can be retired from the Project view",
  );
  const olderBlocked = JSON.parse(JSON.stringify(storedOperations[1]));
  olderBlocked.operation_id = "operation_older_blocked";
  olderBlocked.updated_at = "2026-09-05T01:00:04Z";
  storedOperations.push(olderBlocked);
  await interval.fn();
  assert.equal(
    get("notification").hidden,
    true,
    "an acknowledged latest result and its older duplicate do not reopen a notification",
  );
  storedOperations.pop();

  storedOperations[1].result = {
    project_id: "project_fixture",
    delivery_id: "r1",
    checkpoint_sha256: "a".repeat(64),
    stage: "WAITING_HUMAN",
    next_action: "Approve exact omitted paths",
    approval: {
      kind: "coder_scope",
      plan_sha256: scopeSha,
      title: "批准补充 Coder 文件范围",
      facts: ["待补充文件 src/pkg/__init__.py"],
    },
  };
  fixture.requests[0].stage = "BLOCKED";
  fixture.tasks.forEach((task) => {
    task.blocker =
      "Coder failed at attempt 1: coder run run_fixture failed: Codex worktree changes violated the machine policy";
  });
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  const scopeBlockerSection = descend(get("detail")).find((node) =>
    node.className.includes("request-blocking-section"),
  );
  const approveScope = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "批准文件范围",
  );
  assert.ok(approveScope, "WAITING_HUMAN renders its exact scope approval");
  assert.ok(
    descend(scopeBlockerSection).includes(approveScope),
    "the pending recovery action is rendered beside the blocker instead of below the discussion",
  );
  assert.doesNotMatch(
    text(scopeBlockerSection),
    /Coder failed at attempt 1|Codex worktree changes violated the machine policy/,
    "a successful continue operation must not look like the original failure happened again",
  );
  assert.match(text(scopeBlockerSection), /原始阻塞.*文件改动超出原任务授权范围/s);
  assert.match(text(get("detail")), /src\/pkg\/__init__\.py/);
  assert.match(text(get("detail")), /不会启动 Agent.*仍需审批恢复计划/);
  assert.doesNotMatch(text(get("detail")), /c{64}/);
  await approveScope.events.click();
  assert.deepEqual(submittedIntents[2], {
    action: "CONTINUE_DELIVERY",
    project_id: "project_fixture",
    delivery_id: "r1",
    expected_checkpoint_sha256: "a".repeat(64),
    approved_scope_sha256: scopeSha,
  });

  storedOperations[2].status = "SUCCEEDED";
  storedOperations[2].updated_at = "2026-09-05T01:00:06Z";
  storedOperations[2].result = {
    project_id: "project_fixture",
    delivery_id: "r1",
    checkpoint_sha256: "a".repeat(64),
    stage: "BLOCKED",
    next_action: "Current recovery source or target facts do not match",
  };
  storedOperations.push({
    ...structuredClone(storedOperations[1]),
    operation_id: "operation_reissued_scope",
    updated_at: "2026-09-05T01:00:07Z",
  });
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  assert.ok(
    descend(get("detail")).find(
      (node) => node.tag === "button" && node.textContent === "批准文件范围",
    ),
    "a failed scope approval must not consume a later reissued approval with the same digest",
  );
  storedOperations.pop();

  storedOperations[2].status = "SUCCEEDED";
  storedOperations[2].updated_at = "2026-09-05T01:00:08Z";
  storedOperations[2].result = {
    project_id: "project_fixture",
    delivery_id: "r1",
    checkpoint_sha256: "a".repeat(64),
    stage: "WAITING_HUMAN",
    next_action: "Approve exact recovery",
    approval: {
      kind: "coder_recovery",
      plan_sha256: planSha,
      title: "批准 Coder 恢复任务",
      facts: ["保留改动 2 个文件", "已补充文件范围 src/pkg/__init__.py"],
    },
  };
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  const approvePlan = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "批准并继续",
  );
  assert.ok(approvePlan, "scope approval is followed by exact recovery plan approval");
  await approvePlan.events.click();
  assert.deepEqual(submittedIntents[3], {
    action: "CONTINUE_DELIVERY",
    project_id: "project_fixture",
    delivery_id: "r1",
    expected_checkpoint_sha256: "a".repeat(64),
    approved_plan_sha256: planSha,
  });

  storedOperations[3].status = "FAILED";
  storedOperations[3].updated_at = "2026-09-05T01:00:09Z";
  storedOperations[3].error_summary = "Provider unavailable";
  await interval.fn();
  assert.match(text(get("notification")), /Provider unavailable/);
  const closeFailure = descend(get("notification")).find(
    (node) => node.tag === "button" && node.textContent === "知道了",
  );
  assert.ok(closeFailure, "a durable failed operation can be dismissed from its dialog");
  await closeFailure.events.click();
  assert.doesNotMatch(text(get("notification")), /Provider unavailable/);
  vm.runInContext('showDetail("request","r1")', context);
  assert.ok(
    descend(get("detail")).find(
      (node) => node.tag === "button" && node.textContent === "继续交付",
    ),
    "a consumed exact plan is not offered again; unified continue can propose the next plan",
  );
  assert.doesNotMatch(text(get("detail")), /批准并继续/);

  const beforeSingleFinalization = structuredClone(fixture.requests[0]);
  fixture.requests[0].stage = "WAITING_DELIVERY_FINALIZATION";
  fixture.requests[0].blocker =
    "原生 QA 与 Review 已通过，继续交付将复核现有证据并完成单仓需求。";
  fixture.requests[0].next_action = fixture.requests[0].blocker;
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  assert.match(text(get("detail")), /等待交付确认/);
  const finalizationFlow = vm.runInContext(
    "deliveryFlow(snapshot.requests[0])",
    context,
  );
  const currentDelivery = descend(finalizationFlow).find(
    (node) => node.className === "current",
  );
  assert.match(text(currentDelivery), /7\s+交付/);
  fixture.requests[0] = beforeSingleFinalization;
  await interval.fn();

  // A retained PLANNING checkpoint can request integration approval without
  // pretending the completed child has gone back to Coder/QA/Reviewer.
  const beforeIntegration = structuredClone(fixture.requests[0]);
  const beforeApprovalResult = storedOperations[1].result;
  fixture.requests[0].stage = "PLANNING";
  fixture.requests[0].blocker = null;
  storedOperations[1].result = {
    project_id: "project_fixture",
    delivery_id: "r1",
    checkpoint_sha256: "a".repeat(64),
    stage: "PLANNING",
    next_action: "请确认候选并批准一次补充验收。",
    approval: {
      kind: "joint_integration",
      plan_sha256: "e".repeat(64),
      title: "批准一次补充联合验收",
      facts: ["原有 3 次验收记录完整保留", "不会重新执行已完成仓库的 Coder、QA 或 Reviewer"],
    },
  };
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  assert.match(text(get("detail")), /批准一次补充联合验收/);
  const extraApproval = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "批准并继续",
  );
  assert.ok(extraApproval);
  await extraApproval.events.click();
  assert.deepEqual(submittedIntents.at(-1), {
    action: "CONTINUE_DELIVERY",
    project_id: "project_fixture",
    delivery_id: "r1",
    expected_checkpoint_sha256: "a".repeat(64),
    approved_plan_sha256: "e".repeat(64),
  });
  storedOperations.pop();
  submittedIntents.pop();
  storedOperations[1].result = beforeApprovalResult;
  fixture.requests[0] = beforeIntegration;
  await interval.fn();

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
  assert.equal(get("operations").hidden, true);
  assert.match(text(get("notification")), /交付运行时尚未就绪/);
  assert.ok(
    descend(get("notification")).find(
      (node) => node.tag === "button" && node.textContent === "前往设置",
    ),
  );
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

  fixture.requests[0].stage = "WAITING_PRODUCT_REPLY";
  fixture.requests[0].dialogue = [
    {
      sequence: 1,
      speaker: "user",
      text: "结算页需要支持新的折扣说明。",
      attachments: [
        {
          id: "requirement_attachment_" + "e".repeat(40),
          name: "checkout.png",
          media_type: "image/png",
          source_bytes: 2048,
          sha256: "f".repeat(64),
        },
      ],
    },
    {
      sequence: 2,
      speaker: "product",
      text: "折扣说明需要支持哪些端？\n是否需要兼容旧数据？",
      attachments: [],
    },
  ];
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  const detailOverview = descend(get("detail")).find(
    (node) => node.className === "request-detail-overview",
  );
  assert.ok(detailOverview, "Requirement identity is grouped into a stable overview");
  assert.equal(
    descend(detailOverview).find((node) => node.tag === "h2")?.textContent,
    "需求详情",
  );
  const productDialogue = descend(get("detail")).find(
    (node) => node.className === "detail-section product-dialogue",
  );
  assert.ok(productDialogue, "durable Product dialogue is rendered");
  assert.match(text(productDialogue), /你.*结算页需要支持新的折扣说明/);
  assert.match(text(productDialogue), /Product Agent.*折扣说明需要支持哪些端/);
  assert.match(text(productDialogue), /截图 · checkout.png · 2 KB/);
  const discussionForm = descend(get("detail")).find(
    (node) => node.className === "discussion-form",
  );
  assert.match(text(discussionForm), /回复 Product Agent/);
  assert.equal(
    descend(discussionForm).find((node) => node.tag === "h3")?.textContent,
    "回复 Product Agent",
    "the composer is subordinate to the shared Product discussion section",
  );
  const stageArtifacts = descend(get("detail")).find(
    (node) => node.className === "detail-section stage-artifacts",
  );
  assert.ok(
    stageArtifacts,
    "stage artifacts must be a separated detail section after Requirement actions",
  );
  assert.match(text(stageArtifacts), /阶段产物/);
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

  storedOperations = [];
  fixture.requests[0].stage = "PRODUCT_DISCOVERY";
  fixture.requests[0].dialogue = [fixture.requests[0].dialogue[0]];
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  const processingDialogue = descend(get("detail")).find(
    (node) => node.className === "detail-section product-dialogue",
  );
  assert.ok(processingDialogue, "Product processing keeps the discussion module visible");
  const processingComposer = descend(processingDialogue).find(
    (node) => node.className === "discussion-form",
  );
  assert.ok(
    processingComposer,
    "Product processing keeps the composer inside the same discussion module",
  );
  assert.equal(
    descend(get("detail")).some(
      (node) => node.className === "detail-section discussion-form",
    ),
    false,
    "dialogue history and composer must not be split by another detail divider",
  );
  assert.ok(
    descend(processingComposer).find(
      (node) => node.tag === "button" && node.textContent === "继续需求讨论",
    ),
    "an interrupted Product run uses a discussion-specific recovery action",
  );
  assert.equal(
    descend(get("detail")).some(
      (node) => node.tag === "button" && node.textContent === "继续交付",
    ),
    false,
    "Product discovery must not be presented as implementation delivery",
  );

  for (const [code, summary, expectedNext] of [
    ["MODEL_AUTHENTICATION_ERROR", "product / 知识检索意图: codex/test (high): authentication expired", /codex login/],
    ["MODEL_QUOTA_EXHAUSTED", "usage limit reached", /等待额度恢复/],
    ["MODEL_PROVIDER_UNAVAILABLE", "Codex CLI 无法启动 errno=2", /可执行文件/],
    ["MODEL_INVALID_OUTPUT", "ProductDraft 回复未通过结构校验", /结构化结果/],
    ["MANAGER_FAILURE", "Manager operation failed; inspect durable delivery facts.", /旧记录未保存具体失败原因/],
  ]) {
    storedOperations = [{
      operation_id: "operation_product_failure",
      status: "FAILED",
      updated_at: "2026-09-05T01:00:06Z",
      error_code: code,
      error_summary: summary,
      intent: { action: "PRODUCT_REPLY", project_id: "project_fixture", delivery_id: "r1" },
    }];
    await interval.fn();
    vm.runInContext('showDetail("request","r1")', context);
    const failures = descend(get("detail")).filter((node) => node.className.includes("product-failure"));
    assert.equal(failures.length, 1);
    assert.match(text(failures[0]), /失败原因/);
    assert.match(text(failures[0]), /下一步/);
    assert.match(text(failures[0]), expectedNext);
    assert.match(text(failures[0]), /operation_product_failure/);
    assert.match(text(failures[0]), /无需重新输入或新建需求/);
    if (code !== "MANAGER_FAILURE") assert.ok(text(failures[0]).includes(summary));
  }
  const continueDiscussion = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "继续需求讨论",
  );
  await continueDiscussion.events.click();
  assert.deepEqual(submittedIntents.at(-1), {
    action: "CONTINUE_DELIVERY",
    project_id: "project_fixture",
    delivery_id: "r1",
    expected_checkpoint_sha256: "a".repeat(64),
  });
  storedOperations[0].status = "RUNNING";
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  assert.equal(descend(get("detail")).some((node) => node.className.includes("product-failure")), false);
  storedOperations[0].status = "SUCCEEDED";
  fixture.requests[0].stage = "WAITING_PRODUCT_REPLY";
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  assert.equal(descend(get("detail")).some((node) => node.className.includes("product-failure")), false);
  fixture.requests[0].stage = "PRODUCT_DISCOVERY";

  storedOperations = [
    {
      operation_id: "operation_source_revision_drift",
      status: "FAILED",
      updated_at: "2026-09-05T01:00:06Z",
      error_code: "COMMAND_REJECTED",
      error_summary: "source revision drift: use a new requirement project",
      intent: {
        action: "PRODUCT_REPLY",
        project_id: "project_fixture",
        delivery_id: "r1",
        expected_checkpoint_sha256: "a".repeat(64),
      },
    },
  ];
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  const driftDetail = get("detail");
  assert.match(text(driftDetail), /代码版本已变化/);
  assert.doesNotMatch(
    text(driftDetail),
    /上次 Product Agent 执行已中断/,
    "source drift must not be presented as a resumable interrupted run",
  );
  assert.ok(
    descend(driftDetail).find(
      (node) => node.tag === "button" && node.textContent === "删除需求",
    ),
    "a pre-approval drifted Requirement can be retired from the Project view",
  );
  const recreateRequirement = descend(driftDetail).find(
    (node) =>
      node.tag === "button" && node.textContent === "基于当前代码新建需求",
  );
  await recreateRequirement.events.click();
  const recreateForm = descend(get("composer")).find(
    (node) => node.tag === "form" && node.className === "project-form",
  );
  assert.match(text(get("composer")), /基于当前代码新建需求/);
  assert.equal(
    descend(recreateForm).find((node) => node.tag === "input").value,
    malicious,
    "the replacement Requirement keeps the displayed name editable",
  );
  assert.match(text(recreateForm), /\/backend\/module-a/);
  assert.match(text(recreateForm), /\/frontend/);
  await recreateForm.events.submit({ preventDefault() {} });
  assert.deepEqual(submittedIntents.at(-1), {
    action: "CREATE_REQUIREMENT",
    project_id: "project_fixture",
    name: malicious,
    repository_roots: ["/backend/module-a", "/frontend"],
  });

  fixture.requests[0].stage = "READY_FOR_DISCUSSION";
  storedOperations = [
    {
      operation_id: "operation_product_reply",
      status: "RUNNING",
      updated_at: "2026-09-05T01:00:07Z",
      intent: {
        action: "PRODUCT_REPLY",
        project_id: "project_fixture",
        delivery_id: "r1",
        expected_checkpoint_sha256: "a".repeat(64),
      },
    },
  ];
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  const runningComposer = descend(get("detail")).find(
    (node) => node.className === "discussion-form",
  );
  assert.equal(
    descend(runningComposer).find((node) => node.tag === "textarea").disabled,
    true,
    "the composer stays visible but disabled while Product is replying",
  );
  assert.equal(
    descend(runningComposer).find(
      (node) => node.tag === "button" && node.textContent === "Product Agent 正在回复",
    ).disabled,
    true,
  );

  storedOperations = [];
  fixture.requests[0].stage = "WAITING_PRODUCT_APPROVAL";
  fixture.requests[0].checkpoint_sha256 = "b".repeat(64);
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  assert.match(text(get("detail")), /批准 ProductSpec 并开始交付/);
  assert.match(text(get("detail")), /继续讨论并修订/);

  fixture.requests[0].stage = "READY_FOR_DISCUSSION";
  fixture.requests[0].dialogue = [];
  fixture.requests[0].checkpoint_sha256 = "a".repeat(64);
  storedOperations = [];
  await interval.fn();
  vm.runInContext('showDetail("request","r1")', context);
  const editRequirement = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "编辑需求",
  );
  const deleteRequirement = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "删除需求",
  );
  assert.ok(editRequirement && deleteRequirement);
  await editRequirement.events.click();
  const editForm = descend(get("composer")).find(
    (node) => node.className === "project-form",
  );
  const editName = descend(editForm).find((node) => node.tag === "input");
  assert.equal(editName.value, malicious);
  assert.match(text(editForm), /\/backend\/module-a/);
  assert.match(text(editForm), /\/frontend/);
  editName.value = "更新后的需求";
  await editForm.events.submit({ preventDefault() {} });
  assert.deepEqual(submittedIntents.at(-1), {
    action: "UPDATE_REQUIREMENT",
    project_id: "project_fixture",
    delivery_id: "r1",
    expected_checkpoint_sha256: "a".repeat(64),
    name: "更新后的需求",
    repository_roots: ["/backend/module-a", "/frontend"],
  });

  const replacement = {
    ...structuredClone(fixture.requests[0]),
    id: "r-edited",
    title: "更新后的需求",
    checkpoint_sha256: "d".repeat(64),
  };
  fixture.requests = [replacement];
  storedOperations[0].status = "SUCCEEDED";
  storedOperations[0].updated_at = "2026-09-05T01:00:08Z";
  storedOperations[0].result = {
    project_id: "project_fixture",
    delivery_id: "r-edited",
    checkpoint_sha256: "d".repeat(64),
    stage: "READY_FOR_DISCUSSION",
    next_action: "Discuss the requirement.",
  };
  await interval.fn();
  assert.match(
    text(get("detail")),
    /更新后的需求/,
    "successful editing follows the replacement Requirement",
  );

  fixture.requests[0].stage = "BLOCKED";
  fixture.requests[0].blocker = "Waiting for a human decision.";
  fixture.requests[0].next_action = "Inspect the retained checkpoint.";
  await interval.fn();
  vm.runInContext('showDetail("request","r-edited")', context);
  const closeEdited = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "关闭需求",
  );
  await closeEdited.events.click();
  await descend(get("composer"))
    .find((node) => node.tag === "button" && node.textContent === "确认关闭")
    .events.click();
  assert.deepEqual(submittedIntents.at(-1), {
    action: "CLOSE_REQUIREMENT",
    project_id: "project_fixture",
    delivery_id: "r-edited",
    expected_checkpoint_sha256: "d".repeat(64),
  });
  assert.equal(
    vm.runInContext('requestGroup(snapshot.requests[0])', context),
    "blocked",
    "a queued close operation must not move a blocked Requirement to active",
  );

  storedOperations.at(-1).status = "SUCCEEDED";
  storedOperations.at(-1).result = {
    project_id: "project_fixture",
    delivery_id: "r-edited",
    checkpoint_sha256: "e".repeat(64),
    stage: "CLOSED",
    next_action: "Requirement closed by user.",
  };
  fixture.requests[0].stage = "CLOSED";
  fixture.requests[0].blocker = null;
  fixture.requests[0].checkpoint_sha256 = "e".repeat(64);
  await interval.fn();
  assert.equal(
    vm.runInContext('requestGroup(snapshot.requests[0])', context),
    "closed",
  );
  vm.runInContext('page="requests"; requestFilter="closed"; render()', context);
  assert.match(text(get("content")), /已关闭 1/);
  vm.runInContext('showDetail("request","r-edited")', context);
  const restartEdited = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "重新启动需求",
  );
  await restartEdited.events.click();
  await descend(get("composer"))
    .find(
      (node) => node.tag === "button" && node.textContent === "确认重新启动",
    )
    .events.click();
  assert.deepEqual(submittedIntents.at(-1), {
    action: "RESTART_REQUIREMENT",
    project_id: "project_fixture",
    delivery_id: "r-edited",
    expected_checkpoint_sha256: "e".repeat(64),
  });
  assert.equal(
    vm.runInContext('requestGroup(snapshot.requests[0])', context),
    "closed",
    "a queued restart operation must not pretend that delivery already resumed",
  );

  storedOperations.at(-1).status = "SUCCEEDED";
  storedOperations.at(-1).result = {
    project_id: "project_fixture",
    delivery_id: "r-edited",
    checkpoint_sha256: "f".repeat(64),
    stage: "BLOCKED",
    next_action: "Requirement restarted; continue delivery.",
  };
  fixture.requests[0].stage = "BLOCKED";
  fixture.requests[0].blocker = "Requirement restarted; continue delivery.";
  fixture.requests[0].checkpoint_sha256 = "f".repeat(64);
  await interval.fn();
  vm.runInContext('showDetail("request","r-edited")', context);
  const deleteEdited = descend(get("detail")).find(
    (node) => node.tag === "button" && node.textContent === "删除需求",
  );
  await deleteEdited.events.click();
  assert.match(text(get("composer")), /历史记录会保留/);
  const confirmDelete = descend(get("composer")).find(
    (node) => node.tag === "button" && node.textContent === "确认删除",
  );
  await confirmDelete.events.click();
  assert.deepEqual(submittedIntents.at(-1), {
    action: "DELETE_REQUIREMENT",
    project_id: "project_fixture",
    delivery_id: "r-edited",
    expected_checkpoint_sha256: "f".repeat(64),
  });
  assert.equal(
    vm.runInContext('requestGroup(snapshot.requests[0])', context),
    "blocked",
    "a queued delete operation must not move a blocked Requirement to active",
  );

  storedOperations.at(-1).status = "SUCCEEDED";
  storedOperations.at(-1).result = {
    project_id: "project_fixture",
    stage: "REQUIREMENT_DELETED",
    next_action: "Requirement removed from the current Project view.",
  };
  fixture.requests = [];
  await interval.fn();
  assert.doesNotMatch(text(get("content")), /更新后的需求/);
});
