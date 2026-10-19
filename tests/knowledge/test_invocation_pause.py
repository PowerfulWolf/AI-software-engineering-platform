"""Host-owned admission refusals survive knowledge publication and replay."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents.execution import bind_execution_guard
from ai_software_engineer.agents.json_schema import strict_output_schema
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured import (
    CodexCliStructuredModelClient,
    FallbackStructuredModelClient,
    StructuredModelClient,
    StructuredModelError,
    StructuredModelResult,
    StructuredModelRoute,
)
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationIntent,
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    KnowledgeInvocationUncertain,
    KnowledgePreparationPaused,
    invocation_lane_sha256,
    knowledge_pause_proof_mode,
    read_paused_preparation,
)
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.service_pause import ServicePauseControl
from tests.knowledge.test_invocation_native import (
    _actual_claim,
    _http_client,
    _HttpTransport,
    _OwnerGuard,
)
from tests.knowledge.test_retrieval_contract import binding, snapshot


class _GenericPaused:
    def __init__(self) -> None:
        self.calls = 0

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
        raise StructuredModelError(AgentErrorCode.SERVICE_PAUSED, "fixture pause", transient=False)


class _PauseThenDelegate:
    def __init__(self, pause: ServicePauseControl, delegate: StructuredModelClient) -> None:
        self.pause, self.delegate = pause, delegate

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        self.pause.request(request_id="pause_exact", instance_id="instance_exact")
        return self.delegate.complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )


def _consultation(root: Path, delegate: StructuredModelClient) -> KnowledgeConsultationService:
    frozen = snapshot()
    bound = binding(frozen)
    claim = _actual_claim(bound)
    records = KnowledgeRecordStore(root)
    return KnowledgeConsultationService(
        FallbackStructuredModelClient(
            (StructuredModelRoute(provider="fixture", model="fixture", client=delegate),),
            role=bound.role,
        ),
        records,
        invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: claim),
    )


def _outcome(root: Path) -> KnowledgeInvocationOutcome:
    bound = binding(snapshot())
    records = KnowledgeRecordStore(
        root / "invocations" / invocation_lane_sha256(bound), read_only=True
    )
    return records.get(
        "knowledge-invocation-outcomes", bound.run_id + ":intent", KnowledgeInvocationOutcome
    )


@pytest.mark.parametrize(
    "origin",
    [
        "fallback_before_route",
        "native_client_entry",
        "responses_client_entry",
        "responses_before_transport_admission",
    ],
)
def test_exact_pre_admission_guard_is_durable_without_inventing_an_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    from ai_software_engineer.agents import structured
    from ai_software_engineer.agents.openai_compatible import HttpResponse

    pause = ServicePauseControl(grace_seconds=300)
    provider = _GenericPaused()
    transport = _HttpTransport(HttpResponse(200, b"{}"), before_return=lambda: None)
    delegate: StructuredModelClient = provider
    if origin == "native_client_entry":
        delegate = _PauseThenDelegate(
            pause,
            CodexCliStructuredModelClient(
                repository_root=tmp_path, model="fixture", executable="never-run", environment={}
            ),
        )
    elif origin == "responses_client_entry":
        delegate = _PauseThenDelegate(pause, _http_client(transport, "fixture"))
    elif origin == "responses_before_transport_admission":
        delegate = _http_client(transport, "fixture")

        def pause_schema(value: Mapping[str, object]) -> dict[str, object]:
            pause.request(request_id="pause_exact", instance_id="instance_exact")
            return strict_output_schema(value)

        monkeypatch.setattr(structured, "strict_output_schema", pause_schema)
    else:
        pause.request(request_id="pause_exact", instance_id="instance_exact")
    root = tmp_path / "knowledge"
    service = _consultation(root, delegate)
    with (
        pause.operation_scope("operation_exact"),
        pytest.raises(KnowledgePreparationPaused) as failed,
    ):
        service.consult(binding(snapshot()), snapshot(), {}, timeout_seconds=1)
    outcome = failed.value.outcome
    receipt = outcome.pre_admission_pause
    assert receipt is not None and receipt.origin == origin
    assert receipt.operation_id == "operation_exact"
    assert (
        receipt.pause_request_id == "pause_exact" and receipt.pause_instance_id == "instance_exact"
    )
    assert receipt.request_sha256 == outcome.intent.request_sha256
    assert receipt.phase == "knowledge_intent" and receipt.role is outcome.intent.binding.role
    assert (
        receipt.selected_call is None
        if origin == "fallback_before_route"
        else receipt.selected_call is not None
    )
    assert outcome.executions == () and provider.calls == transport.calls == 0
    assert pause.due_request() is None  # Admission closes during the grace window.
    assert knowledge_pause_proof_mode(outcome) == "pre_admission_refusal"
    assert read_paused_preparation(root, outcome.outcome_sha256) == outcome
    pause.cancel()  # Cancellation cannot erase the independently sealed refusal.
    assert read_paused_preparation(root, outcome.outcome_sha256) == outcome
    with pytest.raises(KnowledgePreparationPaused) as replay:
        service.consult(binding(snapshot()), snapshot(), {}, timeout_seconds=1)
    assert replay.value.outcome == outcome
    assert replay.value.with_context("replayed").outcome == outcome
    assert _outcome(root) == outcome and provider.calls == transport.calls == 0


def test_generic_service_paused_and_empty_executions_remain_unproven(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    provider = _GenericPaused()
    service = _consultation(root, provider)
    for _ in range(2):
        with pytest.raises(StructuredModelError) as failed:
            service.consult(binding(snapshot()), snapshot(), {}, timeout_seconds=1)
        assert type(failed.value) is StructuredModelError
    outcome = _outcome(root)
    assert provider.calls == 1 and outcome.executions == () and outcome.pre_admission_pause is None
    with pytest.raises(KnowledgeError):
        knowledge_pause_proof_mode(outcome)
    with pytest.raises(KnowledgeError):
        read_paused_preparation(root, outcome.outcome_sha256)
    # New optional fields must not change any old canonical nested digest bytes.
    wire = outcome.model_dump(mode="json")
    assert "pre_admission_pause" not in wire
    assert "pre_admission_pause" not in outcome.to_wire()
    assert outcome.outcome_sha256 == digest(
        {k: v for k, v in wire.items() if k != "outcome_sha256"}
    )
    assert KnowledgeInvocationOutcome.model_validate(wire) == outcome


@pytest.mark.parametrize(
    "namespace",
    ["structured-admission-pauses", "knowledge-invocation-outcomes", "knowledge-pause-intents"],
)
def test_failed_pause_publication_preserves_original_intent_and_never_calls_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, namespace: str
) -> None:
    root = tmp_path / "knowledge"
    provider = _GenericPaused()
    service = _consultation(root, provider)
    pause = ServicePauseControl()
    pause.request()
    original_put = KnowledgeRecordStore.put

    def reject[T: DomainModel](
        store: KnowledgeRecordStore, selected: str, key: str, record: T
    ) -> T:
        if selected == namespace:
            raise OSError("fixture publication failure")
        return original_put(store, selected, key, record)

    monkeypatch.setattr(KnowledgeRecordStore, "put", reject)
    with pause.operation_scope("operation_exact"), pytest.raises(KnowledgeInvocationUncertain):
        service.consult(binding(snapshot()), snapshot(), {}, timeout_seconds=1)
    monkeypatch.setattr(KnowledgeRecordStore, "put", original_put)
    pause.cancel()
    with pytest.raises(KnowledgeInvocationUncertain):
        service.consult(binding(snapshot()), snapshot(), {}, timeout_seconds=1)
    assert provider.calls == 0


def test_actual_native_admission_closed_pair_remains_distinct_from_pre_admission_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.agents import structured_execution
    from ai_software_engineer.agents.structured_observation import (
        StructuredExecutionAdmission,
        StructuredNativeNotStartedReceipt,
        admit_structured_execution,
    )

    pause = ServicePauseControl()

    def admit_then_pause(
        *, execution_kind: str, transport_request_sha256: str, timeout_seconds: float
    ) -> StructuredExecutionAdmission | None:
        assert execution_kind == "native"
        admission = admit_structured_execution(
            execution_kind="native",
            transport_request_sha256=transport_request_sha256,
            timeout_seconds=timeout_seconds,
        )
        pause.request()
        return admission

    monkeypatch.setattr(structured_execution, "admit_structured_execution", admit_then_pause)
    root = tmp_path / "knowledge"
    service = _consultation(
        root,
        CodexCliStructuredModelClient(
            repository_root=tmp_path, model="fixture", executable="never-run", environment={}
        ),
    )
    with (
        pause.operation_scope("operation_exact"),
        pytest.raises(KnowledgePreparationPaused) as failed,
    ):
        service.consult(binding(snapshot()), snapshot(), {}, timeout_seconds=1)
    outcome = failed.value.outcome
    assert outcome.pre_admission_pause is None and len(outcome.executions) == 2
    assert isinstance(outcome.executions[0].observation, StructuredExecutionAdmission)
    receipt = outcome.executions[1].observation
    assert isinstance(receipt, StructuredNativeNotStartedReceipt)
    assert receipt.failure_kind == "service_pause_admission_closed"
    assert knowledge_pause_proof_mode(outcome) == "native_admission_closed"
    assert read_paused_preparation(root, outcome.outcome_sha256) == outcome


def test_posted_http_before_fallback_pause_never_acquires_whole_call_no_start(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.agents.openai_compatible import HttpResponse

    pause = ServicePauseControl()
    transport = _HttpTransport(
        HttpResponse(504, b"fixture gateway timeout"), before_return=pause.request
    )
    backup = _GenericPaused()
    root = tmp_path / "knowledge"
    records = KnowledgeRecordStore(root)
    bound = binding(snapshot())
    claim = _actual_claim(bound)
    service = KnowledgeConsultationService(
        FallbackStructuredModelClient(
            (
                StructuredModelRoute(
                    provider="fixture", model="first", client=_http_client(transport, "first")
                ),
                StructuredModelRoute(provider="fixture", model="backup", client=backup),
            ),
            role=bound.role,
        ),
        records,
        invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: claim),
    )
    with pause.operation_scope("operation_exact"), pytest.raises(StructuredModelError) as failed:
        service.consult(bound, snapshot(), {}, timeout_seconds=1)
    assert not isinstance(failed.value, KnowledgePreparationPaused)
    outcome = _outcome(root)
    assert len(outcome.executions) == 2 and outcome.pre_admission_pause is not None
    assert transport.calls == 1 and backup.calls == 0
    with pytest.raises(KnowledgeError):
        knowledge_pause_proof_mode(outcome)
    with pytest.raises(KnowledgeError):
        read_paused_preparation(root, outcome.outcome_sha256)
    assert (
        KnowledgeRecordStore(root, read_only=True).list(
            "knowledge-pause-intents", KnowledgeInvocationIntent
        )
        == ()
    )


@pytest.mark.parametrize(
    "missing",
    [
        "structured-admission-pauses",
        "knowledge-invocation-intents",
        "knowledge-invocation-outcomes",
        "knowledge-pause-intents",
    ],
)
def test_independent_pause_receipt_and_index_are_required_on_reopen(
    tmp_path: Path, missing: str
) -> None:
    root = tmp_path / "knowledge"
    provider = _GenericPaused()
    service = _consultation(root, provider)
    pause = ServicePauseControl()
    pause.request()
    with (
        pause.operation_scope("operation_exact"),
        pytest.raises(KnowledgePreparationPaused) as failed,
    ):
        service.consult(binding(snapshot()), snapshot(), {}, timeout_seconds=1)
    (path,) = root.rglob(missing + "-*.json")
    path.unlink()
    with pytest.raises((KnowledgeError, KnowledgeInvocationUncertain)):
        read_paused_preparation(root, failed.value.outcome.outcome_sha256)
    assert provider.calls == 0


def test_owner_loss_before_pause_publication_cannot_publish_resume_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = _OwnerGuard()
    pause = ServicePauseControl()
    original_request = pause.request

    def lose_owner(*, request_id: str | None = None, instance_id: str | None = None) -> None:
        original_request(request_id=request_id, instance_id=instance_id)
        guard.alive = False

    monkeypatch.setattr(pause, "request", lose_owner)
    root = tmp_path / "knowledge"
    service = _consultation(
        root,
        _PauseThenDelegate(
            pause,
            CodexCliStructuredModelClient(
                repository_root=tmp_path, model="fixture", executable="never-run", environment={}
            ),
        ),
    )
    with (
        pytest.raises(RuntimeError, match="fixture owner lost"),
        pause.operation_scope("operation_exact"),
        bind_execution_guard(guard),
    ):
        service.consult(binding(snapshot()), snapshot(), {}, timeout_seconds=1)
    records = KnowledgeRecordStore(root, read_only=True)
    assert records.list("knowledge-pause-intents", KnowledgeInvocationIntent) == ()
    bound = binding(snapshot())
    lane = KnowledgeRecordStore(
        root / "invocations" / invocation_lane_sha256(bound), read_only=True
    )
    assert len(lane.list("knowledge-invocation-intents", KnowledgeInvocationIntent)) == 1
    assert lane.list("knowledge-invocation-outcomes", KnowledgeInvocationOutcome) == ()
