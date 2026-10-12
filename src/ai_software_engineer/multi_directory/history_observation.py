"""Complete native history reads with bounded, exact-byte validation receipts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, TypeAdapter

from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId, Sha256
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.multi_directory.store import (
    JointJournal,
    _no_symlinks,
    _validate_successor,
)
from ai_software_engineer.read_record_scope import current_recovery_record_reads
from ai_software_engineer.team_workspace import _read_regular

if TYPE_CHECKING:
    from ai_software_engineer.read_record_scope import RecoveryRecordReads


class JointRecordFacts(DomainModel):
    """Fixed historical fields needed by native-child retirement, never authority."""

    delivery_id: DeliveryId
    sequence: int = Field(ge=1)
    checkpoint_sha256: Sha256
    previous_checkpoint_sha256: Sha256 | None
    team_id: TeamId
    team_manifest_sha256: Sha256
    project_id: ProjectId
    project_manifest_sha256: Sha256
    child_delivery_ids: tuple[DeliveryId, ...]

    @classmethod
    def from_checkpoint(cls, checkpoint: JointCheckpoint) -> JointRecordFacts:
        return cls(
            delivery_id=checkpoint.delivery_id,
            sequence=checkpoint.sequence,
            checkpoint_sha256=checkpoint.checkpoint_sha256,
            previous_checkpoint_sha256=checkpoint.previous_checkpoint_sha256,
            team_id=checkpoint.team_id,
            team_manifest_sha256=checkpoint.team_manifest_sha256,
            project_id=checkpoint.project_id,
            project_manifest_sha256=checkpoint.project_manifest_sha256,
            child_delivery_ids=tuple(child.checkpoint.delivery_id for child in checkpoint.children),
        )


class _VerifiedJointEdge(DomainModel):
    codec_version: Literal["native-joint-prefix-v1"] = "native-joint-prefix-v1"
    predecessor_payload_sha256: Sha256 | None
    facts: JointRecordFacts


@dataclass(frozen=True)
class NativeRequirementPrefix:
    current: JointCheckpoint | None
    records: tuple[JointRecordFacts, ...]


class NativeHistoryJournal(JointJournal):
    """Only native observers opt in; public full-history reads are inherited unchanged."""

    def native_prefix(self, delivery_id: str) -> NativeRequirementPrefix:
        return observe_native_requirement_prefix(self.root, delivery_id)


def observe_native_requirement_prefix(root: Path, delivery_id: str) -> NativeRequirementPrefix:
    """Reread every original byte/path/edge; only exact historical decoding may reuse."""
    TypeAdapter(DeliveryId).validate_python(delivery_id)
    if not delivery_id.startswith("delivery_multi_"):
        raise ValueError("not a joint delivery ID")
    directory = root.absolute() / delivery_id
    _no_symlinks(directory)
    owner = current_recovery_record_reads()
    for path in directory.glob("*.json"):
        _no_symlinks(path)
        _read_regular(path, 8_000_000)
    # Original preflight and Journal each enumerate independently; a new tail
    # between them must enter the second complete byte/chain observation.
    paths = sorted(directory.glob("*.json"))
    records: list[JointRecordFacts] = []
    previous: JointCheckpoint | None = None
    previous_payload: bytes | None = None
    previous_sha: str | None = None
    current: JointCheckpoint | None = None
    try:
        for index, path in enumerate(paths):
            _no_symlinks(path)
            # Preserve the preflight's separate Journal complete read and SHA.
            payload = path.read_bytes()
            payload_sha = hashlib.sha256(payload).hexdigest()
            saved = _lookup(owner, path, delivery_id, payload_sha, previous_sha)
            head = index == len(paths) - 1
            current = _decode(payload, path, delivery_id) if saved is None or head else None
            if saved is None:
                if previous is None and previous_payload is not None:
                    previous = JointCheckpoint.model_validate_json(previous_payload)
                    previous.validate_integrity()
                assert current is not None
                _validate_successor(previous, current)
                facts = JointRecordFacts.from_checkpoint(current)
                edge = _VerifiedJointEdge(predecessor_payload_sha256=previous_sha, facts=facts)
                if owner is not None:
                    owner._remember_joint_edge(path, delivery_id, payload_sha, edge)
            else:
                facts = saved.facts.model_copy(deep=True)
            # This is structural identity of THIS freshly enumerated complete prefix,
            # independent of whether a formerly valid edge was retained.
            if facts.sequence != index + 1 or path.name != f"{facts.sequence:06d}.json":
                raise ValueError("joint journal identity mismatch")
            records.append(facts)
            previous, previous_payload, previous_sha = current, payload, payload_sha
        return NativeRequirementPrefix(
            current.model_copy(deep=True) if current is not None else None, tuple(records)
        )
    finally:
        # Clear this observer's working references; the scope separately clears
        # retained receipts. Validator error frames may retain their own inputs.
        previous = current = None
        previous_payload = None
        payload = b""
        records.clear()


def _decode(payload: bytes, path: Path, delivery_id: str) -> JointCheckpoint:
    checkpoint = None
    try:
        checkpoint = JointCheckpoint.model_validate_json(payload)
        checkpoint.validate_integrity()
        if checkpoint.delivery_id != delivery_id or path.name != f"{checkpoint.sequence:06d}.json":
            raise ValueError("joint journal identity mismatch")
        return checkpoint
    finally:
        checkpoint = None
        payload = b""


def _lookup(
    owner: RecoveryRecordReads | None,
    path: Path,
    delivery_id: str,
    payload_sha256: str,
    predecessor_payload_sha256: str | None,
) -> _VerifiedJointEdge | None:
    if owner is None:
        return None
    return owner._joint_edge(path, delivery_id, payload_sha256, predecessor_payload_sha256)
