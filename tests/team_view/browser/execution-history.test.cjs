// Focused browser contract for complete QA/Review/Coder execution history.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");

const entry = (taskId, index, kind = "state_event", details = {}) => ({
  id: `entry_${taskId}_${index}`,
  kind,
  occurred_at: `2026-09-21T00:${String(index).padStart(2, "0")}:00Z`,
  task_id: taskId,
  summary: kind === "artifact" ? "QA 报告 · FAIL" : `状态 · 第 ${index} 轮`,
  source_uri: `${kind}://${taskId}/${index}`,
  details,
});

test("one unchanged running operation follows design, planning and each native role during polling", async (t) => {
  const h = await ui(t);
  await h.requests();
  const request = h.team.requests[0];
  const active = operation("RUNNING", {intent: {action: "CONTINUE_DELIVERY", project_id: request.project_id,
    delivery_id: request.id, expected_checkpoint_sha256: "a".repeat(64)}});
  h.state.operations = [operation("SUCCEEDED", {operation_id: "history_old"}), active,
    operation("RUNNING", {operation_id: "foreign_project", intent: {...active.intent, project_id: "other_project"}})];
  request.checkpoint_sha256 = "b".repeat(64);
  request.execution = {state: "UNKNOWN", responsibility: "team", reason: "尚无执行器心跳。",
    next_action: "核验执行事实。", action_required: false};
  const original = JSON.stringify(active);
  const currentRow = h.page.locator("#detail .execution-history-entry").filter({hasText: "operation_fixture"});
  const oldRow = h.page.locator("#detail .execution-history-entry").filter({hasText: "history_old"});
  for (const [stage, status, role, phase] of [["DESIGNING", null, null, "技术设计"], ["PLANNING", null, null, "计划编排"],
    ["DELIVERING", "IMPLEMENTING", "coder", "实现"], ["DELIVERING", "QA", "qa", "测试"], ["DELIVERING", "REVIEW", "reviewer", "评审"]]) {
    request.stage = stage;
    h.team.tasks = status ? [{id: "task_current", project_id: request.project_id, request_id: request.id, title: "当前任务",
      status, terminal: false, last_activity: "2026-10-05T13:00:00Z", scope: {root: "/fixture", selected_paths: ["."]},
      role_queue: [{role, status: "RUNNING", lease_liveness: "LEASE_VALID"}], assignments: [], runs: [], documents: [], timeline: []}] : [];
    await h.tick();
    if (stage === "DESIGNING") {
      await h.page.evaluate(() => showDetail("request", "request_fixture"));
      await h.close();
      await currentRow.locator("details summary").click();
      await oldRow.evaluate(node => {window.oldOperationRow = node;});
    }
    assert.equal(await currentRow.locator("strong").first().innerText(), `当前阶段 · ${phase} · 执行中`);
    assert.match(await currentRow.innerText(), /发起操作 · 继续交付/);
    assert.match(await currentRow.innerText(), /发起操作时的需求版本摘要/);
    assert.equal(await currentRow.locator("details").evaluate(node => node.open), true, "expanded engineering details survive progress changes");
    assert.equal(await oldRow.evaluate(node => window.oldOperationRow === node), true, "unchanged sealed history retains its DOM");
    assert.doesNotMatch(await oldRow.innerText(), /当前阶段 ·/);
    assert.equal(JSON.stringify(active), original);
  }
  await currentRow.locator("details summary").click();
  assert.doesNotMatch(await currentRow.innerText(), /operation_fixture|a{64}|b{64}/);
  assert.match(await currentRow.innerText(), /排障信息（供工程人员使用）/);
  assert.equal(await h.page.locator("#detail .execution-history-entry").count(), 2);
  assert.equal(await h.page.locator("#notification").isVisible(), false, "acknowledged ACTIVE notice does not reopen at the next phase");
});

test("visible active notification follows phase while preserving its existing acknowledgement identity", async (t) => {
  const h = await ui(t);
  await h.requests();
  const request = h.team.requests[0];
  request.stage = "DESIGNING";
  h.state.operations = [operation("RUNNING")];
  await h.tick();
  const notification = h.page.locator("#notification");
  assert.match(await notification.innerText(), /当前阶段 · 技术设计 · 执行中/);
  request.stage = "PLANNING";
  await h.tick();
  assert.match(await notification.innerText(), /当前阶段 · 计划编排 · 执行中/);
  await h.close();
  request.stage = "INTEGRATING";
  await h.tick();
  assert.equal(await notification.isVisible(), false);
});

test("task detail renders every round with QA findings and Coder feedback lineage", async (t) => {
  const h = await ui(t);
  h.team.tasks.push({
    id: "delivery_history",
    project_id: "project_fixture",
    request_id: "request_fixture",
    task_id: "task_current_round",
    title: "完整返工历史",
    status: "REVIEW",
    checkpoint_stage: "REVIEW",
    terminal: false,
    scope: {root: "/fixture", selected_paths: ["."]},
    last_activity: "2026-09-21T00:12:00Z",
    next_action: "等待评审",
    history_task_ids: ["task_current_round", "task_old_round"],
    execution_history: [
      ...Array.from({length: 9}, (_, index) => entry("task_old_round", index + 1)),
      entry("task_old_round", 10, "artifact", {
        kind: "qa-report", status: "FAIL", artifact_sha256: "a".repeat(64),
        findings: [{finding_id: "finding_qa", severity: "MAJOR", message: "缺少空输入回归测试。", file: "src/example.py", line: 42, evidence_ids: ["ev_qa"]}],
      }),
      entry("task_current_round", 11, "artifact", {
        kind: "implementation-report", candidate_revision: "b".repeat(40),
        parent_artifact_ids: ["art_plan", "entry_task_old_round_10"], supersedes: "art_impl_old",
        changed_files: [{path: "src/example.py"}], tests_run: [{command: "pytest tests/example", status: "PASS", evidence_id: "ev_coder"}],
      }),
      entry("task_current_round", 12, "artifact", {
        kind: "review-report", verdict: "APPROVE", artifact_sha256: "c".repeat(64), findings: [],
      }),
    ],
    timeline: [entry("task_current_round", 12, "artifact", {kind: "review-report", verdict: "APPROVE", findings: []})],
    assignments: [], runs: [], documents: [],
  });
  await h.tick();
  await h.page.evaluate(() => showDetail("task", "delivery_history"));
  assert.equal(await h.page.locator(".execution-history-entry").count(), 12);
  const text = await h.page.locator(".task-detail-dialog").innerText();
  assert.match(text, /执行记录（完整历史）/);
  assert.match(text, /缺少空输入回归测试/);
  assert.match(text, /Coder 已接收上轮 QA\/Review 反馈/);
  assert.doesNotMatch(text, /task_old_round|task_current_round/);
  await h.page.getByText("任务工程详情", {exact: true}).click();
  assert.match(await h.page.locator(".task-detail-dialog").innerText(), /task_old_round/);
  assert.match(await h.page.locator(".task-detail-dialog").innerText(), /task_current_round/);
  assert.doesNotMatch(text, /b{40}/, "technical candidate identity is collapsed by default");
  await h.page.getByText("产物工程详情", {exact: true}).nth(1).click();
  assert.match(await h.page.locator(".task-detail-dialog").innerText(), /b{40}/);
});
