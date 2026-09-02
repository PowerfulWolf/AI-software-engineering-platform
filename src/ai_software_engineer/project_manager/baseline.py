"""Task-free compilation of organization and project rule baselines.

Project preparation happens before a product request, so this compiler deliberately has no
``Task`` input and never invents Task constraints.  Native project documents remain opaque
references unless an adapter can supply an explicit :class:`SpecRule` backed by the exact
``ProjectProfile`` URI and digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from contextlib import suppress
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import (
    DomainModel,
    NonEmptyStr,
    WirePayload,
    ensure_unique,
)
from ai_software_engineer.project_profile import ProjectProfile, Sha256
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.spec_compiler import (
    HardPolicyMissing,
    RuleField,
    RuleScope,
    SpecConflictClass,
    SpecRule,
    SpecRuleId,
    SpecRuleLayer,
    SpecSourceMismatch,
    SpecSourceRef,
)

ProjectSpecConflictId = Annotated[
    str, StringConstraints(pattern=r"^project_spec_conflict_[a-f0-9]{64}$")
]


class ProjectBaselineCompilerError(RuntimeError):
    """Base error for an invalid project-level baseline request."""


class TaskScopedRuleRejected(ProjectBaselineCompilerError):
    """Raised when preparation is asked to compile a Task-scoped rule."""


class ProjectBaselineIntegrityError(ProjectBaselineCompilerError):
    """Raised when a baseline, conflict, or result digest no longer matches its content."""


class ProjectBaselineRecordStoreError(RuntimeError):
    """Base error for durable project-baseline compilation records."""


class ProjectBaselineRecordConflict(ProjectBaselineRecordStoreError):
    """Raised when one immutable compilation identity is reused with changed content."""


class ProjectBaselineRecordCorruption(ProjectBaselineRecordStoreError):
    """Raised when a persisted compilation or envelope cannot be trusted."""


class ProjectBaselineRecordNotFound(ProjectBaselineRecordStoreError):
    """Raised when an exact compilation digest is absent from the sidecar."""


class ProjectBaselineCompilationStatus(StrEnum):
    """Exclusive outcome of one project-baseline compilation."""

    COMPILED = "COMPILED"
    CONFLICT = "CONFLICT"


class ProjectSpecConflict(DomainModel):
    """Project-scoped conflict discovered before a Delivery Task exists."""

    kind: Literal["PROJECT_SPEC_CONFLICT"] = "PROJECT_SPEC_CONFLICT"
    schema_version: Literal["v0.1"] = "v0.1"
    id: ProjectSpecConflictId
    project_id: ProjectId
    project_profile_sha256: Sha256
    field: RuleField
    classification: SpecConflictClass
    rules: Annotated[tuple[SpecRule, ...], Field(min_length=2)]
    reason: NonEmptyStr
    human_question: NonEmptyStr
    recovery_conditions: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    detected_at: AwareDatetime
    conflict_sha256: Sha256

    @model_validator(mode="after")
    def validate_conflict(self) -> Self:
        ensure_unique((rule.id for rule in self.rules), "ProjectSpecConflict rule IDs")
        ensure_unique(self.recovery_conditions, "ProjectSpecConflict recovery conditions")
        if any(rule.field != self.field for rule in self.rules):
            raise ValueError("ProjectSpecConflict rules must share the conflict field")
        if any(rule.layer is SpecRuleLayer.TASK for rule in self.rules):
            raise ValueError("ProjectSpecConflict cannot contain Task-scoped rules")
        expected_class = (
            SpecConflictClass.HARD_SAFETY
            if any(rule.layer is SpecRuleLayer.PLATFORM_HARD for rule in self.rules)
            else SpecConflictClass.ENGINEERING
        )
        if self.classification is not expected_class:
            raise ValueError("ProjectSpecConflict classification does not match its rules")
        if len(_conflicting_participants(self.rules)) < 2:
            raise ValueError("ProjectSpecConflict requires overlapping rules with different values")
        return self

    def validate_integrity(self) -> None:
        """Reject changed durable conflict content or identity."""
        expected = _conflict_digest(self)
        if self.conflict_sha256 != expected or self.id != f"project_spec_conflict_{expected}":
            raise ProjectBaselineIntegrityError(
                f"ProjectSpecConflict identity does not match content: {self.id}"
            )


class ProjectWaitingHumanRoute(DomainModel):
    """Pure routing fact that prevents product discovery from starting."""

    kind: Literal["project_spec_waiting_human_route"] = "project_spec_waiting_human_route"
    work_item_status: Literal["WAITING_HUMAN"] = "WAITING_HUMAN"
    reason: Literal["PROJECT_SPEC_CONFLICT"] = "PROJECT_SPEC_CONFLICT"
    conflict_ids: Annotated[tuple[ProjectSpecConflictId, ...], Field(min_length=1)]
    product_agent_start_allowed: Literal[False] = False
    recovery_conditions: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_route(self) -> Self:
        ensure_unique(self.conflict_ids, "ProjectWaitingHumanRoute conflict IDs")
        ensure_unique(self.recovery_conditions, "ProjectWaitingHumanRoute recovery conditions")
        return self


class ProjectSpecBaseline(DomainModel):
    """Conflict-free platform/project rules safe for project preparation."""

    kind: Literal["project_spec_baseline"] = "project_spec_baseline"
    schema_version: Literal["v0.1"] = "v0.1"
    project_id: ProjectId
    project_profile_sha256: Sha256
    rules: Annotated[tuple[SpecRule, ...], Field(min_length=1)]
    opaque_project_sources: tuple[SpecSourceRef, ...] = ()
    baseline_sha256: Sha256

    @model_validator(mode="after")
    def validate_baseline(self) -> Self:
        ensure_unique((rule.id for rule in self.rules), "ProjectSpecBaseline rule IDs")
        ensure_unique(
            (source.uri for source in self.opaque_project_sources),
            "ProjectSpecBaseline opaque source URIs",
        )
        structured_project_sources = {
            rule.source_uri for rule in self.rules if rule.layer is SpecRuleLayer.PROJECT
        }
        if any(source.uri in structured_project_sources for source in self.opaque_project_sources):
            raise ValueError("ProjectSpecBaseline cannot keep a structured project source opaque")
        if not any(rule.layer is SpecRuleLayer.PLATFORM_HARD for rule in self.rules):
            raise ValueError("ProjectSpecBaseline requires a PLATFORM_HARD rule")
        if any(rule.layer is SpecRuleLayer.TASK for rule in self.rules):
            raise ValueError("ProjectSpecBaseline cannot contain Task-scoped rules")
        if _detect_conflicting_fields(self.rules):
            raise ValueError("ProjectSpecBaseline cannot contain unresolved conflicts")
        return self

    @property
    def source_uris(self) -> tuple[str, ...]:
        """Return every platform and project source exactly once in stable order."""
        return tuple(
            sorted(
                {
                    *(rule.source_uri for rule in self.rules),
                    *(source.uri for source in self.opaque_project_sources),
                }
            )
        )

    def validate_integrity(self) -> None:
        """Reject a baseline whose canonical digest no longer matches its content."""
        if self.baseline_sha256 != _baseline_digest(self):
            raise ProjectBaselineIntegrityError("ProjectSpecBaseline digest does not match content")


class ProjectBaselineCompilation(DomainModel):
    """Exclusive compiled-or-WAITING_HUMAN result for project preparation."""

    kind: Literal["project_baseline_compilation"] = "project_baseline_compilation"
    schema_version: Literal["v0.1"] = "v0.1"
    status: ProjectBaselineCompilationStatus
    project_id: ProjectId
    project_profile_sha256: Sha256
    compiled_spec: ProjectSpecBaseline | None = None
    conflicts: tuple[ProjectSpecConflict, ...] = ()
    route: ProjectWaitingHumanRoute | None = None
    compiled_at: AwareDatetime
    compilation_sha256: Sha256

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status is ProjectBaselineCompilationStatus.COMPILED:
            if self.compiled_spec is None or self.conflicts or self.route is not None:
                raise ValueError("COMPILED result requires only compiled_spec")
            if (
                self.compiled_spec.project_id != self.project_id
                or self.compiled_spec.project_profile_sha256 != self.project_profile_sha256
            ):
                raise ValueError("compiled_spec does not match compilation project/profile")
        elif self.compiled_spec is not None or not self.conflicts or self.route is None:
            raise ValueError("CONFLICT result requires conflicts and WAITING_HUMAN route")
        else:
            if any(
                conflict.project_id != self.project_id
                or conflict.project_profile_sha256 != self.project_profile_sha256
                for conflict in self.conflicts
            ):
                raise ValueError("conflict does not match compilation project/profile")
            if self.route.conflict_ids != tuple(conflict.id for conflict in self.conflicts):
                raise ValueError("route conflict_ids must match compilation conflicts")
        return self

    def validate_integrity(self) -> None:
        """Validate the result and every nested durable record."""
        if self.compiled_spec is not None:
            self.compiled_spec.validate_integrity()
        for conflict in self.conflicts:
            conflict.validate_integrity()
        if self.compilation_sha256 != _compilation_digest(self):
            raise ProjectBaselineIntegrityError(
                "ProjectBaselineCompilation digest does not match content"
            )


class ProjectBaselineCompiler:
    """Pure compiler for the project-level baseline used during preparation."""

    def compile(
        self,
        profile: ProjectProfile,
        rules: Sequence[SpecRule],
        *,
        compiled_at: datetime,
    ) -> ProjectBaselineCompilation:
        """Compile platform/project rules without manufacturing a Task."""
        _require_aware(compiled_at, "compiled_at")
        profile.validate_integrity()
        if any(rule.layer is SpecRuleLayer.TASK for rule in rules):
            raise TaskScopedRuleRejected(
                "project preparation cannot compile Task rules before a Task exists"
            )
        if not any(rule.layer is SpecRuleLayer.PLATFORM_HARD for rule in rules):
            raise HardPolicyMissing("at least one PLATFORM_HARD rule is required")
        ensure_unique((rule.id for rule in rules), "SpecRule IDs")
        _validate_project_rule_sources(profile, rules)
        ordered = tuple(sorted(rules, key=_rule_sort_key))
        conflicts = _detect_conflicts(profile, ordered, compiled_at)
        if conflicts:
            route = ProjectWaitingHumanRoute(
                conflict_ids=tuple(conflict.id for conflict in conflicts),
                recovery_conditions=(
                    "record an evidence-backed human resolution",
                    "recompile the exact project profile and rule source hashes",
                ),
            )
            return _seal_compilation(
                ProjectBaselineCompilation(
                    status=ProjectBaselineCompilationStatus.CONFLICT,
                    project_id=profile.project_id,
                    project_profile_sha256=profile.profile_sha256,
                    conflicts=conflicts,
                    route=route,
                    compiled_at=compiled_at,
                    compilation_sha256="0" * 64,
                )
            )

        provisional = ProjectSpecBaseline(
            project_id=profile.project_id,
            project_profile_sha256=profile.profile_sha256,
            rules=ordered,
            opaque_project_sources=_opaque_project_sources(profile, ordered),
            baseline_sha256="0" * 64,
        )
        baseline = provisional.model_copy(update={"baseline_sha256": _baseline_digest(provisional)})
        return _seal_compilation(
            ProjectBaselineCompilation(
                status=ProjectBaselineCompilationStatus.COMPILED,
                project_id=profile.project_id,
                project_profile_sha256=profile.profile_sha256,
                compiled_spec=baseline,
                compiled_at=compiled_at,
                compilation_sha256="0" * 64,
            )
        )


class FileProjectBaselineCompilationStore:
    """Append-once project-baseline history split across policy and conflict directories.

    A successful baseline is policy input, while a conflict is a blocking fact.  Both live
    under the registered sidecar and are addressed by the stable compilation digest.  The
    target project is never considered a storage root.
    """

    _RECORD_KEYS = frozenset(("compilation", "sha256"))

    def record(
        self,
        workspace: ProjectWorkspace,
        compilation: ProjectBaselineCompilation,
    ) -> ProjectBaselineCompilation:
        """Atomically append a compilation or return its exact first persisted replay."""
        compilation.validate_integrity()
        _require_workspace_identity(workspace, compilation)
        target = self._record_path(workspace, compilation)
        if target.exists() or target.is_symlink():
            existing = self.get(workspace, compilation.compilation_sha256)
            if existing.compilation_sha256 == compilation.compilation_sha256:
                return existing
            raise ProjectBaselineRecordConflict(
                "project-baseline compilation identity already has different content"
            )
        compilation_payload = compilation.to_wire()
        envelope: WirePayload = {
            "compilation": compilation_payload,
            "sha256": _sha256(_canonical_json(compilation_payload)),
        }
        if not _atomic_json_write(target, envelope):
            return self.get(workspace, compilation.compilation_sha256)
        return self.get(workspace, compilation.compilation_sha256)

    def get(
        self,
        workspace: ProjectWorkspace,
        compilation_sha256: Sha256 | str,
    ) -> ProjectBaselineCompilation:
        """Read one exact compilation and revalidate envelope, payload, and identity."""
        try:
            digest = TypeAdapter(Sha256).validate_python(compilation_sha256)
        except ValidationError as error:
            raise ProjectBaselineRecordNotFound(str(compilation_sha256)) from error
        candidates = tuple(
            path
            for path in self._candidate_paths(workspace, digest)
            if path.exists() or path.is_symlink()
        )
        if not candidates:
            raise ProjectBaselineRecordNotFound(digest)
        if len(candidates) != 1:
            raise ProjectBaselineRecordCorruption(
                f"project-baseline compilation exists in multiple sidecar roots: {digest}"
            )
        target = candidates[0]
        if target.is_symlink() or not target.is_file():
            raise ProjectBaselineRecordCorruption(
                f"project-baseline record path is not a regular file: {digest}"
            )
        try:
            payload: object = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != self._RECORD_KEYS:
                raise ProjectBaselineRecordCorruption(
                    f"project-baseline record has an invalid envelope: {digest}"
                )
            compilation_payload = payload.get("compilation")
            envelope_digest = payload.get("sha256")
            if not isinstance(compilation_payload, dict) or not isinstance(envelope_digest, str):
                raise ProjectBaselineRecordCorruption(
                    f"project-baseline record is incomplete: {digest}"
                )
            if envelope_digest != _sha256(_canonical_json(compilation_payload)):
                raise ProjectBaselineRecordCorruption(
                    f"project-baseline envelope digest mismatch: {digest}"
                )
            compilation = ProjectBaselineCompilation.model_validate(compilation_payload)
            compilation.validate_integrity()
        except ProjectBaselineRecordCorruption:
            raise
        except (
            OSError,
            UnicodeError,
            ValueError,
            ValidationError,
            ProjectBaselineIntegrityError,
        ) as error:
            raise ProjectBaselineRecordCorruption(
                f"cannot decode project-baseline compilation: {digest}"
            ) from error
        _require_workspace_identity(workspace, compilation)
        if compilation.compilation_sha256 != digest:
            raise ProjectBaselineRecordCorruption(
                f"project-baseline filename identity mismatch: {digest}"
            )
        expected_root = self._compilation_root(workspace, compilation.status)
        if target.parent != expected_root:
            raise ProjectBaselineRecordCorruption(
                f"project-baseline status is stored under the wrong sidecar root: {digest}"
            )
        return compilation

    def _record_path(
        self,
        workspace: ProjectWorkspace,
        compilation: ProjectBaselineCompilation,
    ) -> Path:
        root = self._compilation_root(workspace, compilation.status)
        return root / f"{compilation.compilation_sha256}.json"

    def _candidate_paths(
        self,
        workspace: ProjectWorkspace,
        compilation_sha256: Sha256,
    ) -> tuple[Path, Path]:
        return (
            self._compilation_root(workspace, ProjectBaselineCompilationStatus.COMPILED)
            / f"{compilation_sha256}.json",
            self._compilation_root(workspace, ProjectBaselineCompilationStatus.CONFLICT)
            / f"{compilation_sha256}.json",
        )

    @staticmethod
    def _compilation_root(
        workspace: ProjectWorkspace,
        status: ProjectBaselineCompilationStatus,
    ) -> Path:
        if status is ProjectBaselineCompilationStatus.COMPILED:
            directory_name = "policy"
            base = workspace.directory("policy")
        else:
            directory_name = "spec-conflicts"
            base = workspace.directory("spec-conflicts")
        if base.is_symlink() or not base.is_dir():
            raise ProjectBaselineRecordCorruption(
                f"project sidecar directory is not trusted: {directory_name}"
            )
        root = base / "project-baseline-compilations"
        if root.is_symlink():
            raise ProjectBaselineRecordCorruption(
                f"project-baseline store root is a symlink: {directory_name}"
            )
        try:
            root.mkdir(exist_ok=True)
        except OSError as error:
            raise ProjectBaselineRecordStoreError(
                f"cannot initialize project-baseline store: {directory_name}"
            ) from error
        resolved_base = base.resolve(strict=False)
        resolved_root = root.resolve(strict=False)
        if (
            base.is_symlink()
            or root.is_symlink()
            or not root.is_dir()
            or resolved_root.parent != resolved_base
        ):
            raise ProjectBaselineRecordCorruption(
                f"project-baseline store root escaped its sidecar: {directory_name}"
            )
        return root


def _validate_project_rule_sources(
    profile: ProjectProfile,
    rules: Sequence[SpecRule],
) -> None:
    project_sources = {source.uri: source.sha256 for source in profile.native_rules}
    for rule in rules:
        if rule.layer is SpecRuleLayer.PROJECT and (
            project_sources.get(rule.source_uri) != rule.source_sha256
        ):
            raise SpecSourceMismatch(
                f"project rule source is absent or hash-mismatched: {rule.source_uri}"
            )


def _opaque_project_sources(
    profile: ProjectProfile,
    rules: Sequence[SpecRule],
) -> tuple[SpecSourceRef, ...]:
    """Return only native sources that no structured PROJECT rule consumed."""
    structured_source_uris = {
        rule.source_uri for rule in rules if rule.layer is SpecRuleLayer.PROJECT
    }
    return tuple(
        SpecSourceRef(uri=source.uri, sha256=source.sha256)
        for source in profile.native_rules
        if source.uri not in structured_source_uris
    )


def _require_workspace_identity(
    workspace: ProjectWorkspace,
    compilation: ProjectBaselineCompilation,
) -> None:
    try:
        workspace.manifest.validate_binding(workspace.root)
    except RuntimeError as error:
        raise ProjectBaselineRecordCorruption("project workspace binding is not trusted") from error
    if compilation.project_id != workspace.project_id:
        raise ProjectBaselineRecordCorruption(
            "project-baseline compilation belongs to another project workspace"
        )


def _detect_conflicts(
    profile: ProjectProfile,
    rules: tuple[SpecRule, ...],
    detected_at: datetime,
) -> tuple[ProjectSpecConflict, ...]:
    by_field: dict[str, list[SpecRule]] = defaultdict(list)
    for rule in rules:
        by_field[rule.field].append(rule)
    conflicts: list[ProjectSpecConflict] = []
    for field, candidates in sorted(by_field.items()):
        participants = _conflicting_participants(candidates)
        if len(participants) < 2:
            continue
        classification = (
            SpecConflictClass.HARD_SAFETY
            if any(rule.layer is SpecRuleLayer.PLATFORM_HARD for rule in participants)
            else SpecConflictClass.ENGINEERING
        )
        provisional = ProjectSpecConflict(
            id=f"project_spec_conflict_{'0' * 64}",
            project_id=profile.project_id,
            project_profile_sha256=profile.profile_sha256,
            field=field,
            classification=classification,
            rules=participants,
            reason=f"Overlapping project-baseline rules assign different values to {field}",
            human_question=(
                f"Which source should govern {field}, or which lower rule should be updated?"
            ),
            recovery_conditions=(
                "record an evidence-backed human resolution",
                "recompile all referenced source hashes",
            ),
            detected_at=detected_at,
            conflict_sha256="0" * 64,
        )
        digest = _conflict_digest(provisional)
        conflicts.append(
            provisional.model_copy(
                update={
                    "id": f"project_spec_conflict_{digest}",
                    "conflict_sha256": digest,
                }
            )
        )
    return tuple(conflicts)


def _detect_conflicting_fields(rules: Sequence[SpecRule]) -> tuple[str, ...]:
    by_field: dict[str, list[SpecRule]] = defaultdict(list)
    for rule in rules:
        by_field[rule.field].append(rule)
    return tuple(
        field
        for field, candidates in sorted(by_field.items())
        if len(_conflicting_participants(candidates)) >= 2
    )


def _conflicting_participants(candidates: Sequence[SpecRule]) -> tuple[SpecRule, ...]:
    participants: dict[SpecRuleId, SpecRule] = {}
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if _canonical_json(left.value) == _canonical_json(right.value):
                continue
            if _scopes_overlap(left.scopes, right.scopes):
                participants[left.id] = left
                participants[right.id] = right
    return tuple(sorted(participants.values(), key=_rule_sort_key))


def _scopes_overlap(left: tuple[RuleScope, ...], right: tuple[RuleScope, ...]) -> bool:
    return "*" in left or "*" in right or bool(set(left) & set(right))


_LAYER_RANK = {
    SpecRuleLayer.PLATFORM_HARD: 0,
    SpecRuleLayer.PLATFORM_ENGINEERING: 1,
    SpecRuleLayer.PROJECT: 2,
    SpecRuleLayer.TASK: 3,
}


def _rule_sort_key(rule: SpecRule) -> tuple[int, int, str, tuple[RuleScope, ...], SpecRuleId]:
    return (rule.priority, _LAYER_RANK[rule.layer], rule.field, rule.scopes, rule.id)


def _baseline_digest(baseline: ProjectSpecBaseline) -> Sha256:
    payload = baseline.model_dump(mode="json", exclude={"baseline_sha256"})
    return _sha256(_canonical_json(payload))


def _conflict_digest(conflict: ProjectSpecConflict) -> Sha256:
    payload = conflict.model_dump(
        mode="json",
        exclude={"id", "detected_at", "conflict_sha256"},
    )
    return _sha256(_canonical_json(payload))


def _compilation_digest(compilation: ProjectBaselineCompilation) -> Sha256:
    payload = compilation.model_dump(
        mode="json",
        exclude={"compiled_at", "compilation_sha256"},
    )
    conflicts = payload.get("conflicts")
    if isinstance(conflicts, list):
        for conflict in conflicts:
            if isinstance(conflict, dict):
                conflict.pop("detected_at", None)
    return _sha256(_canonical_json(payload))


def _seal_compilation(
    compilation: ProjectBaselineCompilation,
) -> ProjectBaselineCompilation:
    sealed = compilation.model_copy(update={"compilation_sha256": _compilation_digest(compilation)})
    sealed.validate_integrity()
    return sealed


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: str) -> Sha256:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _atomic_json_write(path: Path, payload: WirePayload) -> bool:
    """Publish without clobbering a concurrent first record."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(_canonical_json(payload))
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return False
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True
    except OSError as error:
        raise ProjectBaselineRecordStoreError(
            f"cannot persist project-baseline record: {path.name}"
        ) from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


__all__ = [
    "FileProjectBaselineCompilationStore",
    "ProjectBaselineCompilation",
    "ProjectBaselineCompilationStatus",
    "ProjectBaselineCompiler",
    "ProjectBaselineCompilerError",
    "ProjectBaselineIntegrityError",
    "ProjectBaselineRecordConflict",
    "ProjectBaselineRecordCorruption",
    "ProjectBaselineRecordNotFound",
    "ProjectBaselineRecordStoreError",
    "ProjectSpecBaseline",
    "ProjectSpecConflict",
    "ProjectSpecConflictId",
    "ProjectWaitingHumanRoute",
    "TaskScopedRuleRejected",
]
