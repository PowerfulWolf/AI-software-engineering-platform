"""Real knowledge preparation processes leave independently replayable stop facts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import pytest

from ai_software_engineer.agents.codex_cli import (
    CodexExecutionUnconfirmed,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.execution import bind_execution_guard
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.openai_compatible import HttpResponse
from ai_software_engineer.agents.structured import (
    CodexCliStructuredModelClient,
    FallbackStructuredModelClient,
    ResponsesStructuredModelClient,
    StructuredModelError,
    StructuredModelRoute,
)
from ai_software_engineer.agents.structured_observation import (
    StructuredExecutionAdmission,
    StructuredHttpRoundTripReceipt,
    StructuredNativeNotStartedReceipt,
    StructuredNativeStopReceipt,
)
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationIntent,
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    KnowledgeInvocationUncertain,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeRunBinding
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue.models import QueueClaim
from tests.domain.factories import make_task
from tests.knowledge.test_retrieval_contract import binding, snapshot
from tests.orchestration.test_native_continuation import claim as native_claim

NativeOutcome = Literal["success", "invalid", "nonzero", "timeout"]


def _executable(tmp_path: Path, outcome: NativeOutcome) -> Path:
    executable = tmp_path / "fixture-codex"
    source = {
        "success": (
            "Path(sys.argv[sys.argv.index('--output-last-message') + 1])"
            ".write_text('{\"queries\": []}')"
        ),
        "invalid": (
            "Path(sys.argv[sys.argv.index('--output-last-message') + 1]).write_text('not-json')"
        ),
        "nonzero": "raise SystemExit(7)",
        "timeout": "import time; time.sleep(4)",
    }[outcome]
    executable.write_text(
        f"#!{sys.executable}\nimport sys\nimport json\nfrom pathlib import Path\n"
        "with Path('started').open('a') as started:\n    started.write('started\\n')\n"
        "intents = list(Path('knowledge/invocations')"
        ".rglob('knowledge-invocation-intents-*.json'))\n"
        "assert len(intents) == 1\n"
        "observations = list(Path('knowledge/invocations')"
        ".rglob('knowledge-execution-records-*.json'))\n"
        "assert len(observations) == 1\n"
        "intent = json.loads(intents[0].read_text())['record']\n"
        "admission = json.loads(observations[0].read_text())['record']\n"
        "assert admission['intent_sha256'] == intent['intent_sha256']\n"
        "assert admission['observation']['kind'] == 'structured_execution_admission'\n"
        f"{source}\n"
    )
    executable.chmod(0o700)
    return executable


def _client(
    root: Path, executable: Path, role: TeamRole, *, backup: Path | None = None
) -> FallbackStructuredModelClient:
    executables = (executable,) if backup is None else (executable, backup)
    return FallbackStructuredModelClient(
        tuple(
            StructuredModelRoute(
                provider="fixture",
                model="fixture-model" if index == 1 else "fixture-backup",
                client=CodexCliStructuredModelClient(
                    repository_root=root,
                    model="fixture-model" if index == 1 else "fixture-backup",
                    executable=str(route_executable),
                    environment={},
                ),
            )
            for index, route_executable in enumerate(executables, 1)
        ),
        role=role,
    )


def _lane(root: Path, bound: KnowledgeRunBinding) -> KnowledgeRecordStore:
    return KnowledgeRecordStore(
        root / "invocations" / invocation_lane_sha256(bound), read_only=True
    )


def _known_records(
    root: Path, bound: KnowledgeRunBinding
) -> tuple[KnowledgeInvocationIntent, KnowledgeInvocationOutcome]:
    records = _lane(root, bound)
    key = bound.run_id + ":intent"
    intent = records.get("knowledge-invocation-intents", key, KnowledgeInvocationIntent)
    outcome = records.get("knowledge-invocation-outcomes", key, KnowledgeInvocationOutcome)
    intent.validate_integrity()
    outcome.validate_integrity()
    assert intent.binding == bound and intent.phase == "intent"
    assert intent.timeout_seconds == 1
    assert outcome.intent == intent and len(outcome.executions) == 2
    admission, stopped = (record.observation for record in outcome.executions)
    assert isinstance(admission, StructuredExecutionAdmission)
    assert isinstance(stopped, StructuredNativeStopReceipt)
    assert stopped.admission == admission
    assert admission.call.role is bound.role
    assert admission.call.phase == "knowledge_intent"
    assert admission.call.request_sha256 == intent.request_sha256
    assert admission.call.route_index == 1
    assert admission.call.provider == "fixture" and admission.call.model == "fixture-model"
    assert stopped.process_stop.process_id == stopped.process_stop.group_id
    assert stopped.process_stop.stopped_at >= intent.created_at
    for record in outcome.executions:
        record.validate_integrity()
        assert record.intent_sha256 == intent.intent_sha256
        assert (
            records.get(
                "knowledge-execution-records", record.record_sha256, KnowledgeExecutionRecord
            )
            == record
        )
    assert len(records.list("knowledge-execution-records", KnowledgeExecutionRecord)) == 2
    return intent, outcome


_REOPEN_FAILED = """
import json
import sys
from pathlib import Path
from ai_software_engineer.agents.structured import (
    CodexCliStructuredModelClient, FallbackStructuredModelClient, StructuredModelError,
    StructuredModelRoute,
)
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord, KnowledgeInvocationOutcome, invocation_lane_sha256,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.knowledge.test_retrieval_contract import binding, snapshot
root, executable = Path(sys.argv[1]), Path(sys.argv[2])
frozen = snapshot()
bound = binding(frozen, TeamRole.CODER)
records = KnowledgeRecordStore(root)
lane = KnowledgeRecordStore(root / 'invocations' / invocation_lane_sha256(bound), read_only=True)
outcome = lane.get(
    'knowledge-invocation-outcomes', bound.run_id + ':intent', KnowledgeInvocationOutcome,
)
outcome.validate_integrity()
for record in outcome.executions:
    record.validate_integrity()
    assert lane.get(
        'knowledge-execution-records', record.record_sha256, KnowledgeExecutionRecord,
    ) == record
client = FallbackStructuredModelClient((StructuredModelRoute(
    provider='fixture', model='fixture-model', client=CodexCliStructuredModelClient(
        repository_root=executable.parent, model='fixture-model', executable=str(executable),
        environment={},
    ),
),), role=TeamRole.CODER)
try:
    KnowledgeConsultationService(client, records).consult(bound, frozen, {}, timeout_seconds=1)
except StructuredModelError as error:
    print(json.dumps({'code': error.code.value, 'timeout_kind': error.timeout_kind,
                      'outcome_sha256': outcome.outcome_sha256}))
else:
    raise AssertionError('The failed original call was not replayed')
"""


@pytest.mark.parametrize("role", list(TeamRole))
@pytest.mark.parametrize("native_outcome", ["timeout", "invalid", "nonzero"])
def test_real_consultation_failure_has_durable_native_receipts_and_never_restarts_same_run(
    tmp_path: Path, role: TeamRole, native_outcome: NativeOutcome
) -> None:
    executable = _executable(tmp_path, native_outcome)
    root = tmp_path / "knowledge"
    frozen = snapshot()
    bound = binding(frozen, role)
    service = KnowledgeConsultationService(
        _client(tmp_path, executable, role), KnowledgeRecordStore(root)
    )
    with pytest.raises(StructuredModelError) as failed:
        service.consult(bound, frozen, {}, timeout_seconds=1)
    intent, outcome = _known_records(root, bound)
    assert outcome.state == "FAILED" and outcome.result is None
    assert outcome.failure is not None and outcome.failure.code == failed.value.code
    stop = outcome.executions[-1].observation
    assert isinstance(stop, StructuredNativeStopReceipt)
    assert (
        stop.process_stop.kind
        == {"timeout": "local_execution_limit", "invalid": "completed", "nonzero": "failed"}[
            native_outcome
        ]
    )
    if native_outcome == "timeout":
        assert failed.value.code is AgentErrorCode.TIMEOUT
        assert failed.value.expandable_timeout and not failed.value.retryable
        assert outcome.failure.timeout_kind == "local_execution_limit"
    if native_outcome == "invalid":
        assert failed.value.code is AgentErrorCode.INVALID_OUTPUT
    reopened = KnowledgeConsultationService(
        _client(tmp_path, executable, role), KnowledgeRecordStore(root)
    )
    with pytest.raises(StructuredModelError) as replay:
        reopened.consult(bound, frozen, {}, timeout_seconds=1)
    assert replay.value.code == failed.value.code
    assert _known_records(root, bound) == (intent, outcome)
    assert (tmp_path / "started").read_text().splitlines() == ["started"]
    if role is TeamRole.CODER:
        child = subprocess.run(
            (sys.executable, "-c", _REOPEN_FAILED, str(root), str(executable)),
            cwd=Path(__file__).resolve().parents[2],
            env={
                "PATH": os.defpath,
                "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            },
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        assert json.loads(child.stdout) == {
            "code": failed.value.code.value,
            "timeout_kind": failed.value.timeout_kind,
            "outcome_sha256": outcome.outcome_sha256,
        }
        assert (tmp_path / "started").read_text().splitlines() == ["started"]


@pytest.mark.parametrize("native_outcome", ["success", "invalid"])
def test_outcome_publication_failure_preserves_the_independent_real_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_outcome: NativeOutcome
) -> None:
    executable = _executable(tmp_path, native_outcome)
    root = tmp_path / "knowledge"
    frozen = snapshot()
    bound = binding(frozen)
    original_put = KnowledgeRecordStore.put

    def fail_outcome[T: DomainModel](
        records: KnowledgeRecordStore, namespace: str, key: str, record: T
    ) -> T:
        if namespace == "knowledge-invocation-outcomes":
            raise OSError("fixture outcome write failed")
        return original_put(records, namespace, key, record)

    monkeypatch.setattr(KnowledgeRecordStore, "put", fail_outcome)
    service = KnowledgeConsultationService(
        _client(tmp_path, executable, bound.role), KnowledgeRecordStore(root)
    )
    with pytest.raises(KnowledgeInvocationUncertain):
        service.consult(bound, frozen, {}, timeout_seconds=1)
    monkeypatch.setattr(KnowledgeRecordStore, "put", original_put)
    records = _lane(root, bound)
    intent = records.get(
        "knowledge-invocation-intents", bound.run_id + ":intent", KnowledgeInvocationIntent
    )
    observations = records.list("knowledge-execution-records", KnowledgeExecutionRecord)
    assert len(observations) == 2
    assert {type(item.observation) for item in observations} == {
        StructuredExecutionAdmission,
        StructuredNativeStopReceipt,
    }
    for record in observations:
        record.validate_integrity()
        assert record.intent_sha256 == intent.intent_sha256
    assert records.list("knowledge-invocation-outcomes", KnowledgeInvocationOutcome) == ()
    with pytest.raises(KnowledgeInvocationUncertain):
        service.consult(bound, frozen, {}, timeout_seconds=1)
    changed = bound.model_copy(
        update={"run_id": "run_after_write_failure", "context_manifest_id": "ctx_" + "d" * 64}
    )
    with pytest.raises(KnowledgeInvocationUncertain):
        service.consult(changed, frozen, {}, timeout_seconds=1)
    assert (tmp_path / "started").read_text().splitlines() == ["started"]


def test_lost_stop_receipt_leaves_pending_original_and_blocks_new_execution_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = _executable(tmp_path, "success")
    root = tmp_path / "knowledge"
    frozen = snapshot()
    bound = binding(frozen)
    run_observed = SubprocessCodexCommandRunner.run_observed

    def lose_receipt(
        runner: SubprocessCodexCommandRunner,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: int,
        observer: Callable[[CodexInvocationResult], None],
    ) -> CodexInvocationResult:
        run_observed(
            runner,
            argv,
            cwd=cwd,
            environment=environment,
            stdin=stdin,
            timeout_seconds=timeout_seconds,
            observer=lambda _: None,
        )
        raise CodexExecutionUnconfirmed("fixture actual stop receipt unavailable")

    monkeypatch.setattr(SubprocessCodexCommandRunner, "run_observed", lose_receipt)
    service = KnowledgeConsultationService(
        _client(tmp_path, executable, bound.role), KnowledgeRecordStore(root)
    )
    with pytest.raises(KnowledgeInvocationUncertain):
        service.consult(bound, frozen, {}, timeout_seconds=1)
    monkeypatch.setattr(SubprocessCodexCommandRunner, "run_observed", run_observed)
    records = _lane(root, bound)
    (intent,) = records.list("knowledge-invocation-intents", KnowledgeInvocationIntent)
    (execution,) = records.list("knowledge-execution-records", KnowledgeExecutionRecord)
    assert intent.binding == bound and execution.intent_sha256 == intent.intent_sha256
    assert isinstance(execution.observation, StructuredExecutionAdmission)
    assert records.list("knowledge-invocation-outcomes", KnowledgeInvocationOutcome) == ()
    reopened = KnowledgeConsultationService(
        _client(tmp_path, executable, bound.role), KnowledgeRecordStore(root)
    )
    for candidate in (
        bound,
        bound.model_copy(update={"run_id": "run_new_preparation"}),
        bound.model_copy(
            update={
                "run_id": "run_changed_source_context",
                "source_revision": "f" * 40,
                "context_manifest_id": "ctx_" + "e" * 64,
            }
        ),
    ):
        with pytest.raises(KnowledgeInvocationUncertain):
            reopened.consult(candidate, frozen, {}, timeout_seconds=1)
    assert records.list("knowledge-invocation-intents", KnowledgeInvocationIntent) == (intent,)
    assert records.list("knowledge-execution-records", KnowledgeExecutionRecord) == (execution,)
    assert records.list("knowledge-invocation-outcomes", KnowledgeInvocationOutcome) == ()
    assert (tmp_path / "started").read_text().splitlines() == ["started"]


def test_real_successful_consultation_preserves_stop_without_creating_an_acceptance_verdict(
    tmp_path: Path,
) -> None:
    executable = _executable(tmp_path, "success")
    root = tmp_path / "knowledge"
    frozen = snapshot()
    bound = binding(frozen, TeamRole.REVIEWER)
    service = KnowledgeConsultationService(
        _client(tmp_path, executable, bound.role), KnowledgeRecordStore(root)
    )
    consultation = service.consult(bound, frozen, {}, timeout_seconds=1)
    assert consultation.binding == bound
    assert consultation.assessment.status == "SUFFICIENT"
    intent, outcome = _known_records(root, bound)
    assert outcome.state == "RETURNED" and outcome.failure is None
    assert outcome.result is not None and outcome.result.payload == {"queries": []}
    stopped = outcome.executions[-1].observation
    assert isinstance(stopped, StructuredNativeStopReceipt)
    assert stopped.process_stop.kind == "completed"
    assert "verdict" not in outcome.to_wire()
    assert (
        KnowledgeConsultationService(
            _client(tmp_path, executable, bound.role), KnowledgeRecordStore(root)
        ).consult(bound, frozen, {}, timeout_seconds=1)
        == consultation
    )
    assert _known_records(root, bound) == (intent, outcome)
    assert (tmp_path / "started").read_text().splitlines() == ["started"]


@pytest.mark.parametrize("stage", ["admission", "stop"])
def test_execution_receipt_write_failure_cannot_spawn_a_backup_or_publish_an_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    executable = _executable(tmp_path, "success")
    backup = tmp_path / "backup-codex"
    backup.write_text(
        f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n"
        "Path('backup-started').touch()\n"
        "Path(sys.argv[sys.argv.index('--output-last-message') + 1])"
        ".write_text('{\"queries\": []}')\n"
    )
    backup.chmod(0o700)
    root = tmp_path / "knowledge"
    frozen = snapshot()
    bound = binding(frozen)
    original_put = KnowledgeRecordStore.put

    def reject_receipt[T: DomainModel](
        records: KnowledgeRecordStore, namespace: str, key: str, record: T
    ) -> T:
        if (
            namespace == "knowledge-execution-records"
            and isinstance(record, KnowledgeExecutionRecord)
            and isinstance(record.observation, StructuredExecutionAdmission)
            == (stage == "admission")
        ):
            raise OSError("fixture receipt publication failed")
        return original_put(records, namespace, key, record)

    monkeypatch.setattr(KnowledgeRecordStore, "put", reject_receipt)
    with pytest.raises(KnowledgeInvocationUncertain):
        KnowledgeConsultationService(
            _client(tmp_path, executable, bound.role, backup=backup), KnowledgeRecordStore(root)
        ).consult(bound, frozen, {}, timeout_seconds=1)
    monkeypatch.setattr(KnowledgeRecordStore, "put", original_put)
    records = _lane(root, bound)
    assert len(records.list("knowledge-invocation-intents", KnowledgeInvocationIntent)) == 1
    observations = records.list("knowledge-execution-records", KnowledgeExecutionRecord)
    assert len(observations) == (0 if stage == "admission" else 1)
    assert all(isinstance(item.observation, StructuredExecutionAdmission) for item in observations)
    assert records.list("knowledge-invocation-outcomes", KnowledgeInvocationOutcome) == ()
    assert (tmp_path / "started").exists() == (stage == "stop")
    assert not (tmp_path / "backup-started").exists()
    changed = bound.model_copy(update={"run_id": "run_after_receipt_failure"})
    with pytest.raises(KnowledgeInvocationUncertain):
        KnowledgeConsultationService(
            _client(tmp_path, executable, bound.role, backup=backup), KnowledgeRecordStore(root)
        ).consult(changed, frozen, {}, timeout_seconds=1)
    assert not (tmp_path / "backup-started").exists()


def _actual_claim(bound: KnowledgeRunBinding, *, repository_id: str | None = None) -> QueueClaim:
    template = native_claim(make_task().model_copy(update={"id": bound.task_id}), 1)
    repository_id = repository_id or bound.repository_ids[0]
    return QueueClaim(
        work_item=template.work_item.model_copy(update={"repository_id": repository_id}),
        assignment=template.assignment.model_copy(update={"repository_id": repository_id}),
        lease=template.lease,
        model_selection=template.model_selection,
        worker_id=template.worker_id,
        claimed_at=template.claimed_at,
    )


def test_actual_queue_claim_is_preserved_in_the_native_knowledge_intent(tmp_path: Path) -> None:
    executable = _executable(tmp_path, "success")
    root = tmp_path / "knowledge"
    frozen = snapshot()
    bound = binding(frozen)
    claim = _actual_claim(bound)
    records = KnowledgeRecordStore(root)
    consultation = KnowledgeConsultationService(
        _client(tmp_path, executable, bound.role),
        records,
        invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: claim),
    ).consult(bound, frozen, {}, timeout_seconds=1)
    assert consultation.binding == bound
    intent, outcome = _known_records(root, bound)
    assert intent.claim == claim and outcome.intent.claim == claim
    assert intent.claim.assignment == claim.assignment
    assert intent.claim.lease == claim.lease
    assert intent.claim.model_selection == claim.model_selection
    assert intent.claim.worker_id == claim.worker_id
    assert (tmp_path / "started").read_text().splitlines() == ["started"]


@pytest.mark.parametrize("mismatch", ["task", "role", "repository"])
def test_mismatched_actual_claim_cannot_record_an_intent_or_start_a_model(
    tmp_path: Path, mismatch: str
) -> None:
    executable = _executable(tmp_path, "success")
    root = tmp_path / "knowledge"
    frozen = snapshot()
    original = binding(frozen)
    claim = _actual_claim(
        original,
        repository_id="repository_another_knowledge" if mismatch == "repository" else None,
    )
    changes: dict[str, dict[str, object]] = {
        "task": {"task_id": "task_another_knowledge"},
        "role": {"role": TeamRole.QA},
        "repository": {},
    }
    bound = original.model_copy(update=changes[mismatch])
    records = KnowledgeRecordStore(root)
    with pytest.raises(KnowledgeInvocationUncertain):
        KnowledgeConsultationService(
            _client(tmp_path, executable, bound.role),
            records,
            invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: claim),
        ).consult(bound, frozen, {}, timeout_seconds=1)
    lane = _lane(root, bound)
    assert lane.list("knowledge-invocation-intents", KnowledgeInvocationIntent) == ()
    assert lane.list("knowledge-execution-records", KnowledgeExecutionRecord) == ()
    assert lane.list("knowledge-invocation-outcomes", KnowledgeInvocationOutcome) == ()
    assert not (tmp_path / "started").exists()


class _HttpTransport:
    def __init__(self, response: HttpResponse, *, before_return: Callable[[], None]) -> None:
        self.response, self.before_return = response, before_return
        self.calls = 0

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HttpResponse:
        self.calls += 1
        self.before_return()
        return self.response


def _http_client(transport: _HttpTransport, model: str) -> ResponsesStructuredModelClient:
    return ResponsesStructuredModelClient(
        endpoint="https://example.invalid/v1",
        api_key="fixture",
        model=model,
        transport=transport,
    )


class _OwnerGuard:
    inherited_fds: tuple[int, ...] = ()

    def __init__(self) -> None:
        self.alive = True

    def check(self) -> None:
        if not self.alive:
            raise RuntimeError("fixture owner lost")

    @contextmanager
    def write_scope(self) -> Iterator[None]:
        self.check()
        yield
        self.check()


def test_owner_lost_during_first_http_route_keeps_completion_but_cannot_start_backup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "knowledge"
    frozen = snapshot()
    bound = binding(frozen)
    guard = _OwnerGuard()

    def lose_owner() -> None:
        lane = _lane(root, bound)
        (intent,) = lane.list("knowledge-invocation-intents", KnowledgeInvocationIntent)
        (record,) = lane.list("knowledge-execution-records", KnowledgeExecutionRecord)
        assert record.intent_sha256 == intent.intent_sha256
        assert isinstance(record.observation, StructuredExecutionAdmission)
        assert record.observation.call.route_index == 1
        guard.alive = False

    first = _HttpTransport(HttpResponse(504, b"fixture gateway timeout"), before_return=lose_owner)
    backup = _HttpTransport(
        HttpResponse(200, b'{"output_text":"{\\"queries\\":[]}"}'),
        before_return=lambda: None,
    )
    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute(
                provider="fixture",
                model="fixture-first",
                client=_http_client(first, "fixture-first"),
            ),
            StructuredModelRoute(
                provider="fixture",
                model="fixture-backup",
                client=_http_client(backup, "fixture-backup"),
            ),
        ),
        role=bound.role,
    )
    service = KnowledgeConsultationService(client, KnowledgeRecordStore(root))
    with pytest.raises(KnowledgeInvocationUncertain), bind_execution_guard(guard):
        service.consult(bound, frozen, {}, timeout_seconds=1)
    assert first.calls == 1 and backup.calls == 0
    lane = _lane(root, bound)
    observations = lane.list("knowledge-execution-records", KnowledgeExecutionRecord)
    assert len(observations) == 2
    admission = next(
        record.observation
        for record in observations
        if isinstance(record.observation, StructuredExecutionAdmission)
    )
    completion = next(
        record.observation
        for record in observations
        if isinstance(record.observation, StructuredHttpRoundTripReceipt)
    )
    assert completion.admission == admission and admission.call.route_index == 1
    assert completion.http_status == 504 and completion.outcome == "returned"
    assert completion.response_body_sha256 == hashlib.sha256(first.response.body).hexdigest()
    for record in observations:
        record.validate_integrity()
    assert lane.list("knowledge-invocation-outcomes", KnowledgeInvocationOutcome) == ()
    for candidate in (bound, bound.model_copy(update={"run_id": "run_after_owner_loss"})):
        with pytest.raises(KnowledgeInvocationUncertain):
            KnowledgeConsultationService(client, KnowledgeRecordStore(root)).consult(
                candidate, frozen, {}, timeout_seconds=1
            )
    assert first.calls == 1 and backup.calls == 0
    assert lane.list("knowledge-execution-records", KnowledgeExecutionRecord) == observations


@pytest.mark.parametrize("backup_outcome", ["success", "invalid"])
def test_missing_native_executable_is_recorded_before_backup_and_complete_outcome(
    tmp_path: Path, backup_outcome: str
) -> None:
    root = tmp_path / "knowledge"
    frozen = snapshot()
    bound = binding(frozen)
    response = HttpResponse(
        200,
        b'{"output_text":"{\\"queries\\":[]}"}' if backup_outcome == "success" else b"not-json",
    )

    def require_first_not_started_before_backup() -> None:
        lane = _lane(root, bound)
        (intent,) = lane.list("knowledge-invocation-intents", KnowledgeInvocationIntent)
        observations = lane.list("knowledge-execution-records", KnowledgeExecutionRecord)
        assert len(observations) == 3
        admissions = {
            record.observation.call.route_index: record.observation
            for record in observations
            if isinstance(record.observation, StructuredExecutionAdmission)
        }
        assert set(admissions) == {1, 2}
        (not_started,) = (
            record.observation
            for record in observations
            if isinstance(record.observation, StructuredNativeNotStartedReceipt)
        )
        assert not_started.admission == admissions[1]
        assert not_started.failure_kind == "process_spawn_failed"
        for record in observations:
            record.validate_integrity()
            assert record.intent_sha256 == intent.intent_sha256
        assert lane.list("knowledge-invocation-outcomes", KnowledgeInvocationOutcome) == ()

    backup = _HttpTransport(response, before_return=require_first_not_started_before_backup)
    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute(
                provider="fixture",
                model="fixture-model",
                client=CodexCliStructuredModelClient(
                    repository_root=tmp_path,
                    model="fixture-model",
                    executable=str(tmp_path / "missing-codex"),
                    environment={},
                ),
            ),
            StructuredModelRoute(
                provider="fixture",
                model="fixture-backup",
                client=_http_client(backup, "fixture-backup"),
            ),
        ),
        role=bound.role,
    )

    def consult() -> None:
        KnowledgeConsultationService(client, KnowledgeRecordStore(root)).consult(
            bound, frozen, {}, timeout_seconds=1
        )

    if backup_outcome == "success":
        consult()
    else:
        with pytest.raises(StructuredModelError) as failed:
            consult()
        assert failed.value.code is AgentErrorCode.INVALID_OUTPUT
    lane = _lane(root, bound)
    intent = lane.get(
        "knowledge-invocation-intents", bound.run_id + ":intent", KnowledgeInvocationIntent
    )
    outcome = lane.get(
        "knowledge-invocation-outcomes", bound.run_id + ":intent", KnowledgeInvocationOutcome
    )
    outcome.validate_integrity()
    assert outcome.intent == intent
    assert outcome.state == ("RETURNED" if backup_outcome == "success" else "FAILED")
    assert len(outcome.executions) == 4
    first_admission, not_started, backup_admission, completed = (
        record.observation for record in outcome.executions
    )
    assert isinstance(first_admission, StructuredExecutionAdmission)
    assert isinstance(not_started, StructuredNativeNotStartedReceipt)
    assert isinstance(backup_admission, StructuredExecutionAdmission)
    assert isinstance(completed, StructuredHttpRoundTripReceipt)
    assert first_admission.execution_kind == "native" and first_admission.call.route_index == 1
    assert not_started.admission == first_admission
    assert not_started.failure_kind == "process_spawn_failed"
    assert backup_admission.execution_kind == "http" and backup_admission.call.route_index == 2
    assert completed.admission == backup_admission and completed.http_status == 200
    assert completed.response_body_sha256 == hashlib.sha256(response.body).hexdigest()
    for record in outcome.executions:
        record.validate_integrity()
        assert record.intent_sha256 == intent.intent_sha256
        assert (
            lane.get("knowledge-execution-records", record.record_sha256, KnowledgeExecutionRecord)
            == record
        )
    assert len(lane.list("knowledge-execution-records", KnowledgeExecutionRecord)) == 4
    assert backup.calls == 1 and not (tmp_path / "started").exists()
    if backup_outcome == "success":
        consult()
    else:
        with pytest.raises(StructuredModelError):
            consult()
    assert backup.calls == 1
