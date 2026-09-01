"""Deterministic compilation and human governance of structured engineering rules.

Opaque project documents remain declared Context sources; this module does not pretend to
understand arbitrary Markdown. Adapters may emit structured ``SpecRule`` values for facts they
can prove, and every project rule is checked against a URI/hash from ``ProjectProfile``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Sequence
from contextlib import suppress
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self, cast

from pydantic import (
    AwareDatetime,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ai_software_engineer.context.models import ContextSource
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import (
    DomainModel,
    JsonValue,
    NonEmptyStr,
    WirePayload,
    ensure_unique,
)
from ai_software_engineer.domain.task import AcceptanceCriterionId, Task, TaskId
from ai_software_engineer.project_profile import ProjectProfile, Sha256

SpecRuleId = Annotated[str, StringConstraints(pattern=r"^rule_[a-z0-9][a-z0-9_-]{2,63}$")]
SpecConflictId = Annotated[str, StringConstraints(pattern=r"^spec_conflict_[a-f0-9]{64}$")]
SpecResolutionId = Annotated[str, StringConstraints(pattern=r"^spec_resolution_[a-f0-9]{64}$")]
RulePriority = Annotated[StrictInt, Field(ge=1, le=10_000)]
RuleField = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")]
RuleScope = Annotated[str, StringConstraints(pattern=r"^(\*|[a-z][a-z0-9_.:-]{0,127})$")]


class SpecCompilerError(RuntimeError):
    """Base error for invalid or unsafe spec compilation."""


class SpecSourceMismatch(SpecCompilerError):
    """Raised when a structured project rule is not backed by ProjectProfile."""


class HardPolicyMissing(SpecCompilerError):
    """Raised when compilation has no organization hard-safety rule."""


class SpecResolutionRejected(SpecCompilerError):
    """Raised when a human resolution cannot safely resolve its conflict."""


class SpecRecordStoreError(RuntimeError):
    """Base error for the append-only spec conflict/resolution store."""


class SpecRecordConflict(SpecRecordStoreError):
    """Raised when an immutable record identity is reused with different content."""


class SpecRecordCorruption(SpecRecordStoreError):
    """Raised when a persisted record is malformed or has an invalid digest."""


class SpecRecordNotFound(SpecRecordStoreError):
    """Raised when a requested spec record does not exist."""


class SpecRuleLayer(StrEnum):
    """Governance layer that authored a structured rule."""

    PLATFORM_HARD = "platform_hard"
    PLATFORM_ENGINEERING = "platform_engineering"
    PROJECT = "project"
    TASK = "task"


class SpecConflictClass(StrEnum):
    """Whether a conflict touches an immutable safety boundary."""

    HARD_SAFETY = "HARD_SAFETY"
    ENGINEERING = "ENGINEERING"


class SpecCompilationStatus(StrEnum):
    """Outcome of one pure compilation attempt."""

    COMPILED = "COMPILED"
    CONFLICT = "CONFLICT"


class SpecResolutionAction(StrEnum):
    """Explicit human actions; only two actions select an effective rule."""

    SELECT_RULE = "SELECT_RULE"
    KEEP_HARD_POLICY = "KEEP_HARD_POLICY"
    UPDATE_LOWER_RULE = "UPDATE_LOWER_RULE"
    TERMINATE_DELIVERY = "TERMINATE_DELIVERY"


class SpecRule(DomainModel):
    """One structured rule with provenance and an explicit applicability scope."""

    kind: Literal["spec_rule"] = "spec_rule"
    id: SpecRuleId
    field: RuleField
    value: JsonValue
    layer: SpecRuleLayer
    priority: RulePriority
    scopes: Annotated[tuple[RuleScope, ...], Field(min_length=1)] = ("*",)
    source_uri: NonEmptyStr
    source_sha256: Sha256
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        ensure_unique(self.scopes, "SpecRule scopes")
        if self.layer in {
            SpecRuleLayer.PLATFORM_HARD,
            SpecRuleLayer.PLATFORM_ENGINEERING,
        } and not self.source_uri.startswith("platform://"):
            raise ValueError("platform rule source_uri must use platform://")
        if self.layer is SpecRuleLayer.PROJECT and not self.source_uri.startswith("project://"):
            raise ValueError("project rule source_uri must use project://")
        if self.layer is SpecRuleLayer.TASK and not self.source_uri.startswith("task://"):
            raise ValueError("task rule source_uri must use task://")
        _canonical_json(self.value)
        return self


class SpecSourceRef(DomainModel):
    """Opaque project-native source retained without claiming semantic interpretation."""

    uri: NonEmptyStr
    sha256: Sha256


class SpecConflict(DomainModel):
    """Immutable conflict fact containing every participating rule and its provenance."""

    kind: Literal["SPEC_CONFLICT"] = "SPEC_CONFLICT"
    schema_version: Literal["v0.1"] = "v0.1"
    id: SpecConflictId
    project_id: ProjectId
    task_id: TaskId
    field: RuleField
    classification: SpecConflictClass
    rules: Annotated[tuple[SpecRule, ...], Field(min_length=2)]
    reason: NonEmptyStr
    human_question: NonEmptyStr
    affected_criteria: tuple[AcceptanceCriterionId, ...]
    recovery_conditions: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    detected_at: AwareDatetime
    conflict_sha256: Sha256

    @model_validator(mode="after")
    def validate_conflict(self) -> Self:
        ensure_unique((rule.id for rule in self.rules), "SpecConflict rule IDs")
        ensure_unique(self.affected_criteria, "SpecConflict affected criteria")
        ensure_unique(self.recovery_conditions, "SpecConflict recovery conditions")
        if any(rule.field != self.field for rule in self.rules):
            raise ValueError("SpecConflict rules must share the conflict field")
        expected_class = (
            SpecConflictClass.HARD_SAFETY
            if any(rule.layer is SpecRuleLayer.PLATFORM_HARD for rule in self.rules)
            else SpecConflictClass.ENGINEERING
        )
        if self.classification is not expected_class:
            raise ValueError("SpecConflict classification does not match its rules")
        if len(_conflicting_participants(self.rules)) < 2:
            raise ValueError("SpecConflict requires overlapping rules with different values")
        return self

    def validate_integrity(self) -> None:
        """Reject a conflict whose durable content no longer matches its identity."""
        expected = _conflict_digest(self)
        if self.conflict_sha256 != expected or self.id != f"spec_conflict_{expected}":
            raise SpecRecordCorruption(f"SpecConflict identity does not match content: {self.id}")


class WaitingHumanRoute(DomainModel):
    """Routing instruction for an upper layer; it performs no state or Lease mutation."""

    kind: Literal["spec_waiting_human_route"] = "spec_waiting_human_route"
    work_item_status: Literal["WAITING_HUMAN"] = "WAITING_HUMAN"
    reason: Literal["SPEC_CONFLICT"] = "SPEC_CONFLICT"
    conflict_ids: Annotated[tuple[SpecConflictId, ...], Field(min_length=1)]
    release_lease: StrictBool = True
    preserve_task_checkpoint: StrictBool = True
    recovery_conditions: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_route(self) -> Self:
        ensure_unique(self.conflict_ids, "WaitingHumanRoute conflict IDs")
        ensure_unique(self.recovery_conditions, "WaitingHumanRoute recovery conditions")
        if not self.release_lease or not self.preserve_task_checkpoint:
            raise ValueError(
                "spec conflict routing must release Lease and preserve Task checkpoint"
            )
        return self


class SpecResolution(DomainModel):
    """Human-authored, evidence-backed resolution of one exact conflict version."""

    kind: Literal["SPEC_RESOLUTION"] = "SPEC_RESOLUTION"
    schema_version: Literal["v0.1"] = "v0.1"
    id: SpecResolutionId
    conflict_id: SpecConflictId
    conflict_sha256: Sha256
    project_id: ProjectId
    task_id: TaskId
    action: SpecResolutionAction
    selected_rule_id: SpecRuleId | None = None
    operator_id: NonEmptyStr
    rationale: NonEmptyStr
    evidence_uris: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    resolved_at: AwareDatetime
    resolution_sha256: Sha256

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        ensure_unique(self.evidence_uris, "SpecResolution evidence URIs")
        selection_actions = {
            SpecResolutionAction.SELECT_RULE,
            SpecResolutionAction.KEEP_HARD_POLICY,
        }
        if (self.action in selection_actions) != (self.selected_rule_id is not None):
            raise ValueError("selected_rule_id is required exactly for rule-selection actions")
        return self

    @classmethod
    def create(
        cls,
        conflict: SpecConflict,
        *,
        action: SpecResolutionAction,
        operator_id: str,
        rationale: str,
        evidence_uris: tuple[str, ...],
        resolved_at: datetime,
        selected_rule_id: SpecRuleId | None = None,
    ) -> SpecResolution:
        """Create and validate a replay-stable human resolution record."""
        seed = {
            "conflict_id": conflict.id,
            "conflict_sha256": conflict.conflict_sha256,
            "action": action.value,
            "selected_rule_id": selected_rule_id,
            "operator_id": operator_id,
            "rationale": rationale,
            "evidence_uris": list(evidence_uris),
        }
        record_id = f"spec_resolution_{_sha256(_canonical_json(seed))}"
        provisional = cls(
            id=record_id,
            conflict_id=conflict.id,
            conflict_sha256=conflict.conflict_sha256,
            project_id=conflict.project_id,
            task_id=conflict.task_id,
            action=action,
            selected_rule_id=selected_rule_id,
            operator_id=operator_id,
            rationale=rationale,
            evidence_uris=evidence_uris,
            resolved_at=resolved_at,
            resolution_sha256="0" * 64,
        )
        record = provisional.model_copy(
            update={"resolution_sha256": _resolution_digest(provisional)}
        )
        validate_resolution(conflict, record)
        return record

    def validate_integrity(self) -> None:
        """Reject a resolution whose durable content no longer matches its identity."""
        expected = _resolution_digest(self)
        expected_id = f"spec_resolution_{_resolution_identity_digest(self)}"
        if self.resolution_sha256 != expected or self.id != expected_id:
            raise SpecRecordCorruption(f"SpecResolution identity does not match content: {self.id}")


class CompiledSpec(DomainModel):
    """Conflict-free, deterministic rule set safe to inject into Context Builder."""

    kind: Literal["compiled_spec"] = "compiled_spec"
    schema_version: Literal["v0.1"] = "v0.1"
    project_id: ProjectId
    task_id: TaskId
    rules: Annotated[tuple[SpecRule, ...], Field(min_length=1)]
    opaque_project_sources: tuple[SpecSourceRef, ...] = ()
    resolution_ids: tuple[SpecResolutionId, ...] = ()
    compiled_sha256: Sha256

    @model_validator(mode="after")
    def validate_compiled(self) -> Self:
        ensure_unique((rule.id for rule in self.rules), "CompiledSpec rule IDs")
        ensure_unique(
            (source.uri for source in self.opaque_project_sources),
            "CompiledSpec opaque source URIs",
        )
        ensure_unique(self.resolution_ids, "CompiledSpec resolution IDs")
        return self

    def validate_integrity(self) -> None:
        """Reject a compiled spec whose identity hash no longer matches its rules."""
        if self.compiled_sha256 != _compiled_digest(self):
            raise SpecRecordCorruption("CompiledSpec digest does not match content")

    def to_context_source(self) -> ContextSource:
        """Expose the compiled contract as one required, deterministic Context source."""
        self.validate_integrity()
        return ContextSource(
            source_id="compiled.spec",
            uri=f"spec://{self.project_id}/{self.task_id}/{self.compiled_sha256}",
            content=_canonical_json(self.to_wire()),
            priority=10,
            required=True,
        )


class SpecCompilation(DomainModel):
    """Exclusive compiled-or-conflict result returned by ``SpecCompiler``."""

    kind: Literal["spec_compilation"] = "spec_compilation"
    status: SpecCompilationStatus
    project_id: ProjectId
    task_id: TaskId
    compiled_spec: CompiledSpec | None = None
    conflicts: tuple[SpecConflict, ...] = ()
    route: WaitingHumanRoute | None = None
    compiled_at: AwareDatetime
    compilation_sha256: Sha256

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status is SpecCompilationStatus.COMPILED:
            if self.compiled_spec is None or self.conflicts or self.route is not None:
                raise ValueError("COMPILED result requires only compiled_spec")
            if (
                self.compiled_spec.project_id != self.project_id
                or self.compiled_spec.task_id != self.task_id
            ):
                raise ValueError("compiled_spec does not match compilation project/Task")
        elif self.compiled_spec is not None or not self.conflicts or self.route is None:
            raise ValueError("CONFLICT result requires conflicts and WAITING_HUMAN route")
        else:
            if any(
                conflict.project_id != self.project_id or conflict.task_id != self.task_id
                for conflict in self.conflicts
            ):
                raise ValueError("conflict does not match compilation project/Task")
            if self.route.conflict_ids != tuple(conflict.id for conflict in self.conflicts):
                raise ValueError("route conflict_ids must match compilation conflicts")
        return self

    def validate_integrity(self) -> None:
        """Reject a compilation whose stable digest no longer matches its outcome."""
        payload = self.model_dump(
            mode="json",
            exclude={"compiled_at", "compilation_sha256"},
        )
        if self.compilation_sha256 != _sha256(_canonical_json(payload)):
            raise SpecRecordCorruption("SpecCompilation digest does not match content")


class SpecCompiler:
    """Pure compiler for platform, project, and Task rule facts."""

    def compile(
        self,
        profile: ProjectProfile,
        task: Task,
        rules: Sequence[SpecRule],
        *,
        compiled_at: datetime,
        resolutions: Sequence[SpecResolution] = (),
    ) -> SpecCompilation:
        """Compile rules, returning a conflict route instead of guessing precedence."""
        _require_aware(compiled_at, "compiled_at")
        profile.validate_integrity()
        all_rules = (*rules, *_task_constraint_rules(task))
        if not any(rule.layer is SpecRuleLayer.PLATFORM_HARD for rule in all_rules):
            raise HardPolicyMissing("at least one PLATFORM_HARD rule is required")
        ensure_unique((rule.id for rule in all_rules), "SpecRule IDs")
        self._validate_rule_sources(profile, task, all_rules)
        ordered = tuple(sorted(all_rules, key=_rule_sort_key))
        conflicts = self._detect_conflicts(profile.project_id, task, ordered, compiled_at)
        ensure_unique(
            (resolution.conflict_id for resolution in resolutions),
            "SpecResolution conflict IDs",
        )
        resolutions_by_conflict = {resolution.conflict_id: resolution for resolution in resolutions}
        unknown = set(resolutions_by_conflict) - {conflict.id for conflict in conflicts}
        if unknown:
            raise SpecResolutionRejected(
                "resolution references a conflict absent from this compilation: "
                + ", ".join(sorted(unknown))
            )

        dropped_rule_ids: set[SpecRuleId] = set()
        unresolved: list[SpecConflict] = []
        applied_resolution_ids: list[SpecResolutionId] = []
        for conflict in conflicts:
            resolution = resolutions_by_conflict.get(conflict.id)
            if resolution is None:
                unresolved.append(conflict)
                continue
            validate_resolution(conflict, resolution)
            if resolution.action in {
                SpecResolutionAction.SELECT_RULE,
                SpecResolutionAction.KEEP_HARD_POLICY,
            }:
                assert resolution.selected_rule_id is not None
                selected = next(
                    rule for rule in conflict.rules if rule.id == resolution.selected_rule_id
                )
                selected_value = _canonical_json(selected.value)
                dropped_rule_ids.update(
                    rule.id
                    for rule in conflict.rules
                    if _canonical_json(rule.value) != selected_value
                )
                applied_resolution_ids.append(resolution.id)
            else:
                unresolved.append(conflict)

        if unresolved:
            route = WaitingHumanRoute(
                conflict_ids=tuple(conflict.id for conflict in unresolved),
                recovery_conditions=(
                    "record evidence-backed human resolution",
                    "recompile the exact rule sources",
                ),
            )
            return _seal_compilation(
                SpecCompilation(
                    status=SpecCompilationStatus.CONFLICT,
                    project_id=profile.project_id,
                    task_id=task.id,
                    conflicts=tuple(unresolved),
                    route=route,
                    compiled_at=compiled_at,
                    compilation_sha256="0" * 64,
                )
            )

        effective = tuple(rule for rule in ordered if rule.id not in dropped_rule_ids)
        opaque_sources = tuple(
            SpecSourceRef(uri=source.uri, sha256=source.sha256) for source in profile.native_rules
        )
        provisional = CompiledSpec(
            project_id=profile.project_id,
            task_id=task.id,
            rules=effective,
            opaque_project_sources=opaque_sources,
            resolution_ids=tuple(sorted(applied_resolution_ids)),
            compiled_sha256="0" * 64,
        )
        compiled = provisional.model_copy(update={"compiled_sha256": _compiled_digest(provisional)})
        return _seal_compilation(
            SpecCompilation(
                status=SpecCompilationStatus.COMPILED,
                project_id=profile.project_id,
                task_id=task.id,
                compiled_spec=compiled,
                compiled_at=compiled_at,
                compilation_sha256="0" * 64,
            )
        )

    @staticmethod
    def _validate_rule_sources(
        profile: ProjectProfile,
        task: Task,
        rules: Iterable[SpecRule],
    ) -> None:
        project_sources = {source.uri: source.sha256 for source in profile.native_rules}
        task_uri = f"task://{task.id}"
        task_source_sha = (
            _sha256(_canonical_json(task.constraints.to_wire()))
            if task.constraints is not None
            else None
        )
        for rule in rules:
            if rule.layer is SpecRuleLayer.PROJECT:
                if project_sources.get(rule.source_uri) != rule.source_sha256:
                    raise SpecSourceMismatch(
                        f"project rule source is absent or hash-mismatched: {rule.source_uri}"
                    )
            elif rule.layer is SpecRuleLayer.TASK and (
                rule.source_uri != task_uri or rule.source_sha256 != task_source_sha
            ):
                raise SpecSourceMismatch(
                    f"task rule must match {task_uri} and the exact TaskConstraints hash"
                )

    @staticmethod
    def _detect_conflicts(
        project_id: ProjectId,
        task: Task,
        rules: tuple[SpecRule, ...],
        detected_at: datetime,
    ) -> tuple[SpecConflict, ...]:
        by_field: dict[str, list[SpecRule]] = defaultdict(list)
        for rule in rules:
            by_field[rule.field].append(rule)
        conflicts: list[SpecConflict] = []
        for field, candidates in sorted(by_field.items()):
            participants = _conflicting_participants(candidates)
            if len(participants) < 2:
                continue
            affected = _affected_criteria(task, participants)
            classification = (
                SpecConflictClass.HARD_SAFETY
                if any(rule.layer is SpecRuleLayer.PLATFORM_HARD for rule in participants)
                else SpecConflictClass.ENGINEERING
            )
            provisional = SpecConflict(
                id=f"spec_conflict_{'0' * 64}",
                project_id=project_id,
                task_id=task.id,
                field=field,
                classification=classification,
                rules=participants,
                reason=f"Overlapping rules assign different values to {field}",
                human_question=(
                    f"Which source should govern {field}, or which lower rule should be updated?"
                ),
                affected_criteria=affected,
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
                    update={"id": f"spec_conflict_{digest}", "conflict_sha256": digest}
                )
            )
        return tuple(conflicts)


def validate_resolution(conflict: SpecConflict, resolution: SpecResolution) -> None:
    """Validate exact conflict binding and prevent hard-policy relaxation."""
    conflict.validate_integrity()
    resolution.validate_integrity()
    if (
        resolution.conflict_id != conflict.id
        or resolution.conflict_sha256 != conflict.conflict_sha256
        or resolution.project_id != conflict.project_id
        or resolution.task_id != conflict.task_id
    ):
        raise SpecResolutionRejected("resolution does not bind the exact conflict identity")
    rule_by_id = {rule.id: rule for rule in conflict.rules}
    selected = rule_by_id.get(resolution.selected_rule_id) if resolution.selected_rule_id else None
    if resolution.selected_rule_id is not None and selected is None:
        raise SpecResolutionRejected("selected_rule_id is not part of the conflict")
    if conflict.classification is SpecConflictClass.HARD_SAFETY:
        if resolution.action is SpecResolutionAction.SELECT_RULE:
            raise SpecResolutionRejected("hard safety cannot be resolved by selecting a lower rule")
        if resolution.action is SpecResolutionAction.KEEP_HARD_POLICY and (
            selected is None or selected.layer is not SpecRuleLayer.PLATFORM_HARD
        ):
            raise SpecResolutionRejected("KEEP_HARD_POLICY must select a PLATFORM_HARD rule")
    elif resolution.action is SpecResolutionAction.KEEP_HARD_POLICY:
        raise SpecResolutionRejected("KEEP_HARD_POLICY requires a hard-safety conflict")


class FileSpecRecordStore:
    """Atomic, append-only store rooted at a project's ``spec-conflicts`` directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve(strict=False)
        self._conflicts = self._root / "conflicts"
        self._resolutions = self._root / "resolutions"
        self._conflicts.mkdir(parents=True, exist_ok=True)
        self._resolutions.mkdir(parents=True, exist_ok=True)

    def put_conflict(self, conflict: SpecConflict) -> SpecConflict:
        conflict.validate_integrity()
        return self._put(conflict, self._conflicts / f"{conflict.id}.json", SpecConflict)

    def get_conflict(self, conflict_id: SpecConflictId) -> SpecConflict:
        validated = TypeAdapter(SpecConflictId).validate_python(conflict_id)
        return self._get(self._conflicts / f"{validated}.json", SpecConflict)

    def put_resolution(self, resolution: SpecResolution) -> SpecResolution:
        resolution.validate_integrity()
        path = self._resolutions / f"{resolution.conflict_id}.json"
        return self._put(resolution, path, SpecResolution)

    def get_resolution(self, conflict_id: SpecConflictId) -> SpecResolution:
        validated = TypeAdapter(SpecConflictId).validate_python(conflict_id)
        return self._get(self._resolutions / f"{validated}.json", SpecResolution)

    @staticmethod
    def _put[RecordT: SpecConflict | SpecResolution](
        record: RecordT,
        path: Path,
        model_type: type[RecordT],
    ) -> RecordT:
        if path.exists():
            existing = FileSpecRecordStore._get(path, model_type)
            if _record_identity(existing) != _record_identity(record):
                raise SpecRecordConflict(
                    f"spec record already exists with different content: {path.name}"
                )
            return existing
        _atomic_json_write(path, record.to_wire())
        return record

    @staticmethod
    def _get[RecordT: SpecConflict | SpecResolution](
        path: Path,
        model_type: type[RecordT],
    ) -> RecordT:
        if not path.is_file():
            raise SpecRecordNotFound(path.name)
        try:
            record = model_type.model_validate(json.loads(path.read_text(encoding="utf-8")))
            record.validate_integrity()
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            raise SpecRecordCorruption(f"spec record is invalid: {path.name}") from error
        return cast(RecordT, record)


def _task_constraint_rules(task: Task) -> tuple[SpecRule, ...]:
    if task.constraints is None:
        return ()
    values: tuple[tuple[str, JsonValue], ...] = (
        ("task.allowed_paths", list(task.constraints.allowed_paths)),
        ("task.denied_paths", list(task.constraints.denied_paths)),
        ("task.allowed_commands", list(task.constraints.allowed_commands)),
        ("task.max_attempts", task.constraints.max_attempts),
        ("task.notes", task.constraints.notes),
    )
    source_uri = f"task://{task.id}"
    source_sha = _sha256(_canonical_json(task.constraints.to_wire()))
    rules: list[SpecRule] = []
    for field, value in values:
        if value in (None, [], ""):
            continue
        rule_id = _stable_rule_id(task.id, field, value)
        rules.append(
            SpecRule(
                id=rule_id,
                field=field,
                value=value,
                layer=SpecRuleLayer.TASK,
                priority=400,
                source_uri=source_uri,
                source_sha256=source_sha,
                rationale="Explicit Task constraint",
            )
        )
    return tuple(rules)


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


def _affected_criteria(
    task: Task,
    rules: tuple[SpecRule, ...],
) -> tuple[AcceptanceCriterionId, ...]:
    known = {criterion.id for criterion in task.acceptance_criteria}
    scoped = {
        scope.removeprefix("criterion:")
        for rule in rules
        for scope in rule.scopes
        if scope.startswith("criterion:")
    }
    selected = known & scoped
    if selected:
        return tuple(sorted(selected))
    return tuple(criterion.id for criterion in task.acceptance_criteria if criterion.required)


_LAYER_RANK = {
    SpecRuleLayer.PLATFORM_HARD: 0,
    SpecRuleLayer.PLATFORM_ENGINEERING: 1,
    SpecRuleLayer.PROJECT: 2,
    SpecRuleLayer.TASK: 3,
}


def _rule_sort_key(rule: SpecRule) -> tuple[int, int, str, tuple[RuleScope, ...], SpecRuleId]:
    return (rule.priority, _LAYER_RANK[rule.layer], rule.field, rule.scopes, rule.id)


def _stable_rule_id(task_id: TaskId, field: str, value: JsonValue) -> SpecRuleId:
    digest = _sha256(_canonical_json({"task_id": task_id, "field": field, "value": value}))
    return f"rule_{digest[:24]}"


def _conflict_digest(conflict: SpecConflict) -> Sha256:
    payload = conflict.model_dump(
        mode="json",
        exclude={"id", "detected_at", "conflict_sha256"},
    )
    return _sha256(_canonical_json(payload))


def _resolution_digest(resolution: SpecResolution) -> Sha256:
    payload = resolution.model_dump(
        mode="json",
        exclude={"resolved_at", "resolution_sha256"},
    )
    return _sha256(_canonical_json(payload))


def _resolution_identity_digest(resolution: SpecResolution) -> Sha256:
    payload = resolution.model_dump(
        mode="json",
        include={
            "conflict_id",
            "conflict_sha256",
            "action",
            "selected_rule_id",
            "operator_id",
            "rationale",
            "evidence_uris",
        },
    )
    return _sha256(_canonical_json(payload))


def _compiled_digest(compiled: CompiledSpec) -> Sha256:
    payload = compiled.model_dump(mode="json", exclude={"compiled_sha256"})
    return _sha256(_canonical_json(payload))


def _seal_compilation(compilation: SpecCompilation) -> SpecCompilation:
    payload = compilation.model_dump(mode="json", exclude={"compiled_at", "compilation_sha256"})
    sealed = compilation.model_copy(
        update={"compilation_sha256": _sha256(_canonical_json(payload))}
    )
    sealed.validate_integrity()
    return sealed


def _record_identity(record: SpecConflict | SpecResolution) -> dict[str, object]:
    excluded = {"detected_at"} if isinstance(record, SpecConflict) else {"resolved_at"}
    return record.model_dump(mode="python", exclude=excluded)


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


def _atomic_json_write(path: Path, payload: WirePayload) -> None:
    encoded = _canonical_json(payload).encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as error:
        raise SpecRecordStoreError(f"cannot persist spec record: {path.name}") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


__all__ = [
    "CompiledSpec",
    "FileSpecRecordStore",
    "HardPolicyMissing",
    "SpecCompilation",
    "SpecCompilationStatus",
    "SpecCompiler",
    "SpecCompilerError",
    "SpecConflict",
    "SpecConflictClass",
    "SpecConflictId",
    "SpecRecordConflict",
    "SpecRecordCorruption",
    "SpecRecordNotFound",
    "SpecRecordStoreError",
    "SpecResolution",
    "SpecResolutionAction",
    "SpecResolutionId",
    "SpecResolutionRejected",
    "SpecRule",
    "SpecRuleId",
    "SpecRuleLayer",
    "SpecSourceMismatch",
    "SpecSourceRef",
    "WaitingHumanRoute",
    "validate_resolution",
]
