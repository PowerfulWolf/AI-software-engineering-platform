# ruff: noqa: E501, RUF001

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_software_engineer.team_view.blocker_text import (
    _coder_output_diagnostic,
    localize_blocking_text,
)

_UPSTREAM_STAGE_ACTIONS: tuple[tuple[str, str], ...] = (
    ("Prepare every selected directory.", "准备所有已选择的代码目录。"),
    (
        "Requirement project prepared. Discuss your requirement in this workspace.",
        "需求项目已准备好，请在此工作区描述并讨论需求。",
    ),
    (
        "Discover one product across all prepared directories.",
        "Product Agent 将梳理所有已准备代码目录的统一需求。",
    ),
    ("Revise the unified ProductSpec.", "Product Agent 将根据本次回复修订统一产品规格。"),
    ("Reply to the Product Agent questions.", "请回答 Product Agent 的问题。"),
    (
        "Review product_spec and approve this exact checkpoint, or reply with revisions.",
        "请审阅本版产品规格并批准，或回复需要修改的内容。",
    ),
    (
        "Design all participating repositories against the approved product.",
        "Designer 将依据已批准的产品规格设计所有参与交付的代码仓库。",
    ),
    (
        "Plan the bounded repository order and joint integration checks.",
        "Planner 将制定有界的仓库交付顺序与联合集成检查计划。",
    ),
    (
        "Execute each repository with independent QA and Reviewer.",
        "按计划交付各代码仓库，并由独立 QA 和 Reviewer 验证。",
    ),
    (
        "Resume with the exact approved knowledge resolution.",
        "使用本次已批准的精确知识解答继续交付。",
    ),
    (
        "Resolve the recorded project specification conflicts before a new intake.",
        "请先处理已记录的项目规范冲突，再开始接收新需求。",
    ),
    (
        "Requirement closed by user; delivery history is retained.",
        "需求已由用户关闭，交付历史仍完整保留。",
    ),
    (
        "Requirement restarted; continue delivery from the retained checkpoint.",
        "需求已重新打开，请从保留的交付进度继续。",
    ),
    (
        "Design recheck requested. Continue to inspect the retained questions "
        "against approved Product facts and exact repository revisions. "
        "This is not approval of proposed behavior changes; budgets are unchanged.",
        "已请求重新核对设计。请继续依据已批准的产品事实和精确仓库版本检查保留的问题。"
        "这不代表批准拟议的行为变更，执行预算保持不变。",
    ),
)


@pytest.mark.parametrize(("original", "expected"), _UPSTREAM_STAGE_ACTIONS)
def test_fixed_upstream_stage_actions_have_chinese_read_side_wording(
    original: str, expected: str
) -> None:
    assert localize_blocking_text(original) == expected
    assert localize_blocking_text(f"用户引用：{original}") == f"用户引用：{original}"


def test_browser_and_reader_agree_on_fixed_upstream_stage_actions() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the browser/reader wording contract")
    app = Path(__file__).parents[2] / "src/ai_software_engineer/team_view/app.js"
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const context = vm.createContext({document: {getElementById: () => ({addEventListener() {}})}});
const source = fs.readFileSync(process.argv[1], "utf8");
vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
context.messages = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(vm.runInContext("messages.map(humanizeBlockingText)", context)));
"""
    result = subprocess.run(
        (node, "-e", script, str(app)),
        input=json.dumps(
            [source for source, _ in _UPSTREAM_STAGE_ACTIONS]
            + [f"用户引用：{source}" for source, _ in _UPSTREAM_STAGE_ACTIONS]
        ),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == [expected for _, expected in _UPSTREAM_STAGE_ACTIONS] + [
        f"用户引用：{source}" for source, _ in _UPSTREAM_STAGE_ACTIONS
    ]


def test_historical_designer_rejection_is_localized_without_inventing_the_cause() -> None:
    original = "Designer stopped safely (DesignerOutputRejected)"
    localized = localize_blocking_text(original)
    assert localized == "技术设计输出未通过校验（DesignerOutputRejected），请检查设计及失败记录。"
    assert "路径" not in localized


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    (
        (
            "cause=WORK_SLICE;validation_rule=PARTIAL_CANDIDATE",
            "本轮仍有后续步骤，只能保存开发进度，完整候选未接纳",
        ),
        (
            "cause=WORK_SLICE;validation_rule=UNSELECTED_COMPLETION",
            "本轮报告把未选定的后续步骤记为完成，平台未接纳报告",
        ),
        (
            "cause=WORK_SLICE;validation_rule=DEFERRED_STEPS",
            "开发进度遗漏了后续待完成步骤，平台未接纳报告",
        ),
        (
            "cause=WORK_SLICE;validation_rule=STEP_PARTITION",
            "开发进度未完整列出已完成和待完成步骤，平台未接纳报告",
        ),
        (
            "cause=WORK_SLICE;validation_rule=PRIOR_COMPLETION",
            "开发进度撤回了此前已完成的步骤，平台未接纳报告",
        ),
        (
            "cause=WORK_SLICE;validation_rule=SOURCE_REVISION",
            "开发报告未绑定当前代码基线，平台未接纳报告",
        ),
        (
            "cause=WORK_SLICE;validation_rule=TASK_BINDING",
            "开发报告不属于当前任务切片，平台未接纳报告",
        ),
        (
            "cause=WORK_SLICE;validation_rule=OUTPUT_KIND",
            "本轮报告类型不符合开发切片约定，平台未接纳报告",
        ),
        (
            "cause=WORK_SLICE;validation_rule=INPUT_CONTRACT",
            "当前开发切片不满足执行前提，平台未接纳报告",
        ),
        (
            "cause=WORK_SLICE;validation_rule=FUTURE_UNKNOWN",
            "开发报告不符合本轮步骤约定，平台未接纳报告",
        ),
        (
            "cause=GIT_CONTRACT",
            "开发报告未通过代码与工作区校验，具体旧校验子因未保存，不能据此认定开发完成",
        ),
    ),
)
@pytest.mark.parametrize("wrapped", (False, True), ids=("direct", "real_run_envelope"))
def test_coder_output_read_side_diagnostic_has_fixed_chinese_and_browser_parity(
    diagnostic: str, expected: str, wrapped: bool
) -> None:
    original = (
        "INVALID_OUTPUT: Coder failed at attempt 1: "
        + ("coder run run_original failed: " if wrapped else "")
        + f"Codex CLI returned invalid structured output; {diagnostic}; "
        "output_sha256=" + "a" * 64 + "; output_bytes=10529; run_original"
    )
    localized = localize_blocking_text(original)
    assert localized is not None
    assert expected in localized
    assert "执行记录 run_original" in localized
    assert "证据摘要 " + "a" * 64 in localized
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for browser wording parity")
    app = Path(__file__).parents[2] / "src/ai_software_engineer/team_view/app.js"
    script = r"""
const fs = require("node:fs"), vm = require("node:vm");
const context = vm.createContext({document: {getElementById: () => ({addEventListener() {}})}});
const source = fs.readFileSync(process.argv[1], "utf8");
vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
context.messages = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(vm.runInContext("messages.map(humanizeBlockingText)", context)));
"""
    result = subprocess.run(
        (node, "-e", script, str(app)),
        input=json.dumps([original]),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == [localized]


@pytest.mark.parametrize(
    "prefix",
    (
        "quoted ",
        "qa run run_original failed: ",
        "coder run run_Original failed: ",
        "coder run run_original failed:  ",
        "coder run run_original failed: coder run run_second failed: ",
    ),
)
def test_coder_diagnostic_does_not_recognize_arbitrary_or_nested_envelopes(prefix: str) -> None:
    detail = prefix + "Codex CLI returned invalid structured output; cause=GIT_CONTRACT"
    assert _coder_output_diagnostic(detail) is None
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for browser wording parity")
    app = Path(__file__).parents[2] / "src/ai_software_engineer/team_view/app.js"
    script = r"""
const fs = require("node:fs"), vm = require("node:vm");
const context = vm.createContext({document: {getElementById: () => ({addEventListener() {}})}});
const source = fs.readFileSync(process.argv[1], "utf8");
vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
context.detail = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(vm.runInContext("coderOutputDiagnostic(detail)", context)));
"""
    result = subprocess.run(
        (node, "-e", script, str(app)),
        input=json.dumps(detail),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) is None


def test_localizes_stable_recovery_and_manager_blockers() -> None:
    assert localize_blocking_text("A child delivery or integration requires recovery.") == (
        "子交付或联合集成需要恢复。"
    )
    assert (
        localize_blocking_text(
            "Coder recovery stopped safely: failed Coder identity is missing, unsafe or ambiguous"
        )
        == "Coder 恢复已安全停止，请检查失败记录和恢复证据后再继续。"
    )


def test_localizes_repository_blocker_but_keeps_opaque_identity() -> None:
    value = (
        "Repository unit_backend is BLOCKED; PLANNING (INVARIANT_VIOLATION): Planner stopped safely"
    )
    localized = localize_blocking_text(value)
    assert localized == (
        "代码仓库 unit_backend 已阻塞；计划阶段校验失败（INVARIANT_VIOLATION），Planner 已安全停止。"
    )


@pytest.mark.parametrize("classification", ["TRANSIENT_INFRA", "NONTRANSIENT_INFRA"])
def test_localizes_role_failure_and_keeps_run_and_evidence_ids(classification: str) -> None:
    value = (
        f"{classification}: Reviewer failed at attempt 3: reviewer run run_abc123 failed: "
        "Codex CLI provider execution failed; stdout_sha256="
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    localized = localize_blocking_text(value)
    assert localized is not None
    assert localized.startswith("Reviewer 第 3 次执行失败：Codex CLI 模型服务执行失败")
    assert "run_abc123" in localized
    assert "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" in localized


def test_localizes_nontransient_knowledge_failure_without_inventing_a_diagnosis() -> None:
    assert (
        localize_blocking_text(
            "NONTRANSIENT_INFRA: coder knowledge preparation failed: PROVIDER_UNAVAILABLE"
        )
        == "Coder 知识准备失败（原因代码：PROVIDER_UNAVAILABLE），请检查模型服务后再继续。"
    )


def test_localizes_policy_classified_role_failure() -> None:
    localized = localize_blocking_text(
        "POLICY_VIOLATION: QA failed at attempt 1: qa run run_abc123 failed: "
        "candidate review prompt exceeds its configured Context budget"
    )

    assert localized is not None
    assert "QA 第 1 次执行失败" in localized
    assert "候选验证上下文超过配置预算" in localized


def test_localizes_dirty_provider_failure_with_safe_route_detail() -> None:
    localized = localize_blocking_text(
        "POLICY_VIOLATION: Coder failed at attempt 1: coder run run_abc123 failed: "
        "failed provider route left repository changes; "
        "provider_diagnostic=Responses provider returned HTTP 429"
    )

    assert localized is not None
    assert "模型服务返回 HTTP 429" in localized
    assert "改动已保留，等待精确恢复审批" in localized
    assert "run_abc123" in localized


def test_localizes_pre_agent_worktree_conflict() -> None:
    assert localize_blocking_text("Delivery stopped safely (WorktreeAlreadyExists)") == (
        "Coder 启动前发现目标分支或工作区已被其他保留任务占用，平台已安全停止并等待精确重启审批。"
    )


def test_localizes_interrupted_codex_timeout_with_retained_changes() -> None:
    digest = "a" * 64
    localized = localize_blocking_text(
        "POLICY_VIOLATION: Coder failed at attempt 1: coder run run_abc123 failed: "
        "Codex CLI left changes after an interrupted execution; cause=TIMEOUT; "
        f"returncode=-1; stdout_sha256={digest}"
    )

    assert localized is not None
    assert "Coder 执行超时，改动已保留，但未产出可接纳的报告，等待精确恢复审批" in localized
    assert "run_abc123" in localized
    assert digest in localized
    assert "预算耗尽" not in localized


def test_signalled_historical_cli_exit_is_presented_as_interruption() -> None:
    localized = localize_blocking_text(
        "Coder failed at attempt 1: coder run run_abc123 failed: "
        "Codex CLI left changes after a failed execution; cause=AUTHENTICATION_ERROR; "
        "returncode=-15; stdout_sha256=" + "a" * 64
    )
    assert localized is not None
    assert "执行被中断，改动已保留" in localized
    assert "模型服务认证失败" not in localized
    assert "run_abc123" in localized
    assert "a" * 64 in localized


def test_localizes_knowledge_preparation_failure_and_keeps_error_code() -> None:
    assert (
        localize_blocking_text(
            "TRANSIENT_INFRA: coder knowledge preparation reached local time limit"
        )
        == "Coder 知识准备达到本地执行时限，尚未开始该角色执行；请检查并批准精确恢复计划。"
    )
    assert localize_blocking_text("qa knowledge preparation failed: RATE_LIMITED") == (
        "QA 知识准备失败（原因代码：RATE_LIMITED），请检查模型服务后再继续。"
    )
    assert (
        localize_blocking_text(
            "TRANSIENT_INFRA: coder knowledge preparation failed: AUTHENTICATION_ERROR"
        )
        == "Coder 知识准备失败（原因代码：AUTHENTICATION_ERROR），请检查模型服务后再继续。"
    )
    assert localize_blocking_text(
        "BUDGET_EXHAUSTED：所需上下文超过配置的输入上限，不能自动重试。"
    ) == ("上下文预算已用尽，平台不会自动重试模型；请缩小精确验证范围后再继续。")


@pytest.mark.parametrize("code", ("CONTEXT_BUDGET_EXHAUSTED", "CONTEXT_CAPACITY"))
def test_localizes_context_capacity_without_calling_it_work_budget_exhaustion(code: str) -> None:
    localized = localize_blocking_text(
        f"{code}: final provider input exceeds the configured Context budget (255325 > 252000)"
    )
    assert localized == (
        "执行上下文超过平台输入容量，模型尚未调用；本次未消耗自动重试额度。"
        "请由平台调整上下文装配或执行能力后，再为原需求准备新的精确恢复方案。"
    )


_LEGACY_CAPACITY_REASON = (
    "Required context exceeds the configured input budget; no automatic retry."
)
_LEGACY_CAPACITY_COPY = (
    "所需上下文超过平台输入容量，交付已暂停。"
    "请由平台调整输入装配后，为原需求准备保留完整开发进度的恢复方案。"
)
_LEGACY_CAPACITY_CASES: tuple[tuple[str, str], ...] = (
    (_LEGACY_CAPACITY_REASON, _LEGACY_CAPACITY_COPY),
    (f"用户引用：{_LEGACY_CAPACITY_REASON}", f"用户引用：{_LEGACY_CAPACITY_REASON}"),
    (f"{_LEGACY_CAPACITY_REASON} User detail.", f"{_LEGACY_CAPACITY_REASON} User detail."),
    ("RETRY_BUDGET_EXHAUSTED", "RETRY_BUDGET_EXHAUSTED"),
    (
        "BUDGET_EXHAUSTED: Coder work attempts exhausted.",
        "BUDGET_EXHAUSTED: Coder work attempts exhausted.",
    ),
)


@pytest.mark.parametrize(("original", "expected"), _LEGACY_CAPACITY_CASES)
def test_legacy_capacity_translation_keeps_exact_match_and_normal_budget_semantics(
    original: str, expected: str
) -> None:
    assert localize_blocking_text(original) == expected


def test_browser_and_reader_agree_on_exact_legacy_capacity_translation() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the browser/reader wording contract")
    app = Path(__file__).parents[2] / "src/ai_software_engineer/team_view/app.js"
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const context = vm.createContext({document: {getElementById: () => ({addEventListener() {}})}});
const source = fs.readFileSync(process.argv[1], "utf8");
vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
context.messages = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(vm.runInContext("messages.map(humanizeBlockingText)", context)));
"""
    result = subprocess.run(
        (node, "-e", script, str(app)),
        input=json.dumps([original for original, _ in _LEGACY_CAPACITY_CASES]),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == [expected for _, expected in _LEGACY_CAPACITY_CASES]


@pytest.mark.parametrize("code", ("CONTEXT_BUDGET_EXHAUSTED", "CONTEXT_CAPACITY"))
def test_browser_localizes_context_capacity_with_the_same_read_side_copy(code: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the browser/reader wording contract")
    app = Path(__file__).parents[2] / "src/ai_software_engineer/team_view/app.js"
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const context = vm.createContext({document: {getElementById: () => ({addEventListener() {}})}});
const source = fs.readFileSync(process.argv[1], "utf8");
vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
context.message = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(vm.runInContext("humanizeBlockingText(message)", context));
"""
    # Keep the same boundary text used by the Python presentation contract; the
    # numeric detail is deliberately ignored by both read-side adapters.
    value = f"{code}: final provider input exceeds the configured Context budget (255325 > 252000)"
    result = subprocess.run(
        (node, "-e", script, str(app)),
        input=json.dumps(value),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout == (
        "执行上下文超过平台输入容量，模型尚未调用；本次未消耗自动重试额度。"
        "请由平台调整上下文装配或执行能力后，再为原需求准备新的精确恢复方案。"
    )


@pytest.mark.parametrize(
    ("detail", "reason"),
    [
        (
            "candidate review prompt exceeds its configured Context budget",
            "候选验证上下文超过配置预算，平台在模型调用前安全停止",
        ),
        (
            "candidate read snapshot exceeds its bounded context budget",
            "候选读取快照超过有界上下文预算，平台未调用模型",
        ),
        (
            "AUTHENTICATION_ERROR",
            "模型服务认证失败，当前阶段未完成",
        ),
        (
            "UNKNOWN_EVIDENCE_REFERENCE",
            "模型产物引用了不存在的证据，QA/Review 结果未被接受",
        ),
        (
            "interrupted execution left repository changes",
            "执行中断后工作区仍有未确认改动，平台已暂停并等待精确恢复审批",
        ),
    ],
)
def test_localizes_known_role_blockers_with_actionable_details(
    detail: str,
    reason: str,
) -> None:
    localized = localize_blocking_text(f"QA failed at attempt 1: {detail}")

    assert localized is not None
    assert reason in localized
    assert "QA 第 1 次执行失败" in localized


def test_localizes_manager_recovery_advice_and_keeps_approval_digest() -> None:
    digest = "a" * 64
    assert (
        localize_blocking_text(
            "Delivery is blocked because a sub-delivery or joint integration requires "
            "recovery and the child finding requests human handling."
        )
        == "子交付或联合集成需要恢复，子任务发现需要人工处理。"
    )
    assert localize_blocking_text(
        "Route the blocked delivery to the existing exact recovery approval associated "
        f"with approval_sha256 {digest}. Do not reset task state or replay any consumed approval."
    ) == (
        "请将阻塞交付转入已存在且精确匹配的恢复审批（审批摘要 "
        f"{digest}）。不要重置任务状态，也不要重复使用已消费的审批。"
    )
    assert localize_blocking_text("Authorized human recovery approver or delivery owner") == (
        "已授权的人工恢复审批人或交付负责人"
    )


def test_unknown_text_and_durable_record_are_not_rewritten() -> None:
    value = "未知原因 run_123 sha256=abc123"
    assert localize_blocking_text(value) == value
    assert localize_blocking_text(None) is None


def test_stopped_engineering_work_is_not_described_as_product_approval() -> None:
    value = "WORK_INTERRUPTED: Coder failed at attempt 1: 工程执行已中断。草稿已保留。现场不满足自动继续条件。需要工程处理。"
    localized = localize_blocking_text(value)
    assert localized is not None
    assert "工程团队" in localized
    assert "等待精确恢复审批" not in localized
    assert "WORK_INTERRUPTED" not in localized
