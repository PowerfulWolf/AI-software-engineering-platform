"""Lossless read-only partitioning; a diagnostic is never execution authority."""

from __future__ import annotations

import pytest

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.execution_window import (
    PlannedVerificationInspection,
    PlannedVerificationRequirement,
)
from ai_software_engineer.domain.native_verification import (
    NativeVerificationCapabilityDetail,
    NativeVerificationWaiting,
    NativeVerificationWaitReason,
    role_verification_digest,
)
from ai_software_engineer.manager.native_verification_partition import (
    NativeEntrypointDiagnosticHint,
    NativeRequirementPrerequisite,
    partition_verification_requirements,
)


def mixed_requirements() -> tuple[PlannedVerificationRequirement, ...]:
    python = tuple(
        PlannedVerificationRequirement(
            id=f"verify_python_{index}",
            role=AgentRole.QA,
            criterion_ids=("ac_models_01",),
            argv=("pytest", f"tests/test_case.py::test_case_{index}"),
            controlled_capability_kind="codex_sandbox_pytest_mysql_v1",
            verification_levels=("unit",),
        )
        for index in range(55)
    )
    browser = PlannedVerificationRequirement(
        id="verify_browser",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        argv=("node", "--test", "tests/browser/fixture.test.cjs"),
        verification_levels=("e2e",),
        planned_new_files=("tests/browser/fixture.test.cjs",),
    )
    live = tuple(
        PlannedVerificationRequirement(
            id=f"verify_live_{index}",
            role=AgentRole.QA,
            criterion_ids=("ac_models_01",),
            argv=("python", "-m", "pytest", "tests/test_live.py::test_round_trip", "-q"),
            verification_levels=("e2e",),
            planned_new_files=("tests/test_live.py",),
        )
        for index in range(4)
    )
    document = PlannedVerificationRequirement(
        id="verify_document",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        inspection=PlannedVerificationInspection(
            kind="document", paths=("README.md",), checklist=("Check approved behavior",)
        ),
        verification_levels=("documentation",),
    )
    return (*python, browser, *live, document)


def test_mixed_partition_preserves_all_original_rows_and_repeated_commands() -> None:
    rows = mixed_requirements()
    original = [item.to_wire() for item in rows]
    result = partition_verification_requirements(
        rows, effective_role=AgentRole.QA, criterion_ids=("ac_models_01",)
    )
    assert result.requirements == rows
    assert result.requirements_sha256 == role_verification_digest(original)
    assert len(result.python_v1_requirements) == 55
    assert len(result.inspection_requirements) == 1
    assert len(result.unavailable_requirements) == 5
    assert len({item.requirement_id for item in result.unavailable_requirements}) == 5
    assert [item.to_wire() for item in rows] == original
    assert all(
        item.detail is NativeVerificationCapabilityDetail.REQUIREMENT_EXECUTOR_UNREGISTERED
        for item in result.unavailable_requirements
    )


def test_reviewer_fallback_preserves_qa_wire_and_uses_distinct_effective_role() -> None:
    rows = mixed_requirements()
    qa = partition_verification_requirements(
        rows, effective_role=AgentRole.QA, criterion_ids=("ac_models_01",)
    )
    reviewer = partition_verification_requirements(
        rows, effective_role=AgentRole.REVIEWER, criterion_ids=("ac_models_01",)
    )
    assert qa.requirements == reviewer.requirements == rows
    assert qa.requirements_sha256 == reviewer.requirements_sha256
    assert qa.effective_role is AgentRole.QA and reviewer.effective_role is AgentRole.REVIEWER
    assert all(
        item.effective_role is AgentRole.REVIEWER for item in reviewer.unavailable_requirements
    )
    assert all(item.role is AgentRole.QA for item in reviewer.requirements)


@pytest.mark.parametrize(
    "change", ["argv", "criterion_ids", "verification_levels", "planned_new_files", "inspection"]
)
def test_full_row_and_independent_digests_detect_changed_original_facts(change: str) -> None:
    rows = mixed_requirements()
    row = rows[-1] if change == "inspection" else rows[-2]
    values: dict[str, object] = {
        "argv": (*row.argv, "--changed") if row.argv else None,
        "criterion_ids": ("ac_other",),
        "verification_levels": ("integration", "e2e"),
        "planned_new_files": ("tests/different.py",),
        "inspection": row.inspection.model_copy(update={"checklist": ("Changed",)})
        if row.inspection
        else None,
    }
    changed = row.model_copy(update={change: values[change]})
    fact = NativeRequirementPrerequisite.for_requirement(
        row,
        effective_role=AgentRole.QA,
        reason=NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE,
        detail=NativeVerificationCapabilityDetail.REQUIREMENT_EXECUTOR_UNREGISTERED,
    )
    assert fact.requirement_sha256 != role_verification_digest(changed.to_wire())
    with pytest.raises(ValueError, match="identity"):
        fact.validate_requirement(changed, effective_role=AgentRole.QA)


def test_omitted_and_empty_verification_levels_are_distinct() -> None:
    row = mixed_requirements()[-2].model_copy(update={"verification_levels": None})
    omitted = NativeRequirementPrerequisite.for_requirement(
        row,
        effective_role=AgentRole.QA,
        reason=NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE,
        detail=NativeVerificationCapabilityDetail.REQUIREMENT_EXECUTOR_UNREGISTERED,
    )
    empty = NativeRequirementPrerequisite.for_requirement(
        row.model_copy(update={"verification_levels": ()}),
        effective_role=AgentRole.QA,
        reason=NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE,
        detail=NativeVerificationCapabilityDetail.REQUIREMENT_EXECUTOR_UNREGISTERED,
    )
    assert omitted.verification_levels_sha256 != empty.verification_levels_sha256
    assert omitted.requirement_sha256 != empty.requirement_sha256


@pytest.mark.parametrize("case", ["duplicate", "foreign", "missing", "role"])
def test_partition_rejects_invalid_scope_before_host_discovery(case: str) -> None:
    rows = mixed_requirements()
    if case == "duplicate":
        rows = (*rows, rows[0])
    elif case == "foreign":
        rows = (rows[0].model_copy(update={"criterion_ids": ("ac_other",)}), *rows[1:])
    elif case == "missing":
        rows = ()
    else:
        rows = (rows[0].model_copy(update={"role": AgentRole.REVIEWER}), *rows[1:])
    with pytest.raises((ValueError, NativeVerificationWaiting)):
        partition_verification_requirements(
            rows, effective_role=AgentRole.QA, criterion_ids=("ac_models_01",)
        )


def test_exact_trusted_hint_selects_diagnostic_only_and_never_a_capability() -> None:
    rows = mixed_requirements()
    browser = rows[55]
    assert browser.argv is not None
    hint = NativeEntrypointDiagnosticHint.create(
        argv=browser.argv,
        verification_levels=browser.verification_levels,
        detail=NativeVerificationCapabilityDetail.BROWSER_EXECUTOR_UNREGISTERED,
    )
    result = partition_verification_requirements(
        rows, effective_role=AgentRole.QA, criterion_ids=("ac_models_01",), hints=(hint,)
    )
    assert (
        result.unavailable_requirements[0].detail
        is NativeVerificationCapabilityDetail.BROWSER_EXECUTOR_UNREGISTERED
    )
    assert len(result.unavailable_requirements) == 5
    altered = browser.model_copy(update={"argv": (*browser.argv, "--changed")})
    changed = partition_verification_requirements(
        (*rows[:55], altered, *rows[56:]),
        effective_role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        hints=(hint,),
    )
    assert (
        changed.unavailable_requirements[0].detail
        is NativeVerificationCapabilityDetail.REQUIREMENT_EXECUTOR_UNREGISTERED
    )
    with pytest.raises(ValueError, match="hint"):
        hint.model_copy(update={"hint_sha256": "0" * 64}).validate_integrity()


def test_explicit_python_e2e_composition_retains_its_registered_capability() -> None:
    row = mixed_requirements()[-2]
    explicit = row.model_copy(
        update={"controlled_capability_kind": "codex_sandbox_pytest_mysql_v1"}
    )
    result = partition_verification_requirements(
        (explicit, row.model_copy(update={"id": "unmarked"})),
        effective_role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
    )
    assert result.python_v1_requirements == (explicit,)
    assert len(result.unavailable_requirements) == 1


def test_legacy_precise_python_without_levels_preserves_v1() -> None:
    row = mixed_requirements()[0].model_copy(
        update={"controlled_capability_kind": None, "verification_levels": None}
    )
    result = partition_verification_requirements(
        (row,), effective_role=AgentRole.QA, criterion_ids=("ac_models_01",)
    )
    assert result.python_v1_requirements == (row,)
    assert result.unavailable_requirements == ()


def test_hint_level_changes_cannot_match_original_semantics() -> None:
    row = mixed_requirements()[55]
    assert row.argv is not None
    hint = NativeEntrypointDiagnosticHint.create(
        argv=row.argv,
        verification_levels=("integration",),
        detail=NativeVerificationCapabilityDetail.BROWSER_EXECUTOR_UNREGISTERED,
    )
    group = partition_verification_requirements(
        (row,), effective_role=AgentRole.QA, criterion_ids=("ac_models_01",), hints=(hint,)
    )
    assert (
        group.unavailable_requirements[0].detail
        is NativeVerificationCapabilityDetail.REQUIREMENT_EXECUTOR_UNREGISTERED
    )


def test_python_subset_global_selection_bound_is_preserved_before_any_host_probe() -> None:
    row = mixed_requirements()[0]
    rows = tuple(
        row.model_copy(
            update={
                "id": f"verify_{index}",
                "argv": ("pytest", f"tests/test_case.py::test_{index}"),
            }
        )
        for index in range(65)
    )
    with pytest.raises(NativeVerificationWaiting) as error:
        partition_verification_requirements(
            rows, effective_role=AgentRole.QA, criterion_ids=("ac_models_01",)
        )
    assert error.value.reason is NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT


def mixed_overflow_requirements() -> tuple[PlannedVerificationRequirement, ...]:
    rows = mixed_requirements()
    python = tuple(
        rows[0].model_copy(
            update={
                "id": f"verify_overflow_{index}",
                "argv": ("pytest", f"tests/test_case.py::test_{index}"),
            }
        )
        for index in range(65)
    )
    return (*python, *rows[55:])


def test_mixed_python_overflow_retains_every_original_prerequisite() -> None:
    rows = mixed_overflow_requirements()
    result = partition_verification_requirements(
        rows, effective_role=AgentRole.QA, criterion_ids=("ac_models_01",)
    )
    assert result.requirements == rows
    assert result.python_v1_requirements == ()
    assert len(result.inspection_requirements) == 1
    assert len(result.unavailable_requirements) == 70
    indexed = {item.requirement_id: item for item in result.unavailable_requirements}
    for row in rows[:65]:
        assert indexed[row.id].reason is NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT
    for row in rows[65:-1]:
        assert (
            indexed[row.id].detail
            is NativeVerificationCapabilityDetail.REQUIREMENT_EXECUTOR_UNREGISTERED
        )
    result.validate_integrity()
