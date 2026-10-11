"""Immutable knowledge-call facts; these records never authorize execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from ai_software_engineer.agents.continuation import ContinuationExecutionUncertain
from ai_software_engineer.agents.execution import current_execution_guard, execution_scope
from ai_software_engineer.agents.models import AgentErrorCode, AgentUsage
from ai_software_engineer.agents.structured import (
    StructuredModelClient,
    StructuredModelError,
    StructuredModelResult,
)
from ai_software_engineer.agents.structured_observation import (
    StructuredExecutionAdmission,
    StructuredHttpRoundTripReceipt,
    StructuredNativeNotStartedReceipt,
    StructuredNativeStopReceipt,
    StructuredObservationRecord,
    StructuredObservationRejected,
    bind_structured_execution_observer,
    structured_request_digest,
)
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, WirePayload
from ai_software_engineer.knowledge.models import (
    Digest,
    KnowledgeError,
    KnowledgeRunBinding,
    digest,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.work_queue.models import QueueClaim

KnowledgePhase = Literal["intent", "assessment"]
_MAX_LANE_INTENTS = 512
_INTENTS = "knowledge-invocation-intents"
_OUTCOMES = "knowledge-invocation-outcomes"
_OBSERVATIONS = "knowledge-execution-records"


class KnowledgeInvocationUncertain(ContinuationExecutionUncertain):
    """Preserve the original preparation when its complete result is unavailable."""


class KnowledgePreparationLocalLimit(StructuredModelError):
    """A complete recorded failure; this identity grants no execution authority."""

    def __init__(
        self, outcome: KnowledgeInvocationOutcome, *, safe_message: str | None = None
    ) -> None:
        outcome.validate_integrity()
        failure = outcome.failure
        if (
            outcome.state != "FAILED"
            or failure is None
            or failure.code is not AgentErrorCode.TIMEOUT
            or failure.timeout_kind != "local_execution_limit"
        ):
            raise ValueError("knowledge local limit requires its complete typed failure")
        self.outcome = outcome
        super().__init__(
            failure.code,
            safe_message or failure.safe_message,
            transient=False,
            timeout_kind="local_execution_limit",
            http_status=failure.http_status,
            request_id=failure.request_id,
            correlation_id=failure.correlation_id,
        )

    def with_context(self, context: str) -> KnowledgePreparationLocalLimit:
        return KnowledgePreparationLocalLimit(
            self.outcome, safe_message=f"{context}: {self.safe_message}"
        )


def invocation_lane_sha256(binding: KnowledgeRunBinding) -> str:
    """A new Run, Context, revision or lease must not hide an unfinished call."""
    return invocation_scope_lane_sha256(
        team_id=binding.team_id,
        project_id=binding.project_id,
        requirement_id=binding.requirement_id,
        repository_ids=binding.repository_ids,
        task_id=binding.task_id,
        role=binding.role,
    )


def invocation_scope_lane_sha256(
    *,
    team_id: str,
    project_id: str,
    requirement_id: str,
    repository_ids: tuple[str, ...],
    task_id: str | None,
    role: TeamRole,
) -> str:
    """Locate a task's facts without inventing a Run or mutable claim."""
    return digest(
        (
            team_id,
            project_id,
            requirement_id,
            repository_ids,
            task_id,
            role.value,
        )
    )


class KnowledgeInvocationIntent(DomainModel):
    kind: Literal["knowledge_invocation_intent"] = "knowledge_invocation_intent"
    schema_version: Literal["v0.1"] = "v0.1"
    binding: KnowledgeRunBinding
    phase: KnowledgePhase
    request_sha256: Digest
    timeout_seconds: Annotated[int, Field(gt=0, le=86_400)]
    claim: QueueClaim | None = None
    created_at: AwareDatetime
    intent_sha256: Digest

    @model_validator(mode="after")
    def validate_claim(self) -> Self:
        if self.claim is not None and (
            self.binding.task_id != self.claim.work_item.task_id
            or self.binding.role.value != self.claim.work_item.role.value
            or self.binding.repository_ids != (self.claim.work_item.repository_id,)
        ):
            raise ValueError("knowledge invocation must retain its actual claimed task and role")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "intent_sha256": "0" * 64})
        return value.model_copy(update={"intent_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"intent_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.intent_sha256 != self.recompute_sha256():
            raise KnowledgeError("INVOCATION_INTENT_INTEGRITY")


class KnowledgeInvocationResult(DomainModel):
    payload: WirePayload
    duration_ms: Annotated[int, Field(ge=0)]
    usage: AgentUsage | None = None
    provider: NonEmptyStr | None = None
    model: NonEmptyStr | None = None
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    request_id: NonEmptyStr | None = None
    correlation_id: NonEmptyStr | None = None

    @classmethod
    def from_result(cls, result: StructuredModelResult) -> Self:
        value = cls(
            payload=TypeAdapter(WirePayload).validate_python(dict(result.payload)),
            duration_ms=result.duration_ms,
            usage=result.usage,
            provider=result.provider,
            model=result.model,
            http_status=result.http_status,
            request_id=result.request_id,
            correlation_id=result.correlation_id,
        )
        rendered = value.model_dump_json()
        if redact_text(rendered).text != rendered:
            raise KnowledgeError("INVOCATION_RESULT_REQUIRES_REDACTION")
        return value

    def as_result(self) -> StructuredModelResult:
        return StructuredModelResult(
            payload=self.payload,
            duration_ms=self.duration_ms,
            usage=self.usage,
            provider=self.provider,
            model=self.model,
            http_status=self.http_status,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
        )


class KnowledgeInvocationFailure(DomainModel):
    code: AgentErrorCode
    safe_message: Annotated[str, Field(min_length=1, max_length=500)]
    transient: bool
    timeout_kind: Literal["local_execution_limit"] | None = None
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    request_id: NonEmptyStr | None = None
    correlation_id: NonEmptyStr | None = None

    @classmethod
    def from_error(cls, error: StructuredModelError) -> Self:
        value = cls(
            code=error.code,
            safe_message=error.safe_message,
            transient=error.transient,
            timeout_kind=error.timeout_kind,
            http_status=error.http_status,
            request_id=error.request_id,
            correlation_id=error.correlation_id,
        )
        if redact_text(value.model_dump_json()).text != value.model_dump_json():
            raise KnowledgeError("INVOCATION_FAILURE_REQUIRES_REDACTION")
        return value

    def as_error(self) -> StructuredModelError:
        return StructuredModelError(
            self.code,
            self.safe_message,
            transient=self.transient,
            timeout_kind=self.timeout_kind,
            http_status=self.http_status,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
        )


class KnowledgeExecutionRecord(DomainModel):
    kind: Literal["knowledge_execution_record"] = "knowledge_execution_record"
    schema_version: Literal["v0.1"] = "v0.1"
    intent_sha256: Digest
    observation: StructuredObservationRecord
    record_sha256: Digest

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "record_sha256": "0" * 64})
        return value.model_copy(update={"record_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"record_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        self.observation.validate_integrity()
        if self.record_sha256 != self.recompute_sha256():
            raise KnowledgeError("INVOCATION_OBSERVATION_INTEGRITY")


class KnowledgeInvocationOutcome(DomainModel):
    """A returned model value is data, never a knowledge or delivery verdict."""

    kind: Literal["knowledge_invocation_outcome"] = "knowledge_invocation_outcome"
    schema_version: Literal["v0.1"] = "v0.1"
    intent: KnowledgeInvocationIntent
    state: Literal["RETURNED", "FAILED"]
    result: KnowledgeInvocationResult | None = None
    failure: KnowledgeInvocationFailure | None = None
    executions: Annotated[tuple[KnowledgeExecutionRecord, ...], Field(max_length=32)] = ()
    completed_at: AwareDatetime
    outcome_sha256: Digest

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        self.intent.validate_integrity()
        if self.completed_at < self.intent.created_at or (
            (self.state == "RETURNED") != (self.result is not None)
            or (self.state == "FAILED") != (self.failure is not None)
        ):
            raise ValueError("knowledge outcome must retain its exact returned value or failure")
        admissions: dict[str, StructuredExecutionAdmission] = {}
        completed: set[str] = set()
        for record in self.executions:
            record.validate_integrity()
            if record.intent_sha256 != self.intent.intent_sha256:
                raise ValueError("knowledge execution belongs to another preparation")
            observation = record.observation
            if isinstance(observation, StructuredExecutionAdmission):
                _require_admission(self.intent, observation)
                if observation.observation_id in admissions:
                    raise ValueError("duplicate knowledge execution admission")
                admissions[observation.observation_id] = observation
            else:
                admission = observation.admission
                if admissions.get(admission.observation_id) != admission or (
                    admission.observation_id in completed
                ):
                    raise ValueError("knowledge completion has no exact preceding admission")
                completed.add(admission.observation_id)
        if set(admissions) != completed:
            raise ValueError("knowledge outcome cannot hide an unfinished route")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "outcome_sha256": "0" * 64})
        return value.model_copy(update={"outcome_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"outcome_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.outcome_sha256 != self.recompute_sha256():
            raise KnowledgeError("INVOCATION_OUTCOME_INTEGRITY")


def _require_admission(
    intent: KnowledgeInvocationIntent, admission: StructuredExecutionAdmission
) -> None:
    admission.validate_integrity()
    if (
        admission.call.request_sha256 != intent.request_sha256
        or admission.call.role is not intent.binding.role
        or admission.call.phase != "knowledge_" + intent.phase
        or admission.timeout_seconds != intent.timeout_seconds
        or admission.admitted_at < intent.created_at
    ):
        raise KnowledgeError("INVOCATION_ADMISSION_CHANGED")


class _KnowledgeExecutionObserver:
    def __init__(self, records: KnowledgeRecordStore, intent: KnowledgeInvocationIntent) -> None:
        self.records, self.intent = records, intent
        self.executions: list[KnowledgeExecutionRecord] = []
        self._admissions: dict[str, StructuredExecutionAdmission] = {}
        self._completed: set[str] = set()

    def _publish(self, observation: StructuredObservationRecord) -> None:
        record = KnowledgeExecutionRecord.create(
            intent_sha256=self.intent.intent_sha256, observation=observation
        )
        self.records.put(_OBSERVATIONS, record.record_sha256, record)
        self.executions.append(record)

    def admit(self, admission: StructuredExecutionAdmission) -> None:
        _require_admission(self.intent, admission)
        if admission.observation_id in self._admissions or len(self._admissions) >= 16:
            raise KnowledgeError("INVOCATION_ADMISSION_CONFLICT")
        if set(self._admissions) != self._completed:
            raise KnowledgeInvocationUncertain("原知识调用尚未完整收尾, 禁止启动替代路由。")
        with execution_scope(current_execution_guard()):
            self._publish(admission)
        self._admissions[admission.observation_id] = admission

    def _complete(
        self,
        receipt: (
            StructuredNativeStopReceipt
            | StructuredNativeNotStartedReceipt
            | StructuredHttpRoundTripReceipt
        ),
    ) -> None:
        receipt.validate_integrity()
        admission = receipt.admission
        if self._admissions.get(admission.observation_id) != admission or (
            admission.observation_id in self._completed
        ):
            raise KnowledgeError("INVOCATION_COMPLETION_CONFLICT")
        # Actual stop facts remain publishable if the owner was lost after the
        # runner stopped. This does not mutate Task, budget, claim or verdict.
        self._publish(receipt)
        self._completed.add(admission.observation_id)

    def native_stopped(self, receipt: StructuredNativeStopReceipt) -> None:
        self._complete(receipt)

    def native_not_started(self, receipt: StructuredNativeNotStartedReceipt) -> None:
        self._complete(receipt)

    def http_completed(self, receipt: StructuredHttpRoundTripReceipt) -> None:
        self._complete(receipt)

    def require_complete(self) -> None:
        if set(self._admissions) != self._completed:
            raise KnowledgeInvocationUncertain("原知识调用的实际收尾记录不完整, 平台已保留原执行。")


class KnowledgeInvocationJournal:
    """Record every phase, and refuse to repeat an unknown invocation after restart."""

    def __init__(
        self, records: KnowledgeRecordStore, *, claimed: Callable[[], QueueClaim] | None = None
    ) -> None:
        self.records = records
        self.claimed = claimed

    def call(
        self,
        binding: KnowledgeRunBinding,
        phase: KnowledgePhase,
        *,
        client: StructuredModelClient,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
    ) -> StructuredModelResult:
        try:
            return self._call(
                binding,
                phase,
                client=client,
                instructions=instructions,
                input_payload=input_payload,
                output_schema=output_schema,
                timeout_seconds=timeout_seconds,
            )
        except (KnowledgeError, OSError, ValueError) as error:
            raise KnowledgeInvocationUncertain(
                "知识准备记录无法完整保存或校验, 原执行和现场已保留。"
            ) from error

    def _call(
        self,
        binding: KnowledgeRunBinding,
        phase: KnowledgePhase,
        *,
        client: StructuredModelClient,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
    ) -> StructuredModelResult:
        records = KnowledgeRecordStore(
            self.records.root / "invocations" / invocation_lane_sha256(binding)
        )
        key = binding.run_id + ":" + phase
        request_sha = structured_request_digest(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
        )
        prior = records.find(_INTENTS, key, KnowledgeInvocationIntent)
        if prior is not None:
            prior.validate_integrity()
            if (prior.binding, prior.phase, prior.request_sha256, prior.timeout_seconds) != (
                binding,
                phase,
                request_sha,
                timeout_seconds,
            ):
                raise KnowledgeInvocationUncertain("知识准备的原始输入已变化, 不能重复使用旧执行。")
            return self._replay(records, key, prior)
        intents = records.list(_INTENTS, KnowledgeInvocationIntent, limit=_MAX_LANE_INTENTS)
        if len(intents) >= _MAX_LANE_INTENTS:
            raise KnowledgeInvocationUncertain("本任务的知识执行记录已达到有限上限, 请平台核验。")
        for intent in intents:
            intent.validate_integrity()
            if invocation_lane_sha256(intent.binding) != invocation_lane_sha256(binding):
                raise KnowledgeInvocationUncertain("知识调用记录的任务归属无法核实。")
            outcome = records.find(
                _OUTCOMES, intent.binding.run_id + ":" + intent.phase, KnowledgeInvocationOutcome
            )
            if outcome is None:
                raise KnowledgeInvocationUncertain("原知识准备结果尚未完整保存, 禁止用新执行覆盖。")
            self._require_outcome(records, intent, outcome)
        intent = KnowledgeInvocationIntent.create(
            binding=binding,
            phase=phase,
            request_sha256=request_sha,
            timeout_seconds=timeout_seconds,
            created_at=datetime.now(UTC),
            claim=self.claimed() if self.claimed is not None else None,
        )
        guard = current_execution_guard()
        with execution_scope(guard):
            records.put(_INTENTS, key, intent)
        observer = _KnowledgeExecutionObserver(records, intent)
        try:
            with bind_structured_execution_observer(observer):
                result = client.complete(
                    instructions=instructions,
                    input_payload=input_payload,
                    output_schema=output_schema,
                    timeout_seconds=timeout_seconds,
                )
        except StructuredModelError as error:
            observer.require_complete()
            failed = self._finish(
                records, key, intent, observer, failure=KnowledgeInvocationFailure.from_error(error)
            )
            if error.expandable_timeout:
                self._publish_local_limit(failed)
                raise KnowledgePreparationLocalLimit(failed) from error
            raise
        except StructuredObservationRejected as error:
            raise KnowledgeInvocationUncertain(
                "知识执行记录保存失败, 平台已暂停后续执行。"
            ) from error
        except Exception as error:
            raise KnowledgeInvocationUncertain(
                "知识执行未形成完整结果, 原记录和现场已保留。"
            ) from error
        observer.require_complete()
        self._finish(
            records, key, intent, observer, result=KnowledgeInvocationResult.from_result(result)
        )
        return result

    @staticmethod
    def _finish(
        records: KnowledgeRecordStore,
        key: str,
        intent: KnowledgeInvocationIntent,
        observer: _KnowledgeExecutionObserver,
        *,
        result: KnowledgeInvocationResult | None = None,
        failure: KnowledgeInvocationFailure | None = None,
    ) -> KnowledgeInvocationOutcome:
        outcome = KnowledgeInvocationOutcome.create(
            intent=intent,
            state="RETURNED" if result is not None else "FAILED",
            result=result,
            failure=failure,
            executions=tuple(observer.executions),
            completed_at=datetime.now(UTC),
        )
        with execution_scope(current_execution_guard()):
            records.put(_OUTCOMES, key, outcome)
        return outcome

    @staticmethod
    def _require_outcome(
        records: KnowledgeRecordStore,
        intent: KnowledgeInvocationIntent,
        outcome: KnowledgeInvocationOutcome,
    ) -> None:
        outcome.validate_integrity()
        if outcome.intent != intent:
            raise KnowledgeInvocationUncertain("知识结果与原始调用不一致, 平台已暂停执行。")
        for record in outcome.executions:
            if records.get(_OBSERVATIONS, record.record_sha256, KnowledgeExecutionRecord) != record:
                raise KnowledgeInvocationUncertain("原知识调用的执行观察无法重新核实。")

    def _publish_local_limit(self, outcome: KnowledgeInvocationOutcome) -> None:
        """Index already sealed facts so exact engineering reads need no lane scan."""
        with execution_scope(current_execution_guard()):
            self.records.put(
                "knowledge-local-limit-intents", outcome.outcome_sha256, outcome.intent
            )

    def _replay(
        self, records: KnowledgeRecordStore, key: str, intent: KnowledgeInvocationIntent
    ) -> StructuredModelResult:
        outcome = records.find(_OUTCOMES, key, KnowledgeInvocationOutcome)
        if outcome is None:
            raise KnowledgeInvocationUncertain("原知识调用已记录, 结果尚未完整保存; 禁止重复调用。")
        self._require_outcome(records, intent, outcome)
        if outcome.failure is not None:
            if outcome.failure.timeout_kind == "local_execution_limit":
                self._publish_local_limit(outcome)
                raise KnowledgePreparationLocalLimit(outcome)
            raise outcome.failure.as_error()
        assert outcome.result is not None
        return outcome.result.as_result()
