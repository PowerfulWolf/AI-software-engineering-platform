"""QA/Reviewer stop observations reach only the sealed outcome of their exact request."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.execution import NativeProcessStop, SynchronousToolLoopStop
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.agents.verifier_stop import (
    capture_verifier_stop,
    current_verifier_stop,
    record_verifier_stop,
)
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.owned_sessions import OwnedProcessIdentity, OwnedSessionStopProof
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
    DurableInvocationControl,
    sealed_verifier_stop,
)
from tests.agents.test_openai_compatible import _request
from tests.work_queue.test_invocation_journal import guard


def synchronous(request: AgentRequest, *, at: datetime | None = None) -> SynchronousToolLoopStop:
    return SynchronousToolLoopStop.create(
        task_id=request.task_id,
        run_id=request.run_id,
        request_sha256=digest(request.to_wire()),
        completed_operation_ids=("op_1",),
        kind="failed",
        stopped_at=at or datetime.now(UTC) + timedelta(seconds=1),
    )


def native(*, session: bool = True, kind: str = "failed") -> NativeProcessStop:
    stopped = datetime.now(UTC) + timedelta(seconds=1)
    leader = OwnedProcessIdentity(
        process_id=4242, group_id=4242, session_id=4242, birth_identity="fixture:leader"
    )
    proof = OwnedSessionStopProof.create(
        boot_identity="fixture:boot",
        leader=leader,
        observed_processes=(leader,),
        observation_count=2,
        observations_sha256="a" * 64,
        observed_at=stopped,
    )
    return NativeProcessStop.create(
        process_id=4242,
        group_id=4242,
        returncode=0 if kind == "completed" else 1,
        kind=kind,
        stopped_at=stopped,
        session_proof=proof if session else None,
    )


def rejected(request: AgentRequest, *, transient: bool = False) -> AgentResult:
    return AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.FAILED,
        error=AgentFailure(
            code=AgentErrorCode.INVALID_OUTPUT,
            message="output rejected by the platform contract",
            transient=transient,
        ),
    )


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
def test_capture_binds_only_the_exact_verifier_request(role: AgentRole) -> None:
    request = _request(role)
    other = request.model_copy(update={"run_id": "run_other_001"})
    assert current_verifier_stop(request) is None
    with capture_verifier_stop(request):
        record_verifier_stop(other, synchronous(other))
        assert current_verifier_stop(request) is None
        stop = synchronous(request)
        record_verifier_stop(request, stop)
        assert current_verifier_stop(request) == stop
        assert current_verifier_stop(other) is None
    assert current_verifier_stop(request) is None


def test_non_verifier_roles_and_legacy_native_stops_record_nothing() -> None:
    coder = _request(AgentRole.CODER)
    with capture_verifier_stop(coder):
        record_verifier_stop(coder, synchronous(coder))
        assert current_verifier_stop(coder) is None
    qa = _request(AgentRole.QA)
    with capture_verifier_stop(qa):
        record_verifier_stop(qa, native(session=False))
        assert current_verifier_stop(qa) is None, "a group stop cannot prove the session ended"
        record_verifier_stop(qa, None)
        assert current_verifier_stop(qa) is None
        owned = native()
        record_verifier_stop(qa, owned)
        assert current_verifier_stop(qa) == owned


@pytest.mark.parametrize("stop_kind", ["synchronous", "native"])
def test_rejected_verifier_outcome_seals_the_observed_stop(tmp_path: Path, stop_kind: str) -> None:
    request = _request(AgentRole.QA)
    control = DurableInvocationControl(KnowledgeRecordStore(tmp_path), guard(request))
    control.prepare(request)
    stop = synchronous(request) if stop_kind == "synchronous" else native()
    with capture_verifier_stop(request):
        record_verifier_stop(request, stop)
        control.completed(request, rejected(request))
    outcome = control.records.get(
        "invocation-outcomes", "work_invocation_001", DeliveryInvocationOutcome
    )
    outcome.validate_integrity()
    assert outcome.verifier_stop == stop
    start = control.records.get("invocation-starts", "work_invocation_001", DeliveryInvocationStart)
    assert sealed_verifier_stop(KnowledgeRecordStore(tmp_path, read_only=True), start) == stop
    other = start.model_copy(update={"lease_id": "lease_other"})
    assert sealed_verifier_stop(KnowledgeRecordStore(tmp_path, read_only=True), other) is None


@pytest.mark.parametrize("case", ["transient", "other_code", "coder", "uncaptured", "early"])
def test_other_outcomes_keep_no_stop_and_their_historical_wire(tmp_path: Path, case: str) -> None:
    request = _request(AgentRole.CODER if case == "coder" else AgentRole.REVIEWER)
    control = DurableInvocationControl(KnowledgeRecordStore(tmp_path), guard(request))
    control.prepare(request)
    result = rejected(request, transient=case == "transient")
    if case == "other_code":
        assert result.error is not None
        result = result.model_copy(
            update={
                "error": result.error.model_copy(update={"code": AgentErrorCode.POLICY_VIOLATION})
            }
        )
    stop = synchronous(request, at=datetime(2000, 1, 1, tzinfo=UTC) if case == "early" else None)
    if case == "uncaptured":
        record_verifier_stop(request, stop)
        control.completed(request, result)
    else:
        with capture_verifier_stop(request):
            record_verifier_stop(request, stop)
            control.completed(request, result)
    outcome = control.records.get(
        "invocation-outcomes", "work_invocation_001", DeliveryInvocationOutcome
    )
    assert outcome.verifier_stop is None
    assert "verifier_stop" not in outcome.to_wire()


def test_outcome_rejects_a_stop_for_another_request_or_ineligible_result(tmp_path: Path) -> None:
    request = _request(AgentRole.QA)
    control = DurableInvocationControl(KnowledgeRecordStore(tmp_path), guard(request))
    control.prepare(request)
    with capture_verifier_stop(request):
        record_verifier_stop(request, synchronous(request))
        control.completed(request, rejected(request))
    outcome = control.records.get(
        "invocation-outcomes", "work_invocation_001", DeliveryInvocationOutcome
    )
    other = request.model_copy(update={"run_id": "run_other_001"})
    wire = outcome.to_wire()
    with pytest.raises(ValueError):
        DeliveryInvocationOutcome.model_validate(
            {**wire, "verifier_stop": synchronous(other).to_wire()}
        )
    with pytest.raises(ValueError):
        DeliveryInvocationOutcome.model_validate(
            {**wire, "result": rejected(request, transient=True).to_wire()}
        )
    with pytest.raises(ValueError):
        DeliveryInvocationOutcome.model_validate(
            {**wire, "verifier_stop": native(session=False).to_wire()}
        )


def test_responses_qa_records_its_returned_tool_loop_for_a_rejected_output(
    tmp_path: Path,
) -> None:
    import json
    from collections.abc import Mapping

    from ai_software_engineer.agents import HttpResponse
    from tests.agents.test_responses import _repository
    from tests.agents.test_responses_boundary_diagnostics import _adapter, _qa

    root, base = _repository(tmp_path)
    request, definition = _qa(base)

    class Malformed:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            del url, headers, body, timeout_seconds
            return HttpResponse(
                status_code=200, body=json.dumps({"output_text": "{not json"}).encode()
            )

    with capture_verifier_stop(request):
        result = _adapter(root, definition, Malformed()).run(request)
        stop = current_verifier_stop(request)
    assert result.error is not None and result.error.code is AgentErrorCode.INVALID_OUTPUT
    assert isinstance(stop, SynchronousToolLoopStop)
    stop.require_request(request)
    # Outside the runner's capture nothing is recorded or retained.
    retried = request.model_copy(update={"run_id": "run_qa_boundary_002"})
    _adapter(root, definition, Malformed()).run(retried)
    assert current_verifier_stop(retried) is None


def test_codex_qa_records_the_runner_owned_session_stop(tmp_path: Path) -> None:
    import json
    from dataclasses import replace

    from ai_software_engineer.agents.codex_cli import CodexCliAgentAdapter, CodexInvocationResult
    from tests.agents.test_codex_cli import _ArtifactOutputRunner, _repository
    from tests.agents.test_codex_cli import _request as codex_request
    from tests.agents.test_openai_compatible import StaticPromptBuilder
    from tests.domain.factories import make_qa_artifact

    root, base = _repository(tmp_path)
    payload = json.loads(make_qa_artifact().model_dump_json())
    payload["producer"]["role"] = "coder"
    owned = native(kind="completed")

    class OwnedStop(_ArtifactOutputRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def,override]
            result: CodexInvocationResult = super().run(argv, **kwargs)
            return replace(result, process_stop=owned)

    def run(request: AgentRequest) -> AgentResult:
        return CodexCliAgentAdapter(
            workspace_root=root,
            model="gpt-5.6-terra",
            agent_id="agent_qa_001",
            agent_version="v0.1",
            prompt_builder=StaticPromptBuilder(),
            runner=OwnedStop(payload),
        ).run(request)

    request = codex_request(AgentRole.QA, run_id="run_owned_stop", source_revision=base)
    with capture_verifier_stop(request):
        result = run(request)
        assert current_verifier_stop(request) == owned
    assert result.error is not None and result.error.code is AgentErrorCode.INVALID_OUTPUT
    coder = codex_request(AgentRole.CODER, run_id="run_owned_coder", source_revision=base)
    with capture_verifier_stop(coder):
        assert current_verifier_stop(coder) is None
