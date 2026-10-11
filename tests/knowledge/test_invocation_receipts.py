"""Preparation calls must leave exact durable facts even when the model fails."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured import StructuredModelError, StructuredModelResult
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    KnowledgeInvocationUncertain,
    invocation_lane_sha256,
    invocation_scope_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeRunBinding
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.knowledge.test_retrieval_contract import binding, snapshot


@pytest.mark.parametrize("role", list(TeamRole))
def test_failed_preparation_is_recorded_before_model_call(tmp_path: Path, role: TeamRole) -> None:
    records = KnowledgeRecordStore(tmp_path)

    class LimitedClient:
        def complete(
            self,
            *,
            instructions: str,
            input_payload: Mapping[str, object],
            output_schema: Mapping[str, object],
            timeout_seconds: int,
            input_images: tuple[Path, ...] = (),
        ) -> StructuredModelResult:
            assert len(tuple(tmp_path.rglob("knowledge-invocation-intents-*.json"))) == 1
            raise StructuredModelError(
                AgentErrorCode.TIMEOUT,
                "fixture local time limit",
                transient=False,
                timeout_kind="local_execution_limit",
            )

    frozen = snapshot()
    with pytest.raises(StructuredModelError, match="fixture local time limit"):
        KnowledgeConsultationService(LimitedClient(), records).consult(
            binding(frozen, role), frozen, {}, timeout_seconds=2
        )
    assert len(tuple(tmp_path.rglob("knowledge-invocation-outcomes-*.json"))) == 1


class CountingClient:
    def __init__(self, failure: StructuredModelError | None = None) -> None:
        self.calls = 0
        self.failure = failure

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return StructuredModelResult({"queries": []}, 9, provider="fixture", model="actual-model")


def call(
    root: Path,
    bound: KnowledgeRunBinding,
    client: CountingClient,
    *,
    instructions: str = "prepare",
    payload: Mapping[str, object] | None = None,
    schema: Mapping[str, object] | None = None,
    timeout: int = 2,
) -> StructuredModelResult:
    return KnowledgeInvocationJournal(KnowledgeRecordStore(root)).call(
        bound,
        "intent",
        client=client,
        instructions=instructions,
        input_payload={"task": "fixture"} if payload is None else payload,
        output_schema={"type": "object"} if schema is None else schema,
        timeout_seconds=timeout,
    )


@pytest.mark.parametrize("role", list(TeamRole))
def test_reopened_success_replays_without_model_call(tmp_path: Path, role: TeamRole) -> None:
    bound = binding(snapshot(), role)
    first = CountingClient()
    expected = call(tmp_path, bound, first)
    replacement = CountingClient()
    assert call(tmp_path, bound, replacement) == expected
    assert first.calls == 1 and replacement.calls == 0


def test_replayed_failure_preserves_typed_metadata(tmp_path: Path) -> None:
    bound = binding(snapshot())
    first = CountingClient(
        StructuredModelError(
            AgentErrorCode.TIMEOUT,
            "local execution ended",
            transient=False,
            timeout_kind="local_execution_limit",
            http_status=504,
            request_id="fixture-request",
            correlation_id="fixture-correlation",
        )
    )
    with pytest.raises(StructuredModelError):
        call(tmp_path, bound, first)
    replacement = CountingClient()
    with pytest.raises(StructuredModelError) as captured:
        call(tmp_path, bound, replacement)
    error = captured.value
    assert error.code is AgentErrorCode.TIMEOUT and error.expandable_timeout
    assert not error.retryable and not error.transient
    assert (error.http_status, error.request_id, error.correlation_id) == (
        504,
        "fixture-request",
        "fixture-correlation",
    )
    assert first.calls == 1 and replacement.calls == 0


@pytest.mark.parametrize("changed", ["instructions", "payload", "schema", "timeout", "source"])
def test_exact_replay_rejects_changed_inputs(tmp_path: Path, changed: str) -> None:
    bound = binding(snapshot())
    call(tmp_path, bound, CountingClient())
    replacement = CountingClient()
    with pytest.raises(KnowledgeInvocationUncertain):
        call(
            tmp_path,
            bound.model_copy(update={"source_revision": "c" * 40})
            if changed == "source"
            else bound,
            replacement,
            instructions="changed" if changed == "instructions" else "prepare",
            payload={"task": "changed"} if changed == "payload" else None,
            schema={"type": "string"} if changed == "schema" else None,
            timeout=3 if changed == "timeout" else 2,
        )
    assert replacement.calls == 0


def test_scope_helper_preserves_lane_without_fake_binding() -> None:
    bound = binding(snapshot())
    assert invocation_scope_lane_sha256(
        team_id=bound.team_id,
        project_id=bound.project_id,
        requirement_id=bound.requirement_id,
        repository_ids=bound.repository_ids,
        task_id=bound.task_id,
        role=bound.role,
    ) == invocation_lane_sha256(bound)
    assert invocation_lane_sha256(bound) == invocation_lane_sha256(
        bound.model_copy(
            update={
                "run_id": "run_changed",
                "source_revision": "c" * 40,
                "context_manifest_id": "ctx_" + "c" * 64,
            }
        )
    )


def test_corrupt_completed_result_cannot_be_replayed(tmp_path: Path) -> None:
    bound = binding(snapshot())
    call(tmp_path, bound, CountingClient())
    lane = KnowledgeRecordStore(tmp_path / "invocations" / invocation_lane_sha256(bound))
    outcome = lane.get(
        "knowledge-invocation-outcomes", bound.run_id + ":intent", KnowledgeInvocationOutcome
    )
    outcome.validate_integrity()
    (path,) = tuple(lane.root.glob("knowledge-invocation-outcomes-*.json"))
    path.write_text('{"record": {}, "sha256": "wrong"}')
    replacement = CountingClient()
    with pytest.raises(KnowledgeInvocationUncertain):
        call(tmp_path, bound, replacement)
    assert replacement.calls == 0
