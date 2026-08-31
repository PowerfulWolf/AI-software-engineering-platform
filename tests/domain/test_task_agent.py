"""Task and Agent Definition behavior at the public domain boundary."""

import pytest

from ai_software_engineer.domain import (
    Agent,
    AgentDefinition,
    AgentRole,
    ArtifactKind,
    Task,
    TaskStatus,
)
from tests.domain.factories import make_agent, make_task


def test_valid_task_is_immutable_and_serializes_without_absent_optionals() -> None:
    task = make_task()

    assert task.status is TaskStatus.NEW
    assert "owner" not in task.to_wire()

    with pytest.raises(ValueError):
        task.status = TaskStatus.PLANNING


def test_agent_schema_name_has_a_stable_public_alias() -> None:
    assert Agent is AgentDefinition


def test_task_rejects_unknown_fields_and_malformed_ids() -> None:
    payload = make_task().to_wire()
    payload["unexpected"] = True

    with pytest.raises(ValueError):
        Task.model_validate(payload)

    payload = make_task().to_wire()
    payload["id"] = "invalid"

    with pytest.raises(ValueError):
        Task.model_validate(payload)


def test_task_rejects_attempts_beyond_its_budget() -> None:
    payload = make_task().to_wire()
    payload["attempts"] = 4

    with pytest.raises(ValueError, match="attempts cannot exceed max_attempts"):
        Task.model_validate(payload)


def test_task_rejects_conflicting_constraint_budget() -> None:
    payload = make_task().to_wire()
    payload["max_attempts"] = 2

    with pytest.raises(ValueError, match=r"constraints\.max_attempts"):
        Task.model_validate(payload)


@pytest.mark.parametrize(
    ("role", "output_kind"),
    (
        (AgentRole.ORCHESTRATOR, ArtifactKind.PLAN),
        (AgentRole.CODER, ArtifactKind.IMPLEMENTATION_REPORT),
        (AgentRole.QA, ArtifactKind.QA_REPORT),
        (AgentRole.REVIEWER, ArtifactKind.REVIEW_REPORT),
    ),
)
def test_each_agent_role_owns_exactly_one_output_artifact_kind(
    role: AgentRole, output_kind: ArtifactKind
) -> None:
    payload = make_agent().to_wire()
    payload["id"] = f"agent_{role}_001"
    payload["role"] = role
    payload["input_artifacts"] = []
    payload["output_artifacts"] = [output_kind]

    agent = AgentDefinition.model_validate(payload)

    assert agent.output_artifacts == (output_kind,)


def test_agent_rejects_an_output_owned_by_another_role() -> None:
    payload = make_agent().to_wire()
    payload["output_artifacts"] = ["qa-report"]

    with pytest.raises(ValueError, match=r"coder.*implementation-report"):
        AgentDefinition.model_validate(payload)


def test_non_orchestrator_cannot_change_state() -> None:
    payload = make_agent().to_wire()
    payload["permissions"] = {
        **make_agent().permissions.to_wire(),
        "can_change_state": True,
    }

    with pytest.raises(ValueError, match="only orchestrator"):
        AgentDefinition.model_validate(payload)


def test_no_v0_1_agent_can_merge() -> None:
    payload = make_agent().to_wire()
    payload["permissions"] = {
        **make_agent().permissions.to_wire(),
        "can_merge": True,
    }

    with pytest.raises(ValueError, match="merge"):
        AgentDefinition.model_validate(payload)
