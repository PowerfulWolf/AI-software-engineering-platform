"""Synchronous bounded decoding reuse for selected immutable recovery read records."""

from __future__ import annotations

import hashlib
import json
from asyncio import current_task
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from threading import get_ident
from typing import TYPE_CHECKING, Literal, cast

from ai_software_engineer.domain.model import DomainModel

RecordKind = Literal["baseline-plan", "baseline-start", "context"]
type _RecordKey = tuple[str, str, type[DomainModel], str]

if TYPE_CHECKING:
    from ai_software_engineer.multi_directory.history_observation import _VerifiedJointEdge


@dataclass(frozen=True, slots=True)
class _VerifiedRecord:
    payload_sha256: str
    value: DomainModel
    serialized_bytes: int


class RecoveryRecordReads:
    """Private immutable decodes, never cached current Task/authority/READY conclusions."""

    def __init__(
        self, *, maximum_entries: int = 512, maximum_bytes: int = 32 * 1024 * 1024
    ) -> None:
        self.maximum_entries = maximum_entries
        self.maximum_bytes = maximum_bytes
        self._records: dict[_RecordKey, _VerifiedRecord] = {}
        self.retained_bytes = 0
        self.owner_thread = get_ident()
        self.owner_async_task = _async_task_identity()
        self.closed = False

    @property
    def retained_entries(self) -> int:
        return len(self._records)

    def close(self) -> None:
        self._records.clear()
        self.retained_bytes = 0
        self.closed = True

    def _joint_edge(
        self,
        path: Path,
        delivery_id: str,
        payload_sha256: str,
        predecessor_payload_sha256: str | None,
    ) -> _VerifiedJointEdge | None:
        from ai_software_engineer.multi_directory.history_observation import _VerifiedJointEdge

        if (
            self.closed
            or self.owner_thread != get_ident()
            or self.owner_async_task != _async_task_identity()
        ):
            return None
        key: _RecordKey = (str(path.absolute()), "joint-history", _VerifiedJointEdge, delivery_id)
        saved = self._records.get(key)
        if saved is None:
            return None
        if (
            saved.payload_sha256 != payload_sha256
            or not isinstance(saved.value, _VerifiedJointEdge)
            or saved.value.predecessor_payload_sha256 != predecessor_payload_sha256
        ):
            del self._records[key]
            self.retained_bytes -= saved.serialized_bytes
            return None
        return saved.value.model_copy(deep=True)

    def _remember_joint_edge(
        self, path: Path, delivery_id: str, payload_sha256: str, edge: _VerifiedJointEdge
    ) -> None:
        from ai_software_engineer.multi_directory.history_observation import _VerifiedJointEdge

        if type(edge) is not _VerifiedJointEdge or edge.facts.delivery_id != delivery_id:
            raise ValueError("joint validation receipt has another fixed identity")
        if (
            self.closed
            or self.owner_thread != get_ident()
            or self.owner_async_task != _async_task_identity()
            or len(self._records) >= self.maximum_entries
        ):
            return
        key: _RecordKey = (str(path.absolute()), "joint-history", _VerifiedJointEdge, delivery_id)
        # Compact metadata is retained; complete fresh payloads are never retained.
        size = (
            len(edge.model_dump_json().encode())
            + len(key[0].encode())
            + len(delivery_id.encode())
            + 128
        )
        if self.retained_bytes + size <= self.maximum_bytes:
            self._records[key] = _VerifiedRecord(payload_sha256, edge.model_copy(deep=True), size)
            self.retained_bytes += size

    def decode[T: DomainModel](
        self,
        *,
        path: Path,
        kind: RecordKind,
        model: type[T],
        record_key: str,
        payload: bytes,
    ) -> T:
        if not _allowed_record_model(kind, model):
            raise ValueError(
                "recovery decode reuse cannot accept authority or mutable current facts"
            )
        if (
            self.closed
            or self.owner_thread != get_ident()
            or self.owner_async_task != _async_task_identity()
        ):
            return _decode_record(kind, model, payload, record_key)
        # Caller already performed its ordinary fresh complete regular/path read.
        key: _RecordKey = (str(path.absolute()), kind, model, record_key)
        payload_sha = hashlib.sha256(payload).hexdigest()
        saved = self._records.get(key)
        if saved is not None and saved.payload_sha256 == payload_sha:
            value = cast(T, saved.value.model_copy(deep=True))
            _require_record_key(kind, value, record_key)
            return value
        if saved is not None:
            del self._records[key]
            self.retained_bytes -= saved.serialized_bytes
            saved = None
        value = _decode_record(kind, model, payload, record_key)
        if self.closed or len(self._records) >= self.maximum_entries:
            return value
        # Count full raw+typed serialized footprints, not total Python heap/RSS.
        size = len(payload) + len(value.model_dump_json().encode()) + len(key[0].encode()) + 64
        if self.retained_bytes + size <= self.maximum_bytes:
            self._records[key] = _VerifiedRecord(payload_sha, value.model_copy(deep=True), size)
            self.retained_bytes += size
        return value


_CURRENT: ContextVar[RecoveryRecordReads | None] = ContextVar("recovery_record_reads", default=None)


def _async_task_identity() -> int | None:
    try:
        task = current_task()
    except RuntimeError:
        return None
    return id(task) if task is not None else None


def current_recovery_record_reads() -> RecoveryRecordReads | None:
    current = _CURRENT.get()
    return (
        current
        if current is not None
        and not current.closed
        and current.owner_thread == get_ident()
        and current.owner_async_task == _async_task_identity()
        else None
    )


@contextmanager
def recovery_record_read_scope() -> Iterator[RecoveryRecordReads]:
    inherited = current_recovery_record_reads()
    if inherited is not None:
        yield inherited
        return
    owned = RecoveryRecordReads()
    token = _CURRENT.set(owned)
    try:
        yield owned
    finally:
        owned.close()
        _CURRENT.reset(token)


def finish_recovery_record_reads() -> None:
    current = current_recovery_record_reads()
    if current is not None:
        current.close()


def decode_verified_record[T: DomainModel](
    *,
    path: Path,
    kind: RecordKind,
    model: type[T],
    record_key: str,
    payload: bytes,
    allow_reuse: bool = True,
) -> T:
    if not _allowed_record_model(kind, model):
        raise ValueError("recovery decode reuse cannot accept authority or mutable current facts")
    current = current_recovery_record_reads() if allow_reuse else None
    if current is None:
        return _decode_record(kind, model, payload, record_key)
    return current.decode(path=path, kind=kind, model=model, record_key=record_key, payload=payload)


def _decode_record[T: DomainModel](
    kind: RecordKind, model: type[T], payload: bytes, record_key: str
) -> T:
    """Only fixed raw-byte decoders can register a verified immutable model."""
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore

    value = (
        model.model_validate(json.loads(payload.decode("utf-8")))
        if kind == "context"
        else KnowledgeRecordStore._decode_payload(payload, model)
    )
    _validate_record(kind, value, record_key)
    return value


def _require_record_key(kind: RecordKind, value: DomainModel, record_key: str) -> None:
    from ai_software_engineer.context.models import ContextBundle
    from ai_software_engineer.manager.baseline_models import (
        BaselineOperationStart,
        ExecutionBaselinePlan,
    )

    actual = (
        value.context_id
        if kind == "context" and isinstance(value, ContextBundle)
        else value.plan_sha256
        if kind == "baseline-plan" and isinstance(value, ExecutionBaselinePlan)
        else value.plan.plan_sha256
        if kind == "baseline-start" and isinstance(value, BaselineOperationStart)
        else None
    )
    if actual != record_key:
        raise ValueError("recovery immutable record key changed")


def _validate_record(kind: RecordKind, value: DomainModel, record_key: str) -> None:
    """Cache registration has one fixed integrity contract, never caller validators."""
    from ai_software_engineer.context.models import ContextBundle
    from ai_software_engineer.context.ports import ContextCorruption
    from ai_software_engineer.context.store import _validate_context_identity
    from ai_software_engineer.manager.baseline_models import (
        BaselineOperationStart,
        ExecutionBaselinePlan,
    )

    if not _allowed_record_model(kind, type(value)):
        raise ValueError("recovery immutable record has an unsupported type")
    _require_record_key(kind, value, record_key)
    if isinstance(value, ContextBundle):
        _validate_context_identity(value, ContextCorruption)
    elif isinstance(value, ExecutionBaselinePlan | BaselineOperationStart):
        value.validate_integrity()
    else:
        raise ValueError("recovery immutable record has an unsupported type")


def _allowed_record_model(kind: RecordKind, model: type[DomainModel]) -> bool:
    # Lazy imports avoid adapter/model construction cycles; exact trusted types only.
    from ai_software_engineer.context.models import ContextBundle
    from ai_software_engineer.manager.baseline_models import (
        BaselineOperationStart,
        ExecutionBaselinePlan,
    )

    return (
        model
        is {
            "context": ContextBundle,
            "baseline-plan": ExecutionBaselinePlan,
            "baseline-start": BaselineOperationStart,
        }[kind]
    )
