const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ui } = require("./fixture.cjs");

const retryPolicy = {
  product: { max_attempts: 20, max_transient_failures: 5 },
  designer: { max_attempts: 3, max_transient_failures: 5 },
  planner: { max_attempts: 3, max_transient_failures: 5 },
  coder: { max_attempts: 3, max_transient_failures: 5 },
  qa: { max_transient_failures: 5 },
  reviewer: { max_transient_failures: 5 },
};

const route = (provider, model, reasoningEffort, kind = "codex_cli") => ({
  provider,
  model,
  kind,
  endpoint: kind === "responses" ? "https://example.invalid/v1/responses" : null,
  api_key_env: kind === "responses" ? `${provider.toUpperCase()}_API_KEY` : null,
  reasoning_effort: reasoningEffort,
  image_input: kind === "responses",
  enabled: true,
});

const modelConfig = () => {
  const routes = [
    route("codex", "gpt-5.6-terra", "high"),
    route("codex", "gpt-5.6-terra", "medium"),
    route("deepseek", "deepseek-v4", "high", "responses"),
  ];
  const reference = ({ provider, model, reasoning_effort }) => ({
    provider,
    model,
    reasoning_effort,
  });
  return {
    schema_version: "v0.2",
    platform_root: "/fixture/platform",
    team_id: "team_fixture",
    team_name: "Fixture",
    team_knowledge_paths: [],
    database: { backend: "mysql", dsn_env: "ASE_MYSQL_DSN" },
    model_routes: routes,
    agent_model_routes: [
      { role: "designer", routes: routes.map(reference) },
    ],
    codex_executable: "codex",
    codex_cli_proxy_base_url: null,
    codex_cli_proxy_api_key_env: null,
    live_model_execution: true,
    console_port: 8765,
    execution_retry_policy: retryPolicy,
  };
};

const geometry = (locator) => locator.evaluate((form) => {
  const sections = Array.from(form.querySelectorAll(".settings-section"));
  const firstFieldSection = sections.find((section) =>
    section.querySelector(".settings-field-row"));
  const firstField = firstFieldSection?.querySelector(".settings-field-row");
  const heading = firstFieldSection?.querySelector(".settings-section-title");
  const description = firstFieldSection?.querySelector(
    ".settings-section-description",
  );
  const copy = firstField?.querySelector(".settings-field-copy");
  const control = firstField?.querySelector(".settings-field-control");
  return {
    sections: sections.map((section) => ({
      border: parseFloat(getComputedStyle(section).borderTopWidth),
      style: getComputedStyle(section).borderTopStyle,
    })),
    headingLeft: heading?.getBoundingClientRect().left ?? null,
    descriptionLeft: description?.getBoundingClientRect().left ?? null,
    copyLeft: copy?.getBoundingClientRect().left ?? null,
    controlLeft: control?.getBoundingClientRect().left ?? null,
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  };
});

test("Settings pages share one aligned section grid across desktop and narrow widths", async (t) => {
  const h = await ui(t);
  await h.page.locator("#nav-settings").click();
  const form = h.page.locator("#content .settings-form");
  await form.waitFor();
  await h.page.getByText("允许调用真实模型", { exact: true }).waitFor();
  await h.page.getByText(
    "全局安全开关；关闭后拒绝所有模型任务。修改后需要重启。",
    { exact: true },
  ).waitFor();
  assert.equal(await form.getByText(/模拟执行/).count(), 0);

  for (const width of [1440, 768, 390]) {
    await h.page.setViewportSize({ width, height: 1000 });
    const layout = await geometry(form);
    assert.equal(layout.sections.length, 3);
    assert.ok(layout.sections.every((section) =>
      section.border >= 1 && section.style === "solid"));
    if (width >= 600) {
      assert.ok(Math.abs(layout.headingLeft - layout.copyLeft) <= 1,
        `${width}px: Section titles and field labels share the left baseline`);
      assert.ok(Math.abs(layout.descriptionLeft - layout.controlLeft) <= 1,
        `${width}px: Section descriptions and controls share the right baseline`);
    }
    assert.equal(layout.overflow, false, `${width}px: Basic settings does not overflow`);
  }

  await h.page.getByRole("button", { name: "MySQL", exact: true }).click();
  await h.page.setViewportSize({ width: 1440, height: 1000 });
  const mysql = await geometry(form);
  assert.equal(mysql.sections.length, 2);
  assert.ok(Math.abs(mysql.headingLeft - mysql.copyLeft) <= 1);
  assert.ok(Math.abs(mysql.descriptionLeft - mysql.controlLeft) <= 1);
  const environmentName = form.getByRole("textbox", { name: "启动变量" });
  assert.equal(await environmentName.count(), 1);
  assert.equal(await environmentName.isEnabled(), false);
  assert.equal(await environmentName.inputValue(), "ASE_MYSQL_DSN");
  const mysqlAlignment = await form.evaluate((node) => {
    const control = node.querySelector(".settings-field-control").getBoundingClientRect();
    const action = node.querySelector(".settings-action-row").getBoundingClientRect();
    const note = node.querySelector(".settings-section-note").getBoundingClientRect();
    return { control: control.left, action: action.left, note: note.left };
  });
  assert.ok(Math.abs(mysqlAlignment.control - mysqlAlignment.action) <= 1);
  assert.ok(Math.abs(mysqlAlignment.control - mysqlAlignment.note) <= 1);
});

test("Model routing uses compact disclosures and aligned fallback actions", async (t) => {
  const h = await ui(t, { config: modelConfig() });
  await h.page.locator("#nav-settings").click();
  await h.page.locator("#content .settings-form").waitFor();
  await h.page.getByRole("button", { name: /^模型路由/ }).click();
  const form = h.page.locator("#content .settings-form");
  assert.equal(await form.locator(".model-route-disclosure").count(), 3);
  assert.equal(await form.locator(".agent-model-card").count(), 7);
  assert.equal(await form.locator(".settings-section").count(), 3);
  const proxy = form.getByRole("textbox", { name: "Codex CLI 本地代理地址" });
  assert.equal(await proxy.count(), 1);
  await proxy.fill("http://127.0.0.1:8317/v1");
  assert.equal(await proxy.inputValue(), "http://127.0.0.1:8317/v1");
  assert.equal(await h.page.evaluate(() => settingsDraft.codex_cli_proxy_base_url),
    "http://127.0.0.1:8317/v1");
  assert.equal(await h.page.evaluate(() => settingsDraft.model_routes[0].connection_mode),
    "direct", "adding a proxy URL must not silently switch an existing CLI route");
  const connection = form.locator('[data-key="model-route-0-connection"]');
  await connection.locator("summary").click();
  await connection.getByRole("option", { name: "CLIProxyAPI（本地代理）" }).click();
  assert.equal(await h.page.evaluate(() => settingsDraft.model_routes[0].connection_mode), "proxy");
  const proxyKey = form.getByLabel("代理 API Key");
  assert.equal(await proxyKey.getAttribute("type"), "password");
  await proxyKey.fill("test-proxy-secret");

  const designer = form.locator('.agent-model-card[data-role="designer"]');
  await designer.locator(":scope > summary").click();
  const fallbackRows = designer.locator(".agent-fallback-row");
  assert.equal(await fallbackRows.count(), 2);
  const actionColumns = await fallbackRows.evaluateAll((rows) => rows.map((row) => {
    const actions = row.querySelector(".agent-fallback-actions").getBoundingClientRect();
    const buttons = Array.from(row.querySelectorAll(".agent-fallback-actions button"));
    return {
      left: actions.left,
      widths: buttons.map((button) => button.getBoundingClientRect().width),
    };
  }));
  assert.ok(Math.abs(actionColumns[0].left - actionColumns[1].left) <= 1);
  assert.ok(actionColumns.every(({ widths }) =>
    widths.length === 3 && Math.max(...widths) - Math.min(...widths) <= 1));

  for (const width of [1440, 768, 390]) {
    await h.page.setViewportSize({ width, height: 1000 });
    const overflow = await form.evaluate(() =>
      document.documentElement.scrollWidth > window.innerWidth);
    assert.equal(overflow, false, `${width}px: Model Routing does not overflow`);
  }
  const submission = h.page.waitForRequest((request) =>
    request.url().endsWith("/api/v1/admin/settings") && request.method() === "PUT");
  await form.getByRole("button", { name: "保存设置" }).click();
  const submitted = (await submission).postDataJSON();
  assert.equal(submitted.config.codex_cli_proxy_base_url,
    "http://127.0.0.1:8317/v1");
  assert.equal(submitted.config.codex_cli_proxy_api_key_env,
    "ASE_CODEX_PROXY_API_KEY");
  assert.equal(submitted.config.model_routes[0].connection_mode, "proxy");
  assert.deepEqual(submitted.runtime_variables.find((item) =>
    item.environment_name === "ASE_CODEX_PROXY_API_KEY"), {
    environment_name: "ASE_CODEX_PROXY_API_KEY", value: "test-proxy-secret",
  });
  assert.equal(JSON.stringify(submitted.config).includes("test-proxy-secret"), false);
});
