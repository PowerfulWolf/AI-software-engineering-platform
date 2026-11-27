"""A Coder stopped early for lack of plan progress recovers like an exhausted budget."""

from types import SimpleNamespace

import pytest

from ai_software_engineer.agents.fallback import RouteAttemptOutcome
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.manager.delivery_checkpoint import DeliveryFailureCode
from ai_software_engineer.orchestration.retry import CODER_STALL_REASON
from ai_software_engineer.recovery import native
from tests.domain.factories import make_coder_progress_artifact


def _facts(*, exhausted: bool, summary: str, code: DeliveryFailureCode) -> tuple[object, ...]:
    template = make_coder_progress_artifact()
    progress = template.model_copy(
        update={"content": template.content.model_copy(update={"checkpoint_sequence": 4})}
    )
    route = SimpleNamespace(
        task_id="task_x",
        role=AgentRole.CODER,
        outcome=RouteAttemptOutcome.SUCCEEDED,
        result=SimpleNamespace(attempt=4, artifact=progress),
    )
    task = SimpleNamespace(id="task_x", attempts=4, work_budget_exhausted=exhausted)
    checkpoint = SimpleNamespace(failure_summary=summary, failure_code=code)
    return route, task, checkpoint


@pytest.mark.parametrize(
    ("exhausted", "summary", "code", "recoverable"),
    [
        (
            True,
            "Coder requested continuation after the configured run budget",
            DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
            True,
        ),
        (False, CODER_STALL_REASON, DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED, True),
        (
            False,
            "Coder requested continuation after the configured run budget",
            DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
            False,
        ),
        (False, CODER_STALL_REASON, DeliveryFailureCode.TRANSIENT_PROVIDER_FAILURE, False),
    ],
)
def test_stalled_coder_progress_is_a_recoverable_native_source(
    monkeypatch: pytest.MonkeyPatch,
    exhausted: bool,
    summary: str,
    code: DeliveryFailureCode,
    recoverable: bool,
) -> None:
    monkeypatch.setattr(native, "is_prior_progress_source", lambda *args: False)
    route, task, checkpoint = _facts(exhausted=exhausted, summary=summary, code=code)
    assert native._is_recoverable_terminal_coder_route(route, task, checkpoint) is recoverable  # type: ignore[arg-type]
