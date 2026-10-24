const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {supportedActions} = require("./console-capabilities-fixture.cjs");

class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.events = {}; this.dataset = {}; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute() {}
  addEventListener(key, callback) { this.events[key] = callback; }
  get classList() { return {add: () => {}}; }
}
const descendants = node => [node, ...node.children.filter(child => typeof child !== "string").flatMap(descendants)];
const text = node => descendants(node).map(child => child.textContent).join(" ");
const button = (node, name) => descendants(node).find(child => child.tagName === "BUTTON" && child.textContent === name);

function fixture(version = 11) {
  const scope = {team_id: "team_current", project_id: "project_current", repository_id: "repository_current", repository_root: "/fixture/repository"};
  const request = {id: "request_current", title: "原需求", project_id: scope.project_id, checkpoint_sha256: "a".repeat(64), stage: "BLOCKED",
    scopes: [{delivery_id: "delivery_current"}], blocker: "旧 SchemaVersionError", execution: {state: "WAITING", reason: "旧工程阻塞"}};
  const step = {work_item_id: "work_current", role: "coder", attempt: 10, status: "RUNNING", lease_liveness: "LEASE_EXPIRED"};
  const task = {id: "delivery_current", task_id: "task_current", request_id: request.id, project_id: scope.project_id, status: "IMPLEMENTING",
    terminal: true, checkpoint_stage: "BLOCKED", task_revision: 11, task_intent_sha256: "b".repeat(64), scope: {root: scope.repository_root},
    blocker: "旧 SchemaVersionError", role_queue: [step]};
  const input = {task_id: task.task_id, run_id: "run_original_010", role: "coder", attempt: 10, source_revision: "c".repeat(40), context_manifest_id: "ctx_" + "d".repeat(64)};
  const original = {request: input, work_item_id: step.work_item_id, checkpoint_sequence: 11, start_sha256: "1".repeat(64)};
  const report = {kind: "implementation-report", schema_version: "v1.0", source_revision: "e".repeat(40), context_manifest_id: input.context_manifest_id,
    producer: {run_id: input.run_id, agent_id: "agent_coder"}, content: {commit_sha: "e".repeat(40)}};
  const proof = {kind: "rejected_candidate_output", rejection_reason: "unsupported_schema_version", rejected_supported_version: "v0.1", publication_absent: true,
    task: {id: task.task_id, status: "IMPLEMENTING"}, task_revision: 11, task_intent_sha256: task.task_intent_sha256, scope,
    proof_sha256: "2".repeat(64), candidate_revision: "e".repeat(40), candidate_parent_revision: input.source_revision,
    outcome: {start: original, outcome_sha256: "3".repeat(64), result: {...input, status: "SUCCEEDED", artifact: report}},
    capture_start: {request: input, task_revision: 11, start_sha256: "4".repeat(64), worktree_path: "/fixture/coder",
      claim: {work_item: {id: step.work_item_id}, assignment: {agent_id: "agent_coder"}}},
    capture_stop: {task_id: task.task_id, run_id: input.run_id, capture_start_sha256: "4".repeat(64), output_present: true,
      process_stop: {kind: "completed", returncode: 0, session_proof: {proof_scope: "owned_session_empty", proof_sha256: "5".repeat(64)}}},
    complete_capture: {capture_sha256: "6".repeat(64)}};
  const bound = {project_id: request.project_id, delivery_id: request.id, expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id,
    expected_task_intent_sha256: task.task_intent_sha256, expected_task_revision: 11, expected_work_item_id: step.work_item_id, expected_source_revision: input.source_revision};
  const plan = {purpose: "rejected_candidate_rescue", plan_sha256: "7".repeat(64), input_mode: "preserve_draft", conflicted: false,
    target_base_ref: input.source_revision, prepared_source_revision: proof.candidate_revision,
    dirty_capture: {source_revision: proof.candidate_revision, worktree_path: "/fixture/coder", patch: "", mutations: []},
    complete_capture: {source_revision: proof.candidate_revision, base_revision: input.source_revision, worktree_path: "/fixture/coder", capture_sha256: "6".repeat(64)},
    facts: {scope, task: {id: task.task_id, base_ref: input.source_revision}, task_revision: 11, work_item_id: step.work_item_id,
      rejected_candidate_output: proof, continuation: {retry_cause: "rejected_candidate_output", rejected_candidate_output_sha256: proof.proof_sha256,
        current_attempt: 10, next_execution_attempt: 11, original_run_id: input.run_id, current_invocation_start_sha256: original.start_sha256,
        current_invocation_outcome_sha256: proof.outcome.outcome_sha256}}};
  const operation = {operation_id: "prepare", status: "SUCCEEDED", updated_at: "2026-10-25T00:00:00Z", intent: {...bound,
    action: "PROPOSE_EXECUTION_BASELINE", purpose: "rejected_candidate_rescue", input_mode: "preserve_draft"},
    result: {project_id: request.project_id, delivery_id: request.id, checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}};
  const data = {scope, request, step, task, proof, plan, operation, bound, version};
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, data, supportedActions});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  const run = code => vm.runInContext(code, context);
  run(`snapshot = {team_id: data.scope.team_id, selected_project_id: data.scope.project_id, projects: [], agents: [], tasks: [data.task], requests: [data.request]};
    consoleTeamId = data.scope.team_id; consoleAvailable = true; consoleDeliveryReady = true; operationsAvailable = true;
    consoleOperationContractVersion = data.version; consoleSupportedActions = [...supportedActions]; operations = [data.operation];
    globalThis.submitted = []; submitOperation = async intent => {submitted.push(intent); return {};};
    renderDetail = () => {}; renderNotification = () => {};`);
  return {run, ...data, panel: () => run(`globalThis.panel = document.createElement("section"); appendEngineeringRejectedCandidateRescue(panel, data.request); panel`)};
}

test("exact existing candidate plan remains visible above historical BLOCKED projection", async () => {
  const h = fixture(); const panel = h.panel();
  assert.match(text(panel), /候选报告恢复待确认/);
  assert.match(text(panel), /原成功调用|原 Coder 已真实完成/);
  assert.match(text(panel), /产品范围、原代码基线和项目规范保持/);
  assert.match(text(panel), /独立 QA 和 Review/);
  assert.equal(h.run("engineeringBaselineFacts(data.request, data.task, data.step)"), null, "old family remains closed");
  assert.equal(h.run("requestNodeExecution(data.request).status"), "REJECTED_CANDIDATE_APPROVAL");
  assert.match(text(h.run("requestBlockerSection(data.request)")), /当前操作以已核验的精确候选恢复方案为准/);
  await button(panel, "批准保留候选，保持暂停").events.click();
  assert.equal(h.run("submitted[0].expected_plan_sha256"), h.plan.plan_sha256);
  assert.equal(h.run("submitted[0].continuation_mode"), "pause");
  assert.equal(h.run('Object.hasOwn(submitted[0], "target_base_ref")'), false);
});

test("rechecking the exact known proposal is target-free and never changes input mode", async () => {
  const h = fixture(); const panel = h.panel();
  await button(panel, "重新检查候选恢复").events.click();
  assert.equal(h.run("submitted[0].purpose"), "rejected_candidate_rescue");
  assert.equal(h.run("submitted[0].input_mode"), "preserve_draft");
  assert.equal(h.run('Object.hasOwn(submitted[0], "target_base_ref")'), false);
});

test("stale candidate facts, identity, stop, budget and scope refuse old approval", async () => {
  for (const mutation of [
    'data.task.status = "DONE"', 'data.request.stage = "CLOSED"', 'data.task.task_revision = 12',
    'data.request.checkpoint_sha256 = "f".repeat(64)', 'data.task.task_intent_sha256 = "f".repeat(64)',
    'data.step.lease_liveness = "LEASE_VALID"', 'data.step.status = "CLOSED"', 'data.step.attempt = 11',
    'data.proof.scope.team_id = "team_other"', 'data.plan.facts.native_rule_change = {}',
    'data.proof.outcome.result.status = "FAILED"', 'data.proof.outcome.result.artifact.schema_version = "v0.1"',
    'data.proof.capture_stop.output_present = false', 'delete data.proof.capture_stop.process_stop.session_proof',
    'data.proof.capture_stop.process_stop.returncode = 1', 'data.proof.candidate_parent_revision = "f".repeat(40)',
    'data.plan.prepared_source_revision = "f".repeat(40)', 'data.plan.target_base_ref = "f".repeat(40)',
    'data.plan.dirty_capture.mutations = [{}]', 'data.plan.facts.continuation.reservation_already_applied = true',
    'data.plan.facts.continuation.next_execution_attempt = 10', 'data.proof.publication_absent = false',
    'data.operation.intent.target_base_ref = "f".repeat(40)', 'snapshot.selected_project_id = "project_other"',
  ]) {
    const h = fixture(); const panel = h.panel(); h.run(mutation);
    await button(panel, "批准保留候选，保持暂停").events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});

test("unsupported server or withdrawn capability displays a review without submitting", async () => {
  const h = fixture(10); const panel = h.panel();
  assert.match(text(panel), /当前服务不支持/);
  assert.equal(button(panel, "批准保留候选，保持暂停"), undefined);
  const current = fixture(); const old = current.panel();
  current.run('consoleSupportedActions = consoleSupportedActions.filter(action => action !== "EXECUTE_EXECUTION_BASELINE")');
  await button(old, "批准保留候选，保持暂停").events.click();
  assert.equal(current.run("submitted.length"), 0);
});

test("expired lease alone cannot produce a recovery proposal or unhide an old family", () => {
  const h = fixture(); h.run("operations = []");
  assert.equal(h.panel().children.length, 0);
  assert.equal(h.run("engineeringBaselineFacts(data.request, data.task, data.step)"), null);
});

test("purpose labels describe retained candidate report recovery without product baseline changes", () => {
  const h = fixture();
  assert.equal(h.run("operationActionLabel(data.operation)"), "检查候选报告恢复");
  assert.match(h.run("operationPurpose(data.operation)"), /已有候选/);
  assert.equal(h.run(`operationActionLabel({intent:{action:"EXECUTE_EXECUTION_BASELINE",purpose:"rejected_candidate_rescue",continuation_mode:"pause"}})`), "批准保留候选，保持暂停");
});

function pausedFixture() {
  const h = fixture();
  h.run(`data.operation.intent = {...data.operation.intent, action: "EXECUTE_EXECUTION_BASELINE", continuation_mode: "pause", expected_plan_sha256: data.plan.plan_sha256};
    data.operation.result.execution_baseline_plan = undefined;
    data.operation.result.execution_baseline_binding = {kind: "execution_baseline_binding", schema_version: "v1", purpose: "rejected_candidate_rescue", continuation_mode: "pause", input_mode: "preserve_draft", authority_source: "engineering_operator_decision", authority_sha256: "8".repeat(64), binding_sha256: "9".repeat(64), rejected_candidate_output_sha256: data.proof.proof_sha256, plan_sha256: data.plan.plan_sha256, facts_sha256: "a".repeat(64), task_id: data.task.task_id, task_intent_sha256: data.task.task_intent_sha256, sequence: 1, prior_task_revision: data.task.task_revision, scope: data.scope, approved_base_ref: data.plan.target_base_ref, branch_name: "ai/fixture", worktree_path: "/fixture/coder", prior_execution_base_ref: data.plan.target_base_ref, prior_source_revision: data.proof.candidate_parent_revision, execution_base_ref: data.plan.target_base_ref, execution_source_revision: data.proof.candidate_revision, source_artifact_ids: [], resolved_interruption_receipt_sha256s: [], retained_patch: {uri: "memory://patch", sha256: "b".repeat(64), bytes: 0}, before_inventory_sha256: "c".repeat(64), after_inventory_sha256: "c".repeat(64), completed_at: "2026-10-25T00:00:00Z"};
    data.step.status = "WAITING_HUMAN"; data.step.lease_liveness = "LEASE_EXPIRED"; data.step.wait_disposition_sha256 = "d".repeat(64);
    data.step.wait_disposition = {responsibility: "engineering", action: "RESUME_EXECUTION_BASELINE", facts: {classification: "EXECUTION_BASELINE_PAUSED", task_id: data.task.task_id, work_item_id: data.step.work_item_id, checkpoint_sequence: data.task.task_revision, task_intent_sha256: data.task.task_intent_sha256, source_revision: data.proof.candidate_revision, execution_baseline_sha256: "9".repeat(64)}}`);
  return h;
}

test("a paused retained candidate remains actionable when the native projection is terminal", async () => {
  const h = pausedFixture(); const panel = h.panel();
  assert.match(text(panel), /候选已保留，等待继续/);
  await button(panel, "继续原需求").events.click();
  assert.equal(h.run("submitted[0].action"), "RESUME_EXECUTION_BASELINE");
  assert.equal(h.run("submitted[0].expected_execution_baseline_sha256"), "9".repeat(64));
});

test("retained candidate pause rejects changed bindings, waits, scopes and stale clicks", async () => {
  for (const mutation of [
    'data.task.status = "BLOCKED"', 'data.request.stage = "CLOSED"', 'data.task.task_revision = 12',
    'data.step.status = "RUNNING"', 'data.step.lease_liveness = "LEASE_VALID"',
    'data.step.wait_disposition.facts.execution_baseline_sha256 = "f".repeat(64)',
    'data.step.wait_disposition.facts.classification = "PLATFORM_BUG"',
    'data.step.wait_disposition.facts.task_intent_sha256 = "f".repeat(64)',
    'data.step.wait_disposition.facts.source_revision = "f".repeat(40)',
    'data.operation.result.execution_baseline_binding.scope.team_id = "other_team"',
    'data.operation.result.execution_baseline_binding.prior_task_revision = 12',
    'data.operation.result.execution_baseline_binding.purpose = "source_rebind"',
    'data.operation.result.execution_baseline_binding.before_inventory_sha256 = "f".repeat(64)',
    'data.operation.result.execution_baseline_binding.authority_source = "organization_engineering_policy"',
    'data.operation.result.execution_baseline_binding.execution_source_revision = "f".repeat(40)',
    'data.operation.intent.expected_plan_sha256 = "f".repeat(64)',
    'snapshot.selected_project_id = "other_project"',
    'consoleOperationContractVersion = 10',
  ]) {
    const h = pausedFixture(); const panel = h.panel(); h.run(mutation);
    await button(panel, "继续原需求").events.click();
    assert.equal(h.run("submitted.length"), 0, mutation);
  }
});
