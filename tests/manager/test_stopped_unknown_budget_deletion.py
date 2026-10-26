"""Physical deletion recognizes all exact UNKNOWN-settlement-owned state records."""

import pytest

from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait
from ai_software_engineer.multi_directory.purge import _owners
from ai_software_engineer.multi_directory.purge_state import (
    StateDeletionScope,
    verified_state_record,
)
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_stopped_unknown_budget import service_for

completed = completed_fixture


@pytest.mark.parametrize("completed", ["stopped_unknown_exhausted"], indirect=True)
def test_new_stopped_unknown_groups_are_owned_and_scope_checked(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    result = service.handle(HandleDeliveryWait.model_validate(f.queue.command().to_wire()))
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
    paths = tuple((f.root / "delivery-preflight").glob("stopped-unknown-budget-*.json"))
    assert len(paths) == 3
    for path in paths:
        wire = verified_state_record(path, sidecar, {}, expected)
        if wire.get("kind") == "stopped_unknown_budget_settlement":
            assert f.task.id in _owners(wire)
        with pytest.raises(ValueError):
            verified_state_record(
                path,
                sidecar,
                {},
                expected.model_copy(update={"task_ids": frozenset({"task_foreign"})}),
            )
