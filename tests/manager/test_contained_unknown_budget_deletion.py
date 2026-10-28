"""Physical deletion recognizes every contained-UNKNOWN-owned state group."""

import pytest

from ai_software_engineer.domain.contained_unknown_budget import ContainedUnknownBudgetSettlement
from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait
from ai_software_engineer.multi_directory.purge import _owners
from ai_software_engineer.multi_directory.purge_state import (
    StateDeletionScope,
    verified_state_record,
)
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_contained_unknown_budget import contained_service_for

completed = completed_fixture


@pytest.mark.parametrize("completed", ["start_only_unknown_exhausted"], indirect=True)
def test_contained_unknown_groups_are_owned_and_scope_checked(
    completed: CompletedFixture,
) -> None:
    f = completed
    result = contained_service_for(f).handle(
        HandleDeliveryWait.model_validate(
            {
                **f.queue.command().to_wire(),
                "confirm_local_execution_stopped": True,
                "local_stop_reference": "call_a7e4ebe2aed34bad899f8cc3588da3b5",
            }
        )
    )
    assert result.budget_settlement_sha256 is not None
    scope = f.collector.scope
    expected = StateDeletionScope(
        team_id=scope.team_id,
        project_id=scope.project_id,
        repository_id=scope.repository_id,
        repository_root=scope.repository_root,
        requirement_ids=frozenset({f.native.scope.requirement_id}),
        task_ids=frozenset({f.task.id}),
    )
    sidecar = f.root.parent
    paths = tuple((f.root / "delivery-preflight").glob("contained-unknown-budget-*.json"))
    assert len(paths) == 3
    for path in paths:
        wire = verified_state_record(path, sidecar, {}, expected)
        if wire.get("kind") == "contained_unknown_budget_settlement":
            assert f.task.id in _owners(wire)
            assert ContainedUnknownBudgetSettlement.model_validate(wire).settlement_sha256 == (
                result.budget_settlement_sha256
            )
        with pytest.raises(ValueError):
            verified_state_record(
                path,
                sidecar,
                {},
                expected.model_copy(update={"task_ids": frozenset({"task_foreign"})}),
            )
