"""Durable, bounded Manager proposals with explicit owned invocation claims.

The model receives no store or executor. The application owns admission, validation,
failure accounting and immutable publication; no proposal is an approval or verdict.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self
from uuid import uuid4

from pydantic import AwareDatetime, Field, StrictInt, ValidationError, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.execution import ExecutionGuard, bind_execution_guard
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured import StructuredModelClient, StructuredModelError
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, WirePayload
from ai_software_engineer.domain.retry_policy import ExecutionTimePolicy, ManagerRetryPolicy
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.model_store import ManagerRecordStore, manager_record_transaction
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.store.mysql_repository import open_mysql_connection


class ManagerExecutionRejected(RuntimeError):
    """A safe coordination stop, never a new business failure or verdict."""


class ManagerRunScope(DomainModel):
    team_id: TeamId
    project_id: ProjectId
    requirement_id: NonEmptyStr
    stage: NonEmptyStr

    @property
    def episode_id(self) -> str:
        return digest(self.to_wire())


class ManagerRunRecord(DomainModel):
    kind: Literal["manager_model_run"] = "manager_model_run"
    scope: ManagerRunScope
    sequence: Annotated[StrictInt, Field(ge=1)]
    run_id: NonEmptyStr
    agent_id: Literal["agent_team_manager"] = "agent_team_manager"
    input_sha256: Sha256
    context_manifest_id: NonEmptyStr
    state: Literal["STARTED", "SUCCEEDED", "TRANSIENT", "CAPACITY", "INVALID", "FAILED"]
    started_at: AwareDatetime
    expires_at: AwareDatetime
    owner_sha256: Sha256
    timeout_seconds: Annotated[StrictInt, Field(ge=1, le=86400)]
    retry_policy: ManagerRetryPolicy
    time_policy: ExecutionTimePolicy
    provider: str | None = None
    model: str | None = None
    result: WirePayload | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def receipt_shape(self) -> Self:
        if self.expires_at <= self.started_at:
            raise ValueError("Manager claim must have a positive lease window")
        if (self.state == "SUCCEEDED") != (self.result is not None):
            raise ValueError("only a successful Manager invocation has a result")
        if (self.state not in {"STARTED", "SUCCEEDED"}) != (self.error_code is not None):
            raise ValueError("Manager failure requires its typed error code")
        return self


class ManagerInvocationGuard(ExecutionGuard, Protocol):
    @property
    def owner_sha256(self) -> str: ...


class ManagerClaimAuthority(Protocol):
    def claim(
        self, scope: ManagerRunScope, *, seconds: int
    ) -> AbstractContextManager[ManagerInvocationGuard]: ...


class MySqlManagerClaimAuthority:
    """A single-host Manager lane fenced by a live, dedicated MySQL named lock.

    This is not a delivery-role WorkItem or a fabricated Task. A lost connection
    cannot publish output. Every invocation has a separate connection/claim and
    durable STARTED record; the Team lane conservatively serializes Manager runs.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def claim(self, scope: ManagerRunScope, *, seconds: int) -> Iterator[ManagerInvocationGuard]:
        name = "ase.manager." + hashlib.sha256(scope.team_id.encode()).hexdigest()[:48]
        with closing(open_mysql_connection(self._dsn)) as connection:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute(
                    "SELECT GET_LOCK(%s, 0) AS acquired, CONNECTION_ID() AS connection_id",
                    (name,),
                )
                row = cursor.fetchone()
                if row is None or row["acquired"] != 1:
                    raise ManagerExecutionRejected("Manager 正在处理其他协调任务, 请稍后继续。")
                connection_id = row["connection_id"]
                if not isinstance(connection_id, int):
                    raise ManagerExecutionRejected("Manager claim identity is invalid")
            deadline = time.monotonic() + seconds
            owner_identity = hashlib.sha256(
                f"{name}:{connection_id}:{uuid4().hex}".encode()
            ).hexdigest()

            class Guard:
                inherited_fds: tuple[int, ...] = ()
                owner_sha256 = owner_identity

                def check(self) -> None:
                    if time.monotonic() >= deadline:
                        raise ManagerExecutionRejected("Manager invocation lease expired")
                    # Never reconnect: a new connection is not the admitted owner.
                    with connection.cursor(DictCursor) as cursor:
                        cursor.execute(
                            "SELECT IS_USED_LOCK(%s) = CONNECTION_ID() AS owned", (name,)
                        )
                        owned = cursor.fetchone()
                        if owned is None or owned["owned"] != 1:
                            raise ManagerExecutionRejected("Manager invocation ownership lost")

                @contextmanager
                def write_scope(self) -> Iterator[None]:
                    with manager_record_transaction(connection, scope.team_id):
                        self.check()
                        yield
                        self.check()

            try:
                yield Guard()
            finally:
                # Closing the dedicated connection releases its lock, including on errors.
                pass


class ManagerModelExecutor:
    def __init__(
        self,
        *,
        root: Path,
        scope: ManagerRunScope,
        authority: ManagerClaimAuthority,
        retry_policy: ManagerRetryPolicy,
        time_policy: ExecutionTimePolicy,
        store: ManagerRecordStore | None = None,
    ) -> None:
        self.store: ManagerRecordStore = store or KnowledgeRecordStore(root)
        self.scope, self.authority = scope, authority
        self.retry_policy, self.time_policy = retry_policy, time_policy
        self.last_run_id: str | None = None

    def _history(self) -> tuple[ManagerRunRecord, ...]:
        starts = sorted(
            (
                r
                for r in self.store.list("manager-start", ManagerRunRecord)
                if r.scope == self.scope
            ),
            key=lambda r: r.sequence,
        )
        records: list[ManagerRunRecord] = []
        for index, start in enumerate(starts, 1):
            if start.sequence != index or start.state != "STARTED":
                raise ManagerExecutionRejected("Manager run history is inconsistent")
            final = self.store.find("manager-final", start.run_id, ManagerRunRecord)
            if final is not None:
                mutable = {"state", "result", "provider", "model", "error_code"}
                if final.state == "STARTED" or final.model_dump(
                    exclude=mutable
                ) != start.model_dump(exclude=mutable):
                    raise ManagerExecutionRejected("Manager run receipt differs from its claim")
            records.append(final or start)
        return tuple(records)

    def run[T: DomainModel](
        self,
        client: StructuredModelClient,
        *,
        instructions: str,
        payload: Mapping[str, object],
        model: type[T],
        validate: Callable[[T], None] | None = None,
    ) -> tuple[T, str, str]:
        # Inputs may contain repository/user text. Persist only the same redacted, bounded
        # projection sent to the model; invalid raw responses are never written or echoed.
        serialized = redact_text(json.dumps(dict(payload), ensure_ascii=False)).text
        if len(serialized.encode()) > 4_000_000:
            raise ManagerExecutionRejected("Manager context exceeds its bounded input size")
        payload = json.loads(serialized)
        identity = digest(
            {
                "payload": dict(payload),
                "instructions": instructions,
                "schema": model.model_json_schema(),
            }
        )
        # All limits are independent. This hard loop bound is additional to durable admission.
        for _ in range(
            self.retry_policy.max_attempts
            + self.retry_policy.max_transient_failures
            + self.time_policy.max_capacity_timeouts
        ):
            # A route chain may consume one window per fallback route. The lease spans the
            # configured route-count ceiling; this is ownership, not a model time allowance.
            with self.authority.claim(
                self.scope, seconds=self.time_policy.max_seconds * 16 + 60
            ) as guard:
                records = self._history()
                relevant = [r for r in records if r.input_sha256 == identity]
                for record in relevant:
                    if record.state == "SUCCEEDED":
                        value = model.model_validate(record.result)
                        if validate is not None:
                            validate(value)
                        guard.check()
                        self.last_run_id = record.run_id
                        return (
                            value,
                            record.provider or "unspecified",
                            record.model or "unspecified",
                        )
                if (
                    len({r.input_sha256 for r in records} | {identity})
                    > self.retry_policy.max_coordination_rounds
                ):
                    raise ManagerExecutionRejected(
                        "Manager 协调轮次已耗尽, 请检查记录或调整配置后重启。"
                    )
                work = sum(r.state not in {"TRANSIENT", "CAPACITY"} for r in relevant)
                transient = sum(r.state == "TRANSIENT" for r in records)
                capacity = sum(r.state == "CAPACITY" for r in records)
                if work >= self.retry_policy.max_attempts:
                    raise ManagerExecutionRejected("Manager 产物修正额度已耗尽。")
                if transient >= self.retry_policy.max_transient_failures:
                    raise ManagerExecutionRejected("Manager 临时故障额度已耗尽。")
                try:
                    window = self.time_policy.window(capacity)
                except ValueError as error:
                    raise ManagerExecutionRejected(
                        "Manager 本地执行时间扩容额度已耗尽。"
                    ) from error
                run_id = "manager_run_" + uuid4().hex
                started = datetime.now(UTC)
                invocation_payload = {
                    **payload,
                    **(
                        {
                            "contract_correction": (
                                "Invalid or interrupted proposal. Follow the exact schema "
                                "and advertised capabilities; no new authority."
                            )
                        }
                        if work
                        else {}
                    ),
                }
                context_sha = digest(
                    {
                        "payload": invocation_payload,
                        "instructions": instructions,
                        "schema": model.model_json_schema(),
                    }
                )
                start = ManagerRunRecord(
                    scope=self.scope,
                    sequence=len(records) + 1,
                    run_id=run_id,
                    input_sha256=identity,
                    context_manifest_id="ctx_manager_" + context_sha,
                    state="STARTED",
                    started_at=started,
                    expires_at=started + timedelta(seconds=self.time_policy.max_seconds * 16 + 60),
                    owner_sha256=guard.owner_sha256,
                    timeout_seconds=window,
                    retry_policy=self.retry_policy,
                    time_policy=self.time_policy,
                )
                with guard.write_scope():
                    self.store.put(
                        "manager-context",
                        context_sha,
                        ManagerContext(
                            input_sha256=context_sha,
                            payload=invocation_payload,
                            instructions=instructions,
                            output_schema=model.model_json_schema(),
                        ),
                    )
                    self.store.put("manager-start", run_id, start)
                try:
                    with bind_execution_guard(guard):
                        response = client.complete(
                            instructions=instructions,
                            input_payload=invocation_payload,
                            output_schema=model.model_json_schema(),
                            timeout_seconds=window,
                        )
                    try:
                        value = model.model_validate(response.payload)
                        value = model.model_validate_json(redact_text(value.model_dump_json()).text)
                        if validate is not None:
                            validate(value)
                    except (ValidationError, ValueError) as error:
                        raise StructuredModelError(
                            AgentErrorCode.INVALID_OUTPUT,
                            "Manager proposal violated its typed contract",
                            transient=False,
                        ) from error
                except StructuredModelError as error:
                    state = (
                        "CAPACITY"
                        if error.expandable_timeout
                        else "TRANSIENT"
                        if error.retryable
                        else "INVALID"
                        if error.code is AgentErrorCode.INVALID_OUTPUT
                        else "FAILED"
                    )
                    final = start.model_copy(
                        update={"state": state, "error_code": error.code.value}
                    )
                    with guard.write_scope():
                        self.store.put("manager-final", run_id, final)
                    if state == "FAILED":
                        raise
                    continue
                with guard.write_scope():
                    self.store.put(
                        "manager-final",
                        run_id,
                        start.model_copy(
                            update={
                                "state": "SUCCEEDED",
                                "result": value.to_wire(),
                                "provider": response.provider,
                                "model": response.model,
                            }
                        ),
                    )
                self.last_run_id = run_id
                return value, response.provider or "unspecified", response.model or "unspecified"
        raise ManagerExecutionRejected("Manager execution budget exhausted")


class ManagerContext(DomainModel):
    input_sha256: Sha256
    payload: dict[str, object]
    instructions: NonEmptyStr
    output_schema: dict[str, object]
