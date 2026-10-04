// Focused browser contract for complete QA/Review/Coder execution history.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui } = require("./fixture.cjs");

const entry = (taskId, index, kind = "state_event", details = {}) => ({
  id: `entry_${taskId}_${index}`,
  kind,
  occurred_at: `2026-09-21T00:${String(index).padStart(2, "0")}:00Z`,
  task_id: taskId,
  summary: kind === "artifact" ? "QA 报告 · FAIL" : `状态 · 第 ${index} 轮`,
  source_uri: `${kind}://${taskId}/${index}`,
  details,
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
