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
  const copy = firstField?.querySelector(".settings-field-copy");
  const control = firstField?.querySelector(".settings-field-control");
  return {
    sections: sections.map((section) => ({
      border: parseFloat(getComputedStyle(section).borderTopWidth),
      style: getComputedStyle(section).borderTopStyle,
    })),
    headingLeft: heading?.getBoundingClientRect().left ?? null,
    copyLeft: copy?.getBoundingClientRect().left ?? null,
    controlLeft: control?.getBoundingClientRect().left ?? null,
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  };
});

test("Agent help, horizontal primary row and exhausted fallback catalog remain usable", async (t) => {
  const h = await ui(t, { config: modelConfig() });
  await h.page.locator("#nav-settings").click();
  await h.page.getByRole("button", { name: /^模型路由/ }).click();
  const form = h.page.locator("#content .settings-form");
  const manager = form.locator('.agent-model-card[data-role="manager"]');
  assert.equal(await form.locator(".agent-model-role small").count(), 0,
    "Agent descriptions should not stretch summary rows");
  const help = manager.getByRole("button", { name: "Manager Agent说明" });
  await help.click();
  await form.getByRole("dialog", { name: "Manager Agent说明" }).getByText(/确定性能力/).waitFor();
  assert.equal(await manager.evaluate((node) => node.open), false,
    "opening a summary help popover must not expand the Agent card");
  await h.page.keyboard.press("Escape");

  const designer = form.locator('.agent-model-card[data-role="designer"]');
  await designer.locator(":scope > summary").click();
  const primary = await designer.evaluate((card) => {
    const row = card.querySelector(".agent-model-detail > .settings-field-row");
    if (!row) return null;
    const label = row.querySelector(".settings-field-copy").getBoundingClientRect();
    const select = row.querySelector(".single-select > summary").getBoundingClientRect();
    const control = row.querySelector(".settings-field-control").getBoundingClientRect();
    return { labelRight: label.right, selectLeft: select.left,
      labelCenter: label.top + label.height / 2, selectCenter: select.top + select.height / 2 };
  });
  assert.ok(primary && primary.labelRight < primary.selectLeft,
    "primary label and model selector must share a horizontal row");
  assert.ok(Math.abs(primary.labelCenter - primary.selectCenter) <= 2,
    `primary label and selector are vertically aligned: ${JSON.stringify(primary)}`);

  assert.equal(await designer.locator(".agent-fallback-row").count(), 2);
  const exhaustedAdd = designer.locator(".agent-fallback-add");
  await exhaustedAdd.locator("summary").click();
  await exhaustedAdd.getByRole("option", { name: /新增可用模型路由/ }).click();
  const routeRows = form.locator(".model-route-disclosure");
  assert.equal(await routeRows.count(), 4);
  assert.deepEqual(await routeRows.evaluateAll((rows) => rows.map((row) => row.open)),
    [false, false, false, true]);
  const created = routeRows.last();
  await created.getByRole("textbox", { name: "Provider" }).fill("new-provider");
  await created.getByRole("textbox", { name: "Model" }).fill("new-model");
  await created.getByLabel("启用此路由").check();
  const addFallback = designer.locator(".agent-fallback-add");
  await addFallback.locator("summary").click();
  await addFallback.getByRole("option", { name: /^new-provider \/ new-model/ }).click();
  assert.equal(await designer.locator(".agent-fallback-row").count(), 3);
});

test("model catalog starts closed and only a newly added route opens", async (t) => {
  const h = await ui(t, { config: modelConfig() });
  await h.page.locator("#nav-settings").click();
  await h.page.getByRole("button", { name: /^模型路由/ }).click();
  const rows = h.page.locator("#content .model-route-disclosure");
  assert.deepEqual(await rows.evaluateAll((items) => items.map((item) => item.open)),
    [false, false, false]);
  await h.page.getByRole("button", { name: "添加路由", exact: true }).click();
  assert.deepEqual(await rows.evaluateAll((items) => items.map((item) => item.open)),
    [false, false, false, true]);
});

test("stale Settings service blocks saves and explains the required restart", async (t) => {
  const h = await ui(t, { settingsContractVersion: 0 });
  const writes = [];
  h.page.on("request", (request) => {
    if (request.url().endsWith("/api/v1/admin/settings") && request.method() === "PUT")
      writes.push(request);
  });
  await h.page.locator("#nav-settings").click();
  await h.page.getByText(/服务版本不匹配.*重启 Web Console/).waitFor();
  await h.page.evaluate(() => { settingsDraft.codex_executable = "/new/codex"; });
  await h.page.locator("#content .settings-form button[type=submit]").click();
  await h.page.getByRole("alertdialog").getByText(/重启 Web Console 后刷新页面/).waitFor();
  assert.equal(writes.length, 0);
});

test("Settings pages share one aligned section grid across desktop and narrow widths", async (t) => {
  const h = await ui(t);
  await h.page.locator("#nav-settings").click();
  const form = h.page.locator("#content .settings-form");
  await form.waitFor();
  await h.page.getByText("允许调用真实模型", { exact: true }).waitFor();
  assert.equal(await h.page.locator("#content .settings-page-title-row .settings-help-trigger").count(), 1);
  assert.equal(await form.locator(".settings-section-header .settings-help-trigger").count(), 3);
  const modelSwitchHelp = form.getByRole("button", { name: "允许调用真实模型说明" });
  assert.equal(await modelSwitchHelp.count(), 1);
  assert.equal(await modelSwitchHelp.getAttribute("aria-expanded"), "false");
  await modelSwitchHelp.focus();
  await h.page.keyboard.press("Enter");
  const modelSwitchPanel = form.getByRole("dialog", { name: "允许调用真实模型说明" });
  await modelSwitchPanel.getByText("全局安全开关；关闭后拒绝所有模型任务。修改后需要重启。").waitFor();
  assert.equal(await modelSwitchHelp.getAttribute("aria-expanded"), "true");
  await h.page.keyboard.press("Escape");
  assert.equal(await modelSwitchPanel.isVisible(), false);
  assert.equal(await modelSwitchHelp.getAttribute("aria-expanded"), "false");
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
      assert.ok(layout.controlLeft > layout.copyLeft,
        `${width}px: Controls stay in the field value column`);
    }
    assert.equal(layout.overflow, false, `${width}px: Basic settings does not overflow`);
  }

  await h.page.getByRole("button", { name: "MySQL", exact: true }).click();
  await h.page.setViewportSize({ width: 1440, height: 1000 });
  const mysql = await geometry(form);
  assert.equal(mysql.sections.length, 2);
  assert.equal(await form.locator(".settings-section-header .settings-help-trigger").count(), 2);
  assert.ok(Math.abs(mysql.headingLeft - mysql.copyLeft) <= 1);
  assert.ok(mysql.controlLeft > mysql.copyLeft);
  const environmentName = form.getByRole("textbox", { name: "启动变量" });
  assert.equal(await environmentName.count(), 1);
  assert.equal(await environmentName.isEnabled(), false);
  assert.equal(await environmentName.inputValue(), "ASE_MYSQL_DSN");
  const mysqlAlignment = await form.evaluate((node) => {
    const control = node.querySelector(".settings-field-control").getBoundingClientRect();
    const action = node.querySelector(".settings-action-row").getBoundingClientRect();
    return { control: control.left, action: action.left };
  });
  assert.ok(Math.abs(mysqlAlignment.control - mysqlAlignment.action) <= 1);
  const mysqlHelp = form.getByRole("button", { name: "MySQL DSN说明" });
  await mysqlHelp.click();
  await form.getByRole("dialog", { name: "MySQL DSN说明" })
    .getByText("留空表示保留已保存值；输入新 DSN 才会替换。")
    .waitFor();
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
  assert.equal(await form.locator(".settings-section-header .settings-help-trigger").count(), 3);
  const proxy = form.getByRole("textbox", { name: "Codex CLI 本地代理地址" });
  assert.equal(await proxy.count(), 1);
  await proxy.fill("http://127.0.0.1:8317/v1");
  assert.equal(await proxy.inputValue(), "http://127.0.0.1:8317/v1");
  assert.equal(await h.page.evaluate(() => settingsDraft.codex_cli_proxy_base_url),
    "http://127.0.0.1:8317/v1");
  assert.equal(await h.page.evaluate(() => settingsDraft.model_routes[0].connection_mode),
    "direct", "adding a proxy URL must not silently switch an existing CLI route");
  await form.locator(".model-route-disclosure").first().locator(":scope > summary").click();
  const connection = form.locator('[data-key="model-route-0-connection"]');
  await connection.locator("summary").click();
  await connection.getByRole("option", { name: "CLIProxyAPI（本地代理）" }).click();
  assert.equal(await h.page.evaluate(() => settingsDraft.model_routes[0].connection_mode), "proxy");
  const proxyKey = form.getByRole("textbox", { name: "代理 API Key", exact: true });
  assert.equal(await proxyKey.getAttribute("type"), "password");
  await proxyKey.fill("test-proxy-secret");

  const response = form.locator(".model-route-disclosure").nth(2);
  if (!(await response.evaluate((node) => node.open)))
    await response.locator(":scope > summary").click();
  await h.page.waitForFunction(() =>
    document.querySelectorAll(".model-route-disclosure")[2]?.open);
  const responseAlignment = await response.evaluate((node) => {
    const fields = Array.from(node.querySelectorAll(".settings-route-field"));
    const key = fields.find((field) => field.querySelector("strong")?.textContent === "API Key");
    const image = fields.find((field) => field.querySelector("strong")?.textContent === "支持图片输入");
    const keyInput = key.querySelector("input").getBoundingClientRect();
    const imageInput = image.querySelector("input").getBoundingClientRect();
    return {
      keyTop: key.getBoundingClientRect().top,
      imageTop: image.getBoundingClientRect().top,
      keyCenter: keyInput.top + keyInput.height / 2,
      imageCenter: imageInput.top + imageInput.height / 2,
    };
  });
  assert.ok(Math.abs(responseAlignment.keyTop - responseAlignment.imageTop) <= 1);
  assert.ok(Math.abs(responseAlignment.keyCenter - responseAlignment.imageCenter) <= 2,
    JSON.stringify(responseAlignment));
  const imageHelp = response.locator('.settings-help-trigger[aria-label="支持图片输入说明"]');
  assert.equal(await imageHelp.count(), 1);
  await imageHelp.click();
  const imagePanel = form.getByRole("dialog", { name: "支持图片输入说明" });
  await imagePanel.getByText(/Codex CLI 默认支持/).waitFor();
  const helpBounds = await imagePanel.boundingBox();
  assert.ok(helpBounds.x >= 0 && helpBounds.x + helpBounds.width <= 1440);
  await imagePanel.getByRole("button", { name: "关闭" }).click();
  assert.equal(await imagePanel.isVisible(), false);

  const designer = form.locator('.agent-model-card[data-role="designer"]');
  if (!(await designer.evaluate((node) => node.open)))
    await designer.locator(":scope > summary").click();
  await h.page.waitForFunction(() =>
    document.querySelector('.agent-model-card[data-role="designer"]')?.open);
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
    widths.length === 3 && widths.every((width) => Math.abs(width - 36) <= 1)));
  assert.equal(await designer.locator('.agent-model-detail > .settings-field-row .single-select-value').textContent(),
    "gpt-5.6-terra");
  assert.match(await designer.locator('.agent-primary-meta').textContent(),
    /codex · high · Codex CLI/);
  assert.equal(await designer.getByRole('button', { name: '上移备用 1' }).isDisabled(), true);
  assert.equal(await designer.getByRole('button', { name: '下移备用 2' }).isDisabled(), true);
  const product = form.locator('.agent-model-card[data-role="product"]');
  if (!(await product.evaluate((node) => node.open)))
    await product.locator(":scope > summary").click();
  await h.page.waitForFunction(() =>
    document.querySelector('.agent-model-card[data-role="product"]')?.open);

  for (const width of [1440, 768, 390]) {
    await h.page.setViewportSize({ width, height: 1000 });
    const detailAlignment = await form.evaluate(() => {
      const designer = document.querySelector('.agent-model-card[data-role="designer"]');
      const product = document.querySelector('.agent-model-card[data-role="product"]');
      return {
        primary: designer.querySelector('.agent-model-detail > .settings-field-row .single-select').getBoundingClientRect().left,
        fallback: designer.querySelector('.agent-fallback-row').getBoundingClientRect().left,
        addPrimary: product.querySelector('.agent-model-detail > .settings-field-row .single-select').getBoundingClientRect().left,
        addFallback: product.querySelector('.agent-fallback-add').getBoundingClientRect().left,
      };
    });
    assert.ok(detailAlignment.primary >= detailAlignment.fallback && detailAlignment.primary - detailAlignment.fallback <= 122,
      `${width}px: Primary and fallback groups keep a bounded aligned indent: ${JSON.stringify(detailAlignment)}`);
    assert.ok(Math.abs(detailAlignment.addPrimary - detailAlignment.addFallback) <= 1,
      `${width}px: Primary and add-fallback controls share their model-control edge: ${JSON.stringify(detailAlignment)}`);
    const sectionHelp = form.getByRole("button", { name: "Codex CLI 连接说明" });
    await sectionHelp.click();
    const sectionPanel = form.getByRole("dialog", { name: "Codex CLI 连接说明" });
    const bounds = await sectionPanel.boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width,
      `${width}px: Section explanation remains within viewport`);
    await h.page.keyboard.press("Escape");
    await imageHelp.click();
    const fieldBounds = await imagePanel.boundingBox();
    assert.ok(fieldBounds.x >= 0 && fieldBounds.x + fieldBounds.width <= width,
      `${width}px: Field explanation remains within viewport`);
    await h.page.keyboard.press("Escape");
    const overflow = await form.evaluate(() =>
      document.documentElement.scrollWidth > window.innerWidth);
    assert.equal(overflow, false, `${width}px: Model Routing does not overflow`);
  }
  const addFallback = product.locator('.agent-fallback-add');
  await addFallback.locator('summary').click();
  await addFallback.getByRole('option', { name: /^deepseek \/ deepseek-v4/ }).click();
  assert.equal(await product.locator('.agent-fallback-row').count(), 1,
    'the visually compact add control still updates the exact Agent fallback policy');
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
