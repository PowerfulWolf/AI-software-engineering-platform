"""Designer adapter terminal behavior and replay tests."""

from pathlib import Path

import pytest

from ai_software_engineer.design import (
    DesignContextBuilder,
    DesignerAgentRequest,
    DesignerAgentRequestConflict,
    DesignerAgentRunStatus,
    FakeDesignerAgentAdapter,
    FakeDesignerBehavior,
    FakeDesignerScenario,
    RunDesignerCommand,
)
from tests.design.factories import NOW, approved_facts, design_for


def _request(tmp_path: Path) -> tuple[DesignerAgentRequest, RunDesignerCommand]:
    command, _, _ = approved_facts(tmp_path)
    context = DesignContextBuilder().build(
        command.preparation,
        command.project_profile,
        command.project_baseline,
        command.request_revision.request,
        command.product_spec,
        command.product_approval,
        command.solution_design_authorization,
        built_at=NOW,
    )
    return (
        DesignerAgentRequest(
            run_id=command.run_id,
            project_id=command.preparation.project_id,
            request_id=command.request_revision.request.id,
            context=context,
        ),
        command,
    )


@pytest.mark.parametrize(
    ("behavior", "status"),
    (
        (FakeDesignerBehavior.TIMEOUT, DesignerAgentRunStatus.TIMED_OUT),
        (FakeDesignerBehavior.INVALID_OUTPUT, DesignerAgentRunStatus.FAILED),
        (FakeDesignerBehavior.PROVIDER_ERROR, DesignerAgentRunStatus.FAILED),
    ),
)
def test_fake_failure_behaviors_are_typed(
    tmp_path: Path, behavior: FakeDesignerBehavior, status: DesignerAgentRunStatus
) -> None:
    request, _ = _request(tmp_path)
    result = FakeDesignerAgentAdapter(default=FakeDesignerScenario(behavior=behavior)).run(request)

    assert result.status is status
    assert result.error is not None
    assert result.technical_design is None


def test_fake_ready_replays_exact_request_and_rejects_changed_run(tmp_path: Path) -> None:
    request, command = _request(tmp_path)
    adapter = FakeDesignerAgentAdapter(
        default=FakeDesignerScenario(
            behavior=FakeDesignerBehavior.READY,
            technical_design=design_for(command),
        )
    )
    first = adapter.run(request)

    assert first.status is DesignerAgentRunStatus.SUCCEEDED
    assert adapter.run(request.model_copy()) == first
    with pytest.raises(DesignerAgentRequestConflict):
        adapter.run(request.model_copy(update={"timeout_seconds": 30}))
