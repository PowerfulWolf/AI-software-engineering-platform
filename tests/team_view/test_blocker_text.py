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


def test_unknown_text_and_durable_record_are_not_rewritten() -> None:
    value = "未知原因 run_123 sha256=abc123"
    assert localize_blocking_text(value) == value
    assert localize_blocking_text(None) is None
