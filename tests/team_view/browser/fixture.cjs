// Real CSS/layout and input regression suite. Requires Playwright and Chrome.
// See docs/ui-notification-interactions.md for the isolated test command.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const assets = path.resolve(__dirname, "../../../src/ai_software_engineer/team_view");
const operation = (status = "QUEUED", overrides = {}) => ({
  operation_id: "operation_fixture", status, updated_at: "2026-09-21T00:00:00Z",
  intent: { action: "CONTINUE_DELIVERY", project_id: "project_fixture", delivery_id: "request_fixture" },
  error_summary: status === "FAILED" ? "模型暂不可用" : null,
  ...overrides,
});
async function ui(t, options = {}) {
  const browser = await chromium.launch({ channel: process.env.ASE_UI_BROWSER_CHANNEL || "chrome", headless: true });
  t.after(() => browser.close());
  const page = await browser.newPage();
  page.setDefaultTimeout(3000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  t.after(() => assert.deepEqual(errors, [], "no unhandled browser errors"));
  const state = { ready: options.ready ?? true, operations: options.operations || [], reads: [] };
  const team = { schema_version: "v0.2", as_of: "2026-09-21T00:00:00Z", team_id: "team_fixture", team_name: "Fixture",
    selected_project_id: "project_fixture", projects: [{ id: "project_fixture", name: "Fixture project" }], agents: [], tasks: [],
    requests: [{ id: "request_fixture", title: "Fixture request", project_id: "project_fixture", stage: "READY_FOR_DISCUSSION",
      checkpoint_sha256: "a".repeat(64), scopes: [], documents: [], dialogue: [], next_action: "Start discussion" }] };
  const config = options.config || { schema_version: "v0.2", platform_root: "/fixture/platform", team_id: "team_fixture", team_name: "Fixture",
    team_knowledge_paths: [], database: { backend: "mysql", dsn_env: "ASE_MYSQL_DSN" }, model_routes: [], agent_model_routes: [],
    codex_executable: "codex", live_model_execution: false, console_port: 8765,
    execution_retry_policy: {
      product: {max_attempts: 20, max_transient_failures: 5},
      designer: {max_attempts: 3, max_transient_failures: 5},
      planner: {max_attempts: 3, max_transient_failures: 5},
      coder: {max_attempts: 3, max_transient_failures: 5},
      qa: {max_transient_failures: 5}, reviewer: {max_transient_failures: 5},
    } };
  // Poll explicitly to keep the race scenarios deterministic. All API traffic is fixtures.
  await page.addInitScript(() => { window.setInterval = () => 0; });
  await page.route("http://ui.test/**", async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    state.reads.push(pathname);
    if (pathname === "/api/v1/admin/projects" && route.request().method() === "POST")
      return route.fulfill({ json: { project_id: "project_fixture" } });
    const api = {
      "/api/v1/team": team,
      "/api/v1/console": { schema_version: "v0.2", team_id: "team_fixture", delivery_ready: state.ready },
      "/api/v1/operations": state.operations,
      "/api/v1/admin/settings": { settings_contract_version: options.settingsContractVersion ?? 1, config, config_path: "/fixture/production.json", config_source: "saved", restart_required: false, secret_status: [] },
      "/api/v1/admin/projects": team.projects,
      "/api/v1/admin/team/knowledge": [],
      "/api/v1/admin/team/knowledge/index": null,
    };
    if (Object.hasOwn(api, pathname)) return route.fulfill({ json: api[pathname] });
    const file = pathname === "/" ? "index.html" : pathname.slice(1);
    if (["index.html", "style.css", "app.js"].includes(file))
      return route.fulfill({ body: fs.readFileSync(path.join(assets, file)), contentType: file.endsWith("js") ? "text/javascript" : file.endsWith("css") ? "text/css" : "text/html" });
    return route.fulfill({ status: 404, json: { error: { message: "Unavailable fixture endpoint" } } });
  });
  await page.goto("http://ui.test/");
  await page.waitForFunction(() => snapshot !== null && !refreshing);
  return { page, state, team, tick: () => page.evaluate(() => refresh()),
    requests: () => page.locator("#nav-requests").click(),
    close: () => page.locator("#notification").getByRole("button", { name: "知道了", exact: true }).click(),
    draft: async () => {
      await page.getByRole("button", { name: "新建需求", exact: true }).click();
      await page.locator('#composer input[name="name"]').fill("保留正在编辑的需求");
      await page.locator('#composer input[name="name"]').evaluate((node) => { window.draftInput = node; });
    },
  };
}

module.exports = { ui, operation };
