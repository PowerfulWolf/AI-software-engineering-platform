# ruff: noqa: E501, RUF001

import pytest

from ai_software_engineer.team_view.blocker_text import localize_blocking_text


def test_historical_designer_rejection_is_localized_without_inventing_the_cause() -> None:
    original = "Designer stopped safely (DesignerOutputRejected)"
    localized = localize_blocking_text(original)
    assert localized == "技术设计输出未通过校验（DesignerOutputRejected），请检查设计及失败记录。"
    assert "路径" not in localized


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


def test_localizes_role_failure_and_keeps_run_and_evidence_ids() -> None:
    value = (
        "TRANSIENT_INFRA: Reviewer failed at attempt 3: reviewer run run_abc123 failed: "
        "Codex CLI provider execution failed; stdout_sha256="
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    localized = localize_blocking_text(value)
    assert localized.startswith("Reviewer 第 3 次执行失败：Codex CLI 模型服务执行失败")
    assert "run_abc123" in localized
    assert "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" in localized


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
