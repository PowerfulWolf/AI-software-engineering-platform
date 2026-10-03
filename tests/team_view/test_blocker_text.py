# ruff: noqa: E501, RUF001

from ai_software_engineer.team_view.blocker_text import localize_blocking_text


def test_localizes_stable_recovery_and_manager_blockers() -> None:
    assert localize_blocking_text("A child delivery or integration requires recovery.") == (
        "子交付或联合集成需要恢复。"
    )
    assert localize_blocking_text(
        "Coder recovery stopped safely: failed Coder identity is missing, unsafe or ambiguous"
    ) == "Coder 恢复已安全停止，请检查失败记录和恢复证据后再继续。"


def test_localizes_repository_blocker_but_keeps_opaque_identity() -> None:
    value = (
        "Repository unit_backend is BLOCKED; PLANNING (INVARIANT_VIOLATION): "
        "Planner stopped safely"
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


def test_localizes_knowledge_preparation_failure_and_keeps_error_code() -> None:
    assert localize_blocking_text("qa knowledge preparation failed: RATE_LIMITED") == (
        "QA 知识准备失败（原因代码：RATE_LIMITED），请检查模型服务后再继续。"
    )


def test_unknown_text_and_durable_record_are_not_rewritten() -> None:
    value = "未知原因 run_123 sha256=abc123"
    assert localize_blocking_text(value) == value
    assert localize_blocking_text(None) is None
