"""Engineering wait guidance distinguishes a file gap from a named pytest node gap."""

import pytest

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.execution_window import PlannedVerificationRequirement
from ai_software_engineer.domain.native_verification import role_verification_digest
from ai_software_engineer.manager.candidate_test_entry_absence import (
    CandidateTestEntryAbsenceObservation,
    MissingPlannedTestEntry,
)
from ai_software_engineer.manager.delivery_wait import (
    DeliveryWaitRejected,
    _static_qa_next_action,
)


def _observation(
    *, named_node: bool, missing_file: bool = False
) -> CandidateTestEntryAbsenceObservation:
    path = "tests/test_live_a_to_b.py"
    node = path + "::test_production_a_to_b_live"
    row = PlannedVerificationRequirement(
        id="verify_live_a_to_b",
        role=AgentRole.QA,
        criterion_ids=("ac_live",),
        argv=("python", "-m", "pytest", "-q", node),
        planned_new_files=(path,),
        verification_levels=("e2e",),
    )
    entries = [
        MissingPlannedTestEntry(
            requirement=row,
            requirement_sha256=role_verification_digest(row.to_wire()),
            path=path,
            node_id=node if named_node else None,
        )
    ]
    rows = [row]
    if missing_file:
        browser = PlannedVerificationRequirement(
            id="verify_browser",
            role=AgentRole.QA,
            criterion_ids=("ac_browser",),
            argv=("node", "--test", "tests/browser.test.cjs"),
            planned_new_files=("tests/browser.test.cjs",),
            verification_levels=("e2e",),
        )
        rows.append(browser)
        entries.append(
            MissingPlannedTestEntry(
                requirement=browser,
                requirement_sha256=role_verification_digest(browser.to_wire()),
                path="tests/browser.test.cjs",
            )
        )
    return CandidateTestEntryAbsenceObservation.create(
        task_id="task_static_qa_guidance",
        task_intent_sha256="a" * 64,
        candidate_revision="b" * 40,
        plan_artifact_id="art_plan_static_qa_guidance",
        plan_artifact_sha256="c" * 64,
        plan_requirements_sha256=role_verification_digest([item.to_wire() for item in rows]),
        implementation_artifact_id="art_impl_static_qa_guidance",
        implementation_artifact_sha256="d" * 64,
        missing=tuple(entries),
    )


def test_file_only_guidance_keeps_historical_text() -> None:
    assert _static_qa_next_action(_observation(named_node=False)) == (
        "候选提交缺少冻结计划指定的验收测试文件。原 QA 验证准备与模型均未开始; "
        "工程责任人可核对并批准专用静态 FAIL 验收; 原计划验证命令未启动, "
        "后续仍需独立 QA 和返工。"
    )


@pytest.mark.parametrize("mixed", [False, True])
def test_named_node_guidance_reports_source_gap_without_collection_claim(mixed: bool) -> None:
    action = _static_qa_next_action(_observation(named_node=True, missing_file=mixed))
    assert "冻结 pytest 函数节点" in action
    assert "直接源码绑定" in action
    assert "动态收集均未运行" in action
    assert ("文件缺失" in action) is mixed
    if not mixed:
        assert "缺少冻结计划指定的验收测试文件" not in action


def test_guidance_needs_a_current_observation() -> None:
    with pytest.raises(DeliveryWaitRejected, match="缺少当前候选观察"):
        _static_qa_next_action(None)
