"""Manager proposes remedies, never substitutes for the independent verifiers."""

from functools import partial
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents.structured import StructuredModelError, StructuredModelResult
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.manager.native_ui import NativeUiSession, NativeUiSessionPrerequisite
from ai_software_engineer.manager.verification_coordination import (
    ManagerVerificationAdvice,
    ManagerVerificationDraft,
    VerificationFailureReference,
    coordinate_verification,
    coordination_digest,
)


def test_manager_must_cover_original_criteria_without_producing_verdicts() -> None:
    client = Mock()
    draft = {
        "disposition": "PROPOSE_UI",
        "summary": "Inspect isolated mock",
        "next_action": "Approve exact plan",
        "native_ui_scenario": {
            "product": "Fixture",
            "mock_argument": "--mock-ui",
            "window_title": "Fixture",
            "steps": [{"name": "initial", "action": "snapshot"}],
        },
        "criteria": [
            {"criterion_id": "AC01", "step_names": ["initial"], "expected_observation": "Two rows"}
        ],
    }
    client.complete.return_value = StructuredModelResult(payload=draft, duration_ms=1)
    coordinate = partial(
        coordinate_verification,
        client,
        payload={"candidate": "fixture"},
        scope_sha256="1" * 64,
        candidate_revision="2" * 40,
        qa_artifact_id="art_qa_fixture",
        qa_artifact_sha256="3" * 64,
    )
    with pytest.raises(StructuredModelError, match="typed contract"):
        coordinate(criterion_ids=("AC01", "AC02"))
    advice = coordinate(criterion_ids=("AC01",))
    advice.validate_integrity()
    assert advice.draft.disposition == "PROPOSE_UI"
    assert "verdict" not in advice.to_wire()
    assert "never execute" in client.complete.call_args.kwargs["instructions"]


def test_historical_ui_advice_hash_excludes_absent_capture_field() -> None:
    from tests.recovery.test_native_ui import scenario

    draft = ManagerVerificationDraft(
        disposition="PROPOSE_UI",
        summary="Historical AX only",
        next_action="Approve",
        native_ui_scenario=scenario(),
    )
    value = ManagerVerificationAdvice.create(
        input_sha256="1" * 64,
        scope_sha256="2" * 64,
        candidate_revision="3" * 40,
        qa_artifact_id="art_qa_fixture",
        qa_artifact_sha256="4" * 64,
        manager_run_id="run_fixture",
        provider="fixture",
        model="fixture",
        draft=draft,
    )
    historical = value.model_dump(
        mode="json",
        exclude={
            "advice_sha256",
            "knowledge_resolutions",
            "execution_failure",
            "environment_prerequisite",
        },
    )
    historical["draft"].pop("prerequisite_repair")
    for step in historical["draft"]["native_ui_scenario"]["steps"]:
        step.pop("capture_window")
        step.pop("scroll_position")
    historical["advice_sha256"] = coordination_digest(historical)
    loaded = ManagerVerificationAdvice.model_validate(historical)
    loaded.validate_integrity()
    changed = dict(historical)
    changed["draft"] = draft.model_dump(mode="json")
    changed["draft"]["native_ui_scenario"]["steps"][0]["capture_window"] = True
    with pytest.raises(ValueError, match="digest"):
        ManagerVerificationAdvice.model_validate(changed).validate_integrity()


def test_manager_contract_correction_is_bounded_and_never_echoes_invalid_input() -> None:
    invalid = StructuredModelResult(
        payload={
            "disposition": "WAITING_HUMAN",
            "summary": "secret=DO_NOT_ECHO",
            "next_action": "Approve",
            "native_ui_scenario": {"unexpected": "raw output"},
        },
        duration_ms=1,
    )
    valid = StructuredModelResult(
        payload={
            "disposition": "WAITING_HUMAN",
            "summary": "Missing UI capability",
            "next_action": "Manager requests capability provisioning then resumes",
            "native_ui_scenario": None,
        },
        duration_ms=1,
    )
    client = Mock()
    client.complete.side_effect = [invalid, valid]
    call = partial(
        coordinate_verification,
        client,
        payload={"candidate": "fixture"},
        criterion_ids=("AC01",),
        scope_sha256="1" * 64,
        candidate_revision="2" * 40,
        qa_artifact_id="art_qa_fixture",
        qa_artifact_sha256="3" * 64,
    )
    advice = call()
    assert advice.draft.disposition == "WAITING_HUMAN"
    assert client.complete.call_count == 2
    assert "DO_NOT_ECHO" not in str(client.complete.call_args)
    client.complete.side_effect = [invalid, invalid]
    with pytest.raises(StructuredModelError) as failure:
        call()
    assert "DO_NOT_ECHO" not in str(failure.value)


def test_source_repair_is_proposal_only_and_requires_executor_source() -> None:
    draft = {
        "disposition": "PROPOSE_REPAIR",
        "summary": "Mock entry has no primary window",
        "next_action": "Approve bounded test-entry repair for ASE Coder",
        "prerequisite_repair": {
            "objective": "Open the primary isolated Mock window on direct launch.",
            "write_paths": ["Sources/App.swift", "Tests/**"],
        },
    }
    client = Mock()
    client.complete.return_value = StructuredModelResult(payload=draft, duration_ms=1)
    coordinate = partial(
        coordinate_verification,
        client,
        payload={"candidate": "fixture"},
        criterion_ids=("AC01",),
        scope_sha256="1" * 64,
        candidate_revision="2" * 40,
        qa_artifact_id=None,
        qa_artifact_sha256=None,
    )
    with pytest.raises(StructuredModelError, match="typed contract"):
        coordinate()
    advice = coordinate(
        execution_failure=VerificationFailureReference(
            plan_sha256="3" * 64, record_sha256="4" * 64, role=AgentRole.QA
        )
    )
    advice.validate_integrity()
    assert advice.draft.native_ui_scenario is None
    assert advice.draft.prerequisite_repair is not None
    assert "approval" not in advice.to_wire() and "verdict" not in advice.to_wire()
    with pytest.raises(ValueError):
        ManagerVerificationDraft.model_validate({**draft, "disposition": "WAITING_HUMAN"})
    with pytest.raises(ValueError):
        ManagerVerificationDraft.model_validate({**draft, "prerequisite_repair": None})


def test_historical_advice_digest_omits_new_optional_repair_field() -> None:
    historical = {
        "kind": "manager_verification_advice",
        "input_sha256": "1" * 64,
        "scope_sha256": "2" * 64,
        "candidate_revision": "3" * 40,
        "qa_artifact_id": "art_qa_fixture",
        "qa_artifact_sha256": "4" * 64,
        "manager_run_id": "manager_run_fixture",
        "provider": "fixture",
        "model": "fixture",
        "draft": {
            "disposition": "WAITING_HUMAN",
            "summary": "Missing prerequisite",
            "next_action": "Manager coordinates environment and resumes",
            "native_ui_scenario": None,
            "criteria": [],
        },
    }
    advice = ManagerVerificationAdvice.model_validate(
        {**historical, "advice_sha256": coordination_digest(historical)}
    )
    advice.validate_integrity()


@pytest.mark.parametrize("status", [None, "SESSION_LOCKED", "SESSION_UNAVAILABLE", "READY"])
def test_unresolved_desktop_cannot_become_ui_or_source_repair_authority(status: str | None) -> None:
    prerequisite = NativeUiSessionPrerequisite(
        observed_status="SESSION_LOCKED",
        current_session=NativeUiSession.model_validate({"status": status}) if status else None,
    )
    client = Mock()
    client.complete.return_value = StructuredModelResult(
        payload={
            "disposition": "PROPOSE_UI",
            "summary": "Observe the mock",
            "next_action": "Approve fresh exact verification",
            "native_ui_scenario": {
                "product": "Fixture",
                "mock_argument": "--mock-ui",
                "window_title": "Fixture",
                "steps": [{"name": "initial", "action": "snapshot"}],
            },
            "criteria": [
                {"criterion_id": "AC01", "step_names": ["initial"], "expected_observation": "Rows"}
            ],
        },
        duration_ms=1,
    )
    call = partial(
        coordinate_verification,
        client,
        payload={"candidate": "fixture"},
        criterion_ids=("AC01",),
        scope_sha256="1" * 64,
        candidate_revision="2" * 40,
        qa_artifact_id=None,
        qa_artifact_sha256=None,
        execution_failure=VerificationFailureReference(
            plan_sha256="3" * 64, record_sha256="4" * 64, role=AgentRole.QA
        ),
        environment_prerequisite=prerequisite,
    )
    if status == "READY":
        advice = call()
        assert advice.draft.disposition == "PROPOSE_UI"
        assert advice.environment_prerequisite == prerequisite
        advice.validate_integrity()
    else:
        with pytest.raises(StructuredModelError, match="typed contract"):
            call()
        assert client.complete.call_count == 2
