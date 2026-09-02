"""Append-only filesystem store for durable product-discovery facts."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from typing import Final, Protocol, TypeVar

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.domain.enums import ProductApprovalDecision
from ai_software_engineer.domain.model import DomainModel, WirePayload
from ai_software_engineer.domain.project_delivery import (
    ProductApprovalId,
    ProductSpec,
    ProductSpecApproval,
    ProductSpecId,
    ProjectRequestId,
    StageContractError,
)
from ai_software_engineer.product.models import (
    ProductDialogueRecord,
    ProductDiscoveryCheckpoint,
    ProductDiscoveryStatus,
    ProductOperationId,
    ProductOperationRecord,
    ProductRecordIntegrityError,
    ProductRecordStoreError,
    ProjectRequestRevision,
)

_REQUEST_ID_ADAPTER: Final[TypeAdapter[ProjectRequestId]] = TypeAdapter(ProjectRequestId)
_SPEC_ID_ADAPTER: Final[TypeAdapter[ProductSpecId]] = TypeAdapter(ProductSpecId)
_APPROVAL_ID_ADAPTER: Final[TypeAdapter[ProductApprovalId]] = TypeAdapter(ProductApprovalId)
_OPERATION_ID_ADAPTER: Final[TypeAdapter[ProductOperationId]] = TypeAdapter(ProductOperationId)
_RECORD_KEYS: Final = frozenset(("record", "sha256"))
_RecordT = TypeVar("_RecordT", bound=DomainModel)


class ProductRecordNotFound(ProductRecordStoreError):
    """Raised when an exact product record does not exist."""


class ProductRecordConflict(ProductRecordStoreError):
    """Raised when an immutable record identity is reused with changed content."""


class ProductRecordCorruption(ProductRecordStoreError):
    """Raised when persisted product facts cannot be trusted."""


class ProductRecordLineageError(ProductRecordStoreError):
    """Raised when an append references missing or mismatched durable facts."""


class ProductRecordPathError(ProductRecordStoreError):
    """Raised when a store path could leave the configured sidecar root."""


class ProductRecordStore(Protocol):
    """Typed persistence port used by Product application services."""

    def put_dialogue(self, record: ProductDialogueRecord) -> ProductDialogueRecord: ...

    def get_dialogue(
        self, request_id: ProjectRequestId | str, sequence: int
    ) -> ProductDialogueRecord: ...

    def list_dialogue(
        self, request_id: ProjectRequestId | str
    ) -> tuple[ProductDialogueRecord, ...]: ...

    def put_request_revision(self, record: ProjectRequestRevision) -> ProjectRequestRevision: ...

    def get_request_revision(
        self, request_id: ProjectRequestId | str, revision: int
    ) -> ProjectRequestRevision: ...

    def current_request_revision(
        self, request_id: ProjectRequestId | str
    ) -> ProjectRequestRevision: ...

    def put_product_spec(self, spec: ProductSpec) -> ProductSpec: ...

    def get_product_spec(self, request_id: ProjectRequestId | str, version: int) -> ProductSpec: ...

    def find_product_spec(self, spec_id: ProductSpecId | str) -> ProductSpec | None: ...

    def list_product_specs(self, request_id: ProjectRequestId | str) -> tuple[ProductSpec, ...]: ...

    def put_approval(self, approval: ProductSpecApproval) -> ProductSpecApproval: ...

    def get_approval(
        self, request_id: ProjectRequestId | str, product_spec_id: ProductSpecId | str
    ) -> ProductSpecApproval: ...

    def find_approval(self, approval_id: ProductApprovalId | str) -> ProductSpecApproval | None: ...

    def put_checkpoint(
        self, checkpoint: ProductDiscoveryCheckpoint
    ) -> ProductDiscoveryCheckpoint: ...

    def get_checkpoint(
        self, request_id: ProjectRequestId | str, revision: int
    ) -> ProductDiscoveryCheckpoint: ...

    def current_checkpoint(
        self, request_id: ProjectRequestId | str
    ) -> ProductDiscoveryCheckpoint: ...

    def put_operation(self, record: ProductOperationRecord) -> ProductOperationRecord: ...

    def get_operation(self, operation_id: ProductOperationId | str) -> ProductOperationRecord: ...

    def find_operation(
        self, operation_id: ProductOperationId | str
    ) -> ProductOperationRecord | None: ...


class FileProductRecordStore:
    """Persist product facts below an external sidecar using exclusive publication."""

    def __init__(self, root: str | Path) -> None:
        configured = Path(root).expanduser()
        if configured.is_symlink():
            raise ProductRecordPathError("Product record store root cannot be a symlink")
        self._root = configured.resolve(strict=False)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ProductRecordStoreError(
                f"cannot initialize Product record store at {self._root}"
            ) from error
        self._require_trusted_root()

    def put_dialogue(self, record: ProductDialogueRecord) -> ProductDialogueRecord:
        _validate_record(record)
        if record.sequence > 1:
            previous = self.get_dialogue(record.request_id, record.sequence - 1)
            if (
                previous.project_id != record.project_id
                or record.previous_dialogue_sha256 != previous.dialogue_sha256
                or record.recorded_at < previous.recorded_at
            ):
                raise ProductRecordLineageError("ProductDialogueRecord previous digest mismatch")
        target = self._request_record_path("dialogue", record.request_id, record.sequence)
        return self._put(target, record, ProductDialogueRecord)

    def get_dialogue(
        self, request_id: ProjectRequestId | str, sequence: int
    ) -> ProductDialogueRecord:
        target = self._request_record_path("dialogue", request_id, sequence, create=False)
        record = self._read(target, ProductDialogueRecord)
        if record.request_id != request_id or record.sequence != sequence:
            raise ProductRecordCorruption("ProductDialogueRecord filename identity mismatch")
        if sequence > 1:
            previous = self.get_dialogue(request_id, sequence - 1)
            if (
                record.project_id != previous.project_id
                or record.previous_dialogue_sha256 != previous.dialogue_sha256
                or record.recorded_at < previous.recorded_at
            ):
                raise ProductRecordCorruption("ProductDialogueRecord chain is broken")
        return record

    def list_dialogue(
        self, request_id: ProjectRequestId | str
    ) -> tuple[ProductDialogueRecord, ...]:
        request_dir = self._request_directory("dialogue", request_id, create=False)
        if not request_dir.exists():
            return ()
        records = self._list_numbered(request_dir, ProductDialogueRecord)
        previous: ProductDialogueRecord | None = None
        for expected, record in enumerate(records, start=1):
            if record.request_id != request_id or record.sequence != expected:
                raise ProductRecordCorruption("ProductDialogueRecord sequence is not contiguous")
            if previous is None:
                if record.previous_dialogue_sha256 is not None:
                    raise ProductRecordCorruption("first dialogue record has a previous digest")
            elif (
                record.project_id != previous.project_id
                or record.previous_dialogue_sha256 != previous.dialogue_sha256
            ):
                raise ProductRecordCorruption("ProductDialogueRecord chain is broken")
            previous = record
        return records

    def put_request_revision(self, record: ProjectRequestRevision) -> ProjectRequestRevision:
        _validate_record(record)
        if record.revision > 1:
            previous = self.get_request_revision(record.request.id, record.revision - 1)
            _validate_request_lineage(previous, record)
        target = self._request_record_path("requests", record.request.id, record.revision)
        return self._put(target, record, ProjectRequestRevision)

    def get_request_revision(
        self, request_id: ProjectRequestId | str, revision: int
    ) -> ProjectRequestRevision:
        target = self._request_record_path("requests", request_id, revision, create=False)
        record = self._read(target, ProjectRequestRevision)
        if record.request.id != request_id or record.revision != revision:
            raise ProductRecordCorruption("ProjectRequestRevision filename identity mismatch")
        if revision > 1:
            previous = self.get_request_revision(request_id, revision - 1)
            try:
                _validate_request_lineage(previous, record)
            except ProductRecordLineageError as error:
                raise ProductRecordCorruption("ProjectRequestRevision chain is broken") from error
        return record

    def current_request_revision(
        self, request_id: ProjectRequestId | str
    ) -> ProjectRequestRevision:
        records = self._request_revisions(request_id)
        if not records:
            raise ProductRecordNotFound(f"ProjectRequestRevision not found: {request_id}")
        return records[-1]

    def put_product_spec(self, spec: ProductSpec) -> ProductSpec:
        _validate_record(spec)
        request = self.current_request_revision(spec.request_id).request
        if request.project_id != spec.project_id:
            raise ProductRecordLineageError("ProductSpec does not bind the stored ProjectRequest")
        if spec.version == 1:
            if spec.supersedes is not None:
                raise ProductRecordLineageError("first ProductSpec cannot supersede another spec")
        else:
            previous = self.get_product_spec(spec.request_id, spec.version - 1)
            if (
                spec.project_id != previous.project_id
                or spec.supersedes != previous.id
                or spec.request_id != previous.request_id
            ):
                raise ProductRecordLineageError("ProductSpec version lineage mismatch")
        target = self._request_record_path("specs", spec.request_id, spec.version)
        return self._put(target, spec, ProductSpec)

    def get_product_spec(self, request_id: ProjectRequestId | str, version: int) -> ProductSpec:
        target = self._request_record_path("specs", request_id, version, create=False)
        record = self._read(target, ProductSpec)
        if record.request_id != request_id or record.version != version:
            raise ProductRecordCorruption("ProductSpec filename identity mismatch")
        if version > 1:
            previous = self.get_product_spec(request_id, version - 1)
            if record.project_id != previous.project_id or record.supersedes != previous.id:
                raise ProductRecordCorruption("ProductSpec version chain is broken")
        return record

    def find_product_spec(self, spec_id: ProductSpecId | str) -> ProductSpec | None:
        validated_id = _validate_identity(_SPEC_ID_ADAPTER, spec_id, "ProductSpec")
        found: ProductSpec | None = None
        category = self._category("specs", create=False)
        if not category.exists():
            return None
        self._require_directory(category)
        for request_dir in sorted(category.iterdir(), key=lambda item: item.name):
            self._require_directory(request_dir)
            try:
                records = self.list_product_specs(request_dir.name)
            except ProductRecordNotFound as error:
                raise ProductRecordCorruption(
                    f"invalid ProductSpec request directory: {request_dir.name}"
                ) from error
            for record in records:
                if record.id == validated_id:
                    if found is not None:
                        raise ProductRecordCorruption(
                            f"duplicate ProductSpec identity: {validated_id}"
                        )
                    found = record
        return found

    def list_product_specs(self, request_id: ProjectRequestId | str) -> tuple[ProductSpec, ...]:
        request_dir = self._request_directory("specs", request_id, create=False)
        if not request_dir.exists():
            return ()
        records = self._list_numbered(request_dir, ProductSpec)
        previous: ProductSpec | None = None
        for expected, record in enumerate(records, start=1):
            if record.request_id != request_id or record.version != expected:
                raise ProductRecordCorruption("ProductSpec versions are not contiguous")
            if previous is None:
                if record.supersedes is not None:
                    raise ProductRecordCorruption("first ProductSpec has invalid supersedes")
            elif record.project_id != previous.project_id or record.supersedes != previous.id:
                raise ProductRecordCorruption("ProductSpec version chain is broken")
            previous = record
        return records

    def put_approval(self, approval: ProductSpecApproval) -> ProductSpecApproval:
        _validate_record(approval)
        spec = self.find_product_spec(approval.product_spec_id)
        if spec is None or (
            approval.request_id != spec.request_id
            or approval.project_id != spec.project_id
            or approval.product_spec_sha256 != spec.product_spec_sha256
        ):
            raise ProductRecordLineageError(
                "ProductSpecApproval does not bind a stored ProductSpec"
            )
        target = self._named_request_record_path(
            "approvals", approval.request_id, approval.product_spec_id
        )
        return self._put(target, approval, ProductSpecApproval)

    def get_approval(
        self, request_id: ProjectRequestId | str, product_spec_id: ProductSpecId | str
    ) -> ProductSpecApproval:
        target = self._named_request_record_path(
            "approvals", request_id, product_spec_id, create=False
        )
        record = self._read(target, ProductSpecApproval)
        if record.request_id != request_id or record.product_spec_id != product_spec_id:
            raise ProductRecordCorruption("ProductSpecApproval filename identity mismatch")
        self._validate_persisted_approval(record)
        return record

    def find_approval(self, approval_id: ProductApprovalId | str) -> ProductSpecApproval | None:
        validated_id = _validate_identity(_APPROVAL_ID_ADAPTER, approval_id, "approval")
        found: ProductSpecApproval | None = None
        category = self._category("approvals", create=False)
        if not category.exists():
            return None
        self._require_directory(category)
        for request_dir in sorted(category.iterdir(), key=lambda item: item.name):
            self._require_directory(request_dir)
            try:
                _validate_identity(_REQUEST_ID_ADAPTER, request_dir.name, "request")
            except ProductRecordNotFound as error:
                raise ProductRecordCorruption(
                    f"invalid approval request directory: {request_dir.name}"
                ) from error
            for path in sorted(request_dir.iterdir(), key=lambda item: item.name):
                if path.suffix != ".json":
                    raise ProductRecordCorruption(
                        f"unexpected product record filename: {path.name}"
                    )
                record = self._read(path, ProductSpecApproval)
                if record.request_id != request_dir.name or path.stem != record.product_spec_id:
                    raise ProductRecordCorruption("ProductSpecApproval filename identity mismatch")
                self._validate_persisted_approval(record)
                if record.id == validated_id:
                    if found is not None:
                        raise ProductRecordCorruption(
                            f"duplicate approval identity: {validated_id}"
                        )
                    found = record
        return found

    def put_checkpoint(self, checkpoint: ProductDiscoveryCheckpoint) -> ProductDiscoveryCheckpoint:
        _validate_record(checkpoint)
        if checkpoint.revision > 1:
            previous = self.get_checkpoint(checkpoint.request_id, checkpoint.revision - 1)
            if (
                previous.project_id != checkpoint.project_id
                or checkpoint.previous_checkpoint_sha256 != previous.checkpoint_sha256
                or checkpoint.updated_at < previous.updated_at
            ):
                raise ProductRecordLineageError("ProductDiscoveryCheckpoint lineage mismatch")
        self._validate_checkpoint_references(checkpoint, require_current=True)
        target = self._request_record_path(
            "checkpoint-history", checkpoint.request_id, checkpoint.revision
        )
        return self._put(target, checkpoint, ProductDiscoveryCheckpoint)

    def get_checkpoint(
        self, request_id: ProjectRequestId | str, revision: int
    ) -> ProductDiscoveryCheckpoint:
        target = self._request_record_path("checkpoint-history", request_id, revision, create=False)
        record = self._read(target, ProductDiscoveryCheckpoint)
        if record.request_id != request_id or record.revision != revision:
            raise ProductRecordCorruption("ProductDiscoveryCheckpoint filename identity mismatch")
        if revision > 1:
            previous = self.get_checkpoint(request_id, revision - 1)
            if (
                record.project_id != previous.project_id
                or record.previous_checkpoint_sha256 != previous.checkpoint_sha256
                or record.updated_at < previous.updated_at
            ):
                raise ProductRecordCorruption("checkpoint chain is broken")
        try:
            self._validate_checkpoint_references(record, require_current=False)
        except (ProductRecordLineageError, ProductRecordNotFound) as error:
            raise ProductRecordCorruption(
                "checkpoint references do not match durable facts"
            ) from error
        return record

    def current_checkpoint(self, request_id: ProjectRequestId | str) -> ProductDiscoveryCheckpoint:
        request_dir = self._request_directory("checkpoint-history", request_id, create=False)
        if not request_dir.exists():
            raise ProductRecordNotFound(f"ProductDiscoveryCheckpoint not found: {request_id}")
        records = self._list_numbered(request_dir, ProductDiscoveryCheckpoint)
        if not records:
            raise ProductRecordNotFound(f"ProductDiscoveryCheckpoint not found: {request_id}")
        for expected, record in enumerate(records, start=1):
            if record.request_id != request_id or record.revision != expected:
                raise ProductRecordCorruption("checkpoint revisions are not contiguous")
            if (
                expected > 1
                and record.previous_checkpoint_sha256 != records[expected - 2].checkpoint_sha256
            ):
                raise ProductRecordCorruption("checkpoint chain is broken")
        try:
            self._validate_checkpoint_references(records[-1], require_current=False)
        except (ProductRecordLineageError, ProductRecordNotFound) as error:
            raise ProductRecordCorruption(
                "current checkpoint references do not match durable facts"
            ) from error
        return records[-1]

    def put_operation(self, record: ProductOperationRecord) -> ProductOperationRecord:
        _validate_record(record)
        target = self._named_record_path("operations", record.operation_id)
        return self._put(target, record, ProductOperationRecord)

    def get_operation(self, operation_id: ProductOperationId | str) -> ProductOperationRecord:
        validated = _validate_identity(_OPERATION_ID_ADAPTER, operation_id, "operation")
        target = self._named_record_path("operations", validated, create=False)
        record = self._read(target, ProductOperationRecord)
        if record.operation_id != validated:
            raise ProductRecordCorruption("ProductOperationRecord filename identity mismatch")
        return record

    def find_operation(
        self, operation_id: ProductOperationId | str
    ) -> ProductOperationRecord | None:
        try:
            return self.get_operation(operation_id)
        except ProductRecordNotFound:
            return None

    def _request_revisions(
        self, request_id: ProjectRequestId | str
    ) -> tuple[ProjectRequestRevision, ...]:
        request_dir = self._request_directory("requests", request_id, create=False)
        if not request_dir.exists():
            return ()
        records = self._list_numbered(request_dir, ProjectRequestRevision)
        previous: ProjectRequestRevision | None = None
        for expected, record in enumerate(records, start=1):
            if record.request.id != request_id or record.revision != expected:
                raise ProductRecordCorruption("ProjectRequestRevision sequence is not contiguous")
            if previous is not None:
                try:
                    _validate_request_lineage(previous, record)
                except ProductRecordLineageError as error:
                    raise ProductRecordCorruption(
                        "ProjectRequestRevision chain is broken"
                    ) from error
            previous = record
        return records

    def _validate_checkpoint_references(
        self,
        checkpoint: ProductDiscoveryCheckpoint,
        *,
        require_current: bool,
    ) -> None:
        request_revision = self.get_request_revision(
            checkpoint.request_id, checkpoint.request_revision
        )
        if (
            request_revision.request.project_id != checkpoint.project_id
            or request_revision.request.request_sha256 != checkpoint.request_sha256
        ):
            raise ProductRecordLineageError("checkpoint ProjectRequest reference mismatch")
        if (
            require_current
            and self.current_request_revision(checkpoint.request_id).revision
            != checkpoint.request_revision
        ):
            raise ProductRecordLineageError("checkpoint does not reference current ProjectRequest")
        dialogue = self.list_dialogue(checkpoint.request_id)
        if checkpoint.dialogue_count > len(dialogue):
            raise ProductRecordLineageError("checkpoint dialogue count exceeds durable dialogue")
        head = (
            None
            if checkpoint.dialogue_count == 0
            else dialogue[checkpoint.dialogue_count - 1].dialogue_sha256
        )
        if checkpoint.dialogue_head_sha256 != head or (
            require_current and checkpoint.dialogue_count != len(dialogue)
        ):
            raise ProductRecordLineageError("checkpoint dialogue head/count mismatch")
        spec: ProductSpec | None = None
        if checkpoint.current_product_spec_version is not None:
            spec = self.get_product_spec(
                checkpoint.request_id, checkpoint.current_product_spec_version
            )
            if (
                spec.project_id != checkpoint.project_id
                or spec.id != checkpoint.current_product_spec_id
                or spec.product_spec_sha256 != checkpoint.current_product_spec_sha256
            ):
                raise ProductRecordLineageError("checkpoint ProductSpec reference mismatch")
            if (
                require_current
                and self.list_product_specs(checkpoint.request_id)[-1].version
                != checkpoint.current_product_spec_version
            ):
                raise ProductRecordLineageError("checkpoint does not reference current ProductSpec")
        if checkpoint.current_approval_id is not None:
            if spec is None:
                raise ProductRecordLineageError("checkpoint approval requires ProductSpec")
            approval = self.get_approval(checkpoint.request_id, spec.id)
            if (
                approval.id != checkpoint.current_approval_id
                or approval.approval_sha256 != checkpoint.current_approval_sha256
            ):
                raise ProductRecordLineageError("checkpoint approval reference mismatch")
            expected_decision = {
                ProductDiscoveryStatus.CHANGES_REQUESTED: ProductApprovalDecision.REQUEST_CHANGES,
                ProductDiscoveryStatus.APPROVED: ProductApprovalDecision.APPROVED,
            }.get(checkpoint.status)
            if expected_decision is None or approval.decision is not expected_decision:
                raise ProductRecordLineageError(
                    "checkpoint status does not match approval decision"
                )

    def _validate_persisted_approval(self, approval: ProductSpecApproval) -> None:
        spec = self.find_product_spec(approval.product_spec_id)
        if spec is None or (
            spec.request_id != approval.request_id
            or spec.project_id != approval.project_id
            or spec.product_spec_sha256 != approval.product_spec_sha256
        ):
            raise ProductRecordCorruption("ProductSpecApproval does not bind a durable ProductSpec")

    def _put(
        self,
        target: Path,
        record: _RecordT,
        model: type[_RecordT],
    ) -> _RecordT:
        if target.exists() or target.is_symlink():
            existing = self._read(target, model)
            if existing.to_wire() == record.to_wire():
                return existing
            raise ProductRecordConflict(
                f"product record already exists with different content: {target.name}"
            )
        payload = record.to_wire()
        envelope: WirePayload = {"record": payload, "sha256": _digest(payload)}
        if not _atomic_write(self._root, target, envelope):
            existing = self._read(target, model)
            if existing.to_wire() == record.to_wire():
                return existing
            raise ProductRecordConflict(
                f"product record was concurrently created with different content: {target.name}"
            )
        return self._read(target, model)

    def _read(self, target: Path, model: type[_RecordT]) -> _RecordT:
        try:
            payload: object = json.loads(
                _read_trusted_text(self._root, target),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON value: {value}")
                ),
            )
            if not isinstance(payload, dict) or set(payload) != _RECORD_KEYS:
                raise ProductRecordCorruption(
                    f"product record has an invalid envelope: {target.name}"
                )
            record_payload = payload.get("record")
            digest = payload.get("sha256")
            if not isinstance(record_payload, dict) or not isinstance(digest, str):
                raise ProductRecordCorruption(f"product record is incomplete: {target.name}")
            if digest != _digest(record_payload):
                raise ProductRecordCorruption(
                    f"product record envelope digest mismatch: {target.name}"
                )
            record = model.model_validate(record_payload)
            _validate_record(record)
            return record
        except ProductRecordCorruption:
            raise
        except ProductRecordIntegrityError as error:
            raise ProductRecordCorruption(
                f"product record inner digest mismatch: {target.name}"
            ) from error
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            raise ProductRecordCorruption(f"cannot decode product record: {target.name}") from error

    def _list_numbered(self, directory: Path, model: type[_RecordT]) -> tuple[_RecordT, ...]:
        self._require_directory(directory)
        files = sorted(directory.iterdir(), key=lambda item: item.name)
        records: list[_RecordT] = []
        for expected, path in enumerate(files, start=1):
            if path.name != f"{expected:08d}.json":
                raise ProductRecordCorruption(f"unexpected product record filename: {path.name}")
            records.append(self._read(path, model))
        return tuple(records)

    def _request_record_path(
        self,
        category: str,
        request_id: ProjectRequestId | str,
        sequence: int,
        *,
        create: bool = True,
    ) -> Path:
        if isinstance(sequence, bool) or sequence < 1:
            raise ProductRecordNotFound(str(sequence))
        return self._request_directory(category, request_id, create=create) / f"{sequence:08d}.json"

    def _named_request_record_path(
        self,
        category: str,
        request_id: ProjectRequestId | str,
        identity: ProductSpecId | str,
        *,
        create: bool = True,
    ) -> Path:
        validated = _validate_identity(_SPEC_ID_ADAPTER, identity, "ProductSpec")
        return self._request_directory(category, request_id, create=create) / f"{validated}.json"

    def _request_directory(
        self,
        category: str,
        request_id: ProjectRequestId | str,
        *,
        create: bool,
    ) -> Path:
        validated = _validate_identity(_REQUEST_ID_ADAPTER, request_id, "request")
        category_dir = self._category(category, create=create)
        target = category_dir / validated
        if create:
            _mkdir_trusted(target, self._root)
        elif target.exists() or target.is_symlink():
            self._require_directory(target)
        self._require_contained(target)
        return target

    def _named_record_path(self, category: str, identity: str, *, create: bool = True) -> Path:
        category_dir = self._category(category, create=create)
        return category_dir / f"{identity}.json"

    def _category(self, category: str, *, create: bool) -> Path:
        if category not in {
            "dialogue",
            "requests",
            "specs",
            "approvals",
            "checkpoint-history",
            "operations",
        }:
            raise ProductRecordPathError(f"unknown Product record category: {category}")
        self._require_trusted_root()
        target = self._root / category
        if create:
            _mkdir_trusted(target, self._root)
        elif target.exists() or target.is_symlink():
            self._require_directory(target)
        self._require_contained(target)
        return target

    def _require_trusted_root(self) -> None:
        if (
            self._root.is_symlink()
            or not self._root.is_dir()
            or self._root.resolve(strict=False) != self._root
        ):
            raise ProductRecordPathError(
                f"Product record store root is no longer trusted: {self._root}"
            )

    def _require_directory(self, path: Path) -> None:
        self._require_contained(path)
        if path.is_symlink() or not path.is_dir() or path.resolve(strict=False) != path:
            raise ProductRecordPathError(f"untrusted Product record directory: {path}")

    def _require_contained(self, path: Path) -> None:
        self._require_trusted_root()
        try:
            path.resolve(strict=False).relative_to(self._root)
        except ValueError as error:
            raise ProductRecordPathError(
                f"Product record path escapes its store root: {path}"
            ) from error


def _validate_request_lineage(
    previous: ProjectRequestRevision, current: ProjectRequestRevision
) -> None:
    stable_previous = previous.request.model_dump(
        mode="json", exclude={"status", "updated_at", "request_sha256"}
    )
    stable_current = current.request.model_dump(
        mode="json", exclude={"status", "updated_at", "request_sha256"}
    )
    if (
        current.revision != previous.revision + 1
        or current.supersedes_sha256 != previous.request_revision_sha256
        or stable_current != stable_previous
        or current.request.updated_at < previous.request.updated_at
    ):
        raise ProductRecordLineageError("ProjectRequestRevision lineage mismatch")


def _validate_record(record: DomainModel) -> None:
    validator = getattr(record, "validate_integrity", None)
    if validator is None or not callable(validator):
        raise ProductRecordIntegrityError(
            f"record type has no integrity contract: {type(record).__name__}"
        )
    try:
        validator()
    except ProductRecordIntegrityError:
        raise
    except (StageContractError, ValueError) as error:
        raise ProductRecordIntegrityError(
            f"{type(record).__name__} digest does not match content"
        ) from error


def _validate_identity[IdentityT](
    adapter: TypeAdapter[IdentityT], value: IdentityT | str, label: str
) -> IdentityT:
    try:
        return adapter.validate_python(value)
    except ValidationError as error:
        raise ProductRecordNotFound(f"invalid {label} identity: {value}") from error


def _mkdir_trusted(path: Path, root: Path) -> None:
    if path.is_symlink():
        raise ProductRecordPathError(f"Product record directory cannot be a symlink: {path}")
    try:
        path.mkdir(exist_ok=True)
    except OSError as error:
        raise ProductRecordStoreError(
            f"cannot initialize Product record directory: {path}"
        ) from error
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ProductRecordPathError(
            f"Product record directory escapes its root: {path}"
        ) from error
    if not path.is_dir() or path.is_symlink() or resolved != path:
        raise ProductRecordPathError(f"untrusted Product record directory: {path}")


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _atomic_write(root: Path, target: Path, payload: WirePayload) -> bool:
    """Publish relative to trusted directory FDs so symlink swaps cannot escape."""
    directory_fd: int | None = None
    temporary_name = f".{target.name}.{secrets.token_hex(16)}.tmp"
    published = False
    try:
        relative = target.relative_to(root)
        directory_fd = _open_directory_chain(root, relative.parent.parts)
        if not _directory_fd_matches_path(directory_fd, target.parent):
            raise ProductRecordPathError(
                f"Product record directory changed before publish: {target.parent}"
            )
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(descriptor, mode="w", encoding="utf-8") as temporary:
            temporary.write(_canonical_json(payload))
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(
                temporary_name,
                target.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            return False
        published = True
        if not _directory_fd_matches_path(directory_fd, target.parent):
            os.unlink(target.name, dir_fd=directory_fd)
            published = False
            raise ProductRecordPathError(
                f"Product record directory changed during publish: {target.parent}"
            )
        os.fsync(directory_fd)
        return True
    except ProductRecordPathError:
        raise
    except OSError as error:
        raise ProductRecordStoreError(
            f"cannot atomically write Product record: {target.name}"
        ) from error
    finally:
        if directory_fd is not None:
            with suppress(OSError):
                os.unlink(temporary_name, dir_fd=directory_fd)
            if published and not _directory_fd_matches_path(directory_fd, target.parent):
                with suppress(OSError):
                    os.unlink(target.name, dir_fd=directory_fd)
            os.close(directory_fd)


def _open_directory_chain(root: Path, parts: tuple[str, ...]) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    try:
        for part in parts:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _directory_fd_matches_path(descriptor: int, path: Path) -> bool:
    try:
        by_path = path.lstat()
        by_fd = os.fstat(descriptor)
    except OSError:
        return False
    return (
        stat.S_ISDIR(by_path.st_mode)
        and by_path.st_dev == by_fd.st_dev
        and by_path.st_ino == by_fd.st_ino
    )


def _read_trusted_text(root: Path, target: Path) -> str:
    """Read one regular file through trusted directory FDs and detect parent swaps."""
    directory_fd: int | None = None
    record_fd: int | None = None
    try:
        try:
            relative = target.relative_to(root)
        except ValueError as error:
            raise ProductRecordPathError(
                f"Product record path escapes its store root: {target}"
            ) from error
        directory_fd = _open_directory_chain(root, relative.parent.parts)
        if not _directory_fd_matches_path(directory_fd, target.parent):
            raise ProductRecordPathError(
                f"Product record directory changed before read: {target.parent}"
            )
        record_fd = os.open(
            relative.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(record_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ProductRecordPathError(
                f"product record path is not a regular file: {target.name}"
            )
        with os.fdopen(record_fd, mode="rb", closefd=True) as record_file:
            record_fd = None
            content = record_file.read()
            after = os.fstat(record_file.fileno())
        if not _same_file_snapshot(before, after):
            raise ProductRecordPathError(f"product record changed during read: {target.name}")
        if not _directory_fd_matches_path(directory_fd, target.parent):
            raise ProductRecordPathError(
                f"Product record directory changed during read: {target.parent}"
            )
        return content.decode("utf-8")
    except ProductRecordPathError:
        raise
    except FileNotFoundError as error:
        raise ProductRecordNotFound(target.name) from error
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ProductRecordPathError(
                f"product record path is a symlink or has an untrusted parent: {target.name}"
            ) from error
        raise
    finally:
        if record_fd is not None:
            os.close(record_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _same_file_snapshot(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        stat.S_ISREG(after.st_mode)
        and before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )


__all__ = [
    "FileProductRecordStore",
    "ProductRecordConflict",
    "ProductRecordCorruption",
    "ProductRecordIntegrityError",
    "ProductRecordLineageError",
    "ProductRecordNotFound",
    "ProductRecordPathError",
    "ProductRecordStore",
    "ProductRecordStoreError",
]
