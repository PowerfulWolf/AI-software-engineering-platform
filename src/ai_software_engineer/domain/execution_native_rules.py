"""Immutable exact project-rule inputs approved independently of Product scope."""

from __future__ import annotations

import hashlib
import json
from difflib import unified_diff
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.execution_baseline import FullGitRevision
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_profile import NativeRuleSource

MAX_NATIVE_RULE_EPOCH_BYTES = 16 * 1024 * 1024
MAX_NATIVE_RULE_SOURCES = 5000
MAX_NATIVE_RULE_SOURCE_BYTES = 1_000_000
MAX_NATIVE_RULE_RAW_TOTAL_BYTES = 8_000_000


def _wire_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def native_rules_sha256(rules: tuple[NativeRuleSource, ...]) -> str:
    return hashlib.sha256(_wire_bytes([rule.to_wire() for rule in rules])).hexdigest()


class NativeRuleDelta(DomainModel):
    path: NonEmptyStr
    change: Literal["added", "modified", "deleted"]
    before: NativeRuleSource | None = None
    after: NativeRuleSource | None = None

    @model_validator(mode="after")
    def exact_delta(self) -> Self:
        expected = (
            "added"
            if self.before is None and self.after is not None
            else "deleted"
            if self.before is not None and self.after is None
            else "modified"
            if self.before is not None and self.after is not None and self.before != self.after
            else None
        )
        if expected != self.change or any(
            rule.relative_path != self.path
            for rule in (self.before, self.after)
            if rule is not None
        ):
            raise ValueError("原生规范变更必须绑定精确路径和增改删事实")
        return self


def native_rule_delta(
    source: tuple[NativeRuleSource, ...], target: tuple[NativeRuleSource, ...]
) -> tuple[NativeRuleDelta, ...]:
    before = {rule.relative_path: rule for rule in source}
    after = {rule.relative_path: rule for rule in target}
    return tuple(
        NativeRuleDelta(
            path=path,
            change="added"
            if path not in before
            else "deleted"
            if path not in after
            else "modified",
            before=before.get(path),
            after=after.get(path),
        )
        for path in sorted(before.keys() | after.keys())
        if before.get(path) != after.get(path)
    )


class NativeRuleEpochBody(DomainModel):
    source: NativeRuleSource
    content: str
    content_sha256: Sha256
    content_bytes: Annotated[StrictInt, Field(ge=0, le=MAX_NATIVE_RULE_EPOCH_BYTES)]

    @model_validator(mode="after")
    def bounded_redacted_body(self) -> Self:
        data = self.content.encode("utf-8")
        if (
            len(data) != self.content_bytes
            or hashlib.sha256(data).hexdigest() != self.content_sha256
            or redact_text(self.content).text != self.content
            or self.source.byte_length > MAX_NATIVE_RULE_SOURCE_BYTES
        ):
            raise ValueError("原生规范正文必须完整、脱敏并匹配内容摘要")
        return self


class NativeRuleEpochReference(DomainModel):
    scope: EngineeringScope
    task_id: TaskId
    target_base_ref: FullGitRevision
    rules_sha256: Sha256
    epoch_sha256: Sha256


def _native_unified_diff(
    *,
    path: str,
    source_revision: str,
    target_revision: str,
    before: NativeRuleEpochBody | None,
    after: NativeRuleEpochBody | None,
) -> str:
    lines = unified_diff(
        (before.content if before else "").splitlines(keepends=True),
        (after.content if after else "").splitlines(keepends=True),
        fromfile=f"{source_revision}/{path}" if before else "/dev/null",
        tofile=f"{target_revision}/{path}" if after else "/dev/null",
    )
    return "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines
    )


class NativeRuleChangeInspection(DomainModel):
    epoch: NativeRuleEpochReference
    source_revision: FullGitRevision
    delta: NativeRuleDelta
    before_body: NativeRuleEpochBody | None = None
    after_body: NativeRuleEpochBody | None = None
    unified_diff: str

    @model_validator(mode="after")
    def exact_bodies(self) -> Self:
        if (
            (self.before_body.source if self.before_body else None) != self.delta.before
            or (self.after_body.source if self.after_body else None) != self.delta.after
            or self.unified_diff
            != _native_unified_diff(
                path=self.delta.path,
                source_revision=self.source_revision,
                target_revision=self.epoch.target_base_ref,
                before=self.before_body,
                after=self.after_body,
            )
            or len(_wire_bytes(self.to_wire())) > MAX_NATIVE_RULE_EPOCH_BYTES
        ):
            raise ValueError("规范差异正文未完整匹配封存来源或超过展示字节预算")
        return self


class NativeRuleEpoch(DomainModel):
    kind: Literal["execution_native_rule_epoch"] = "execution_native_rule_epoch"
    schema_version: Literal["v1"] = "v1"
    scope: EngineeringScope
    task_id: TaskId
    source_revision: FullGitRevision
    target_base_ref: FullGitRevision
    source_rules: Annotated[tuple[NativeRuleSource, ...], Field(max_length=MAX_NATIVE_RULE_SOURCES)]
    before_bodies: Annotated[
        tuple[NativeRuleEpochBody, ...], Field(max_length=MAX_NATIVE_RULE_SOURCES)
    ]
    bodies: Annotated[tuple[NativeRuleEpochBody, ...], Field(max_length=MAX_NATIVE_RULE_SOURCES)]
    epoch_sha256: Sha256

    @property
    def rules(self) -> tuple[NativeRuleSource, ...]:
        return tuple(body.source for body in self.bodies)

    @property
    def reference(self) -> NativeRuleEpochReference:
        return NativeRuleEpochReference(
            scope=self.scope,
            task_id=self.task_id,
            target_base_ref=self.target_base_ref,
            rules_sha256=native_rules_sha256(self.rules),
            epoch_sha256=self.epoch_sha256,
        )

    @model_validator(mode="after")
    def complete_sources(self) -> Self:
        if tuple(body.source for body in self.before_bodies) != self.source_rules:
            raise ValueError("原生规范版本必须封存完整的原版本正文和来源")
        for rules in (self.source_rules, self.rules):
            ensure_unique((rule.relative_path for rule in rules), "原生规范路径")
            if tuple(sorted(rules, key=lambda rule: rule.relative_path)) != rules:
                raise ValueError("原生规范清单必须完整且稳定排序")
            if sum(rule.byte_length for rule in rules) > MAX_NATIVE_RULE_RAW_TOTAL_BYTES:
                raise ValueError("完整原生规范清单超过有界读取预算")
            for rule in rules:
                if (
                    rule.uri != f"project://{self.scope.repository_id}/{rule.relative_path}"
                    or rule.byte_length > MAX_NATIVE_RULE_SOURCE_BYTES
                ):
                    raise ValueError("原生规范来源不属于精确 Repository 或超过读取预算")
        return self

    def inspect_change(self, path: str) -> NativeRuleChangeInspection:
        self.validate_integrity()
        change = next(
            (
                value
                for value in native_rule_delta(self.source_rules, self.rules)
                if value.path == path
            ),
            None,
        )
        if change is None:
            raise ValueError("所选路径不是该批准方案封存的原生规范变更")
        before = next(
            (body for body in self.before_bodies if body.source.relative_path == path), None
        )
        after = next((body for body in self.bodies if body.source.relative_path == path), None)
        return NativeRuleChangeInspection(
            epoch=self.reference,
            source_revision=self.source_revision,
            delta=change,
            before_body=before,
            after_body=after,
            unified_diff=_native_unified_diff(
                path=path,
                source_revision=self.source_revision,
                target_revision=self.target_base_ref,
                before=before,
                after=after,
            ),
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if len(_wire_bytes(self.to_wire())) > MAX_NATIVE_RULE_EPOCH_BYTES:
            raise ValueError("完整原生规范版本超过持久化字节预算")
        payload = self.to_wire()
        payload.pop("epoch_sha256")
        if hashlib.sha256(_wire_bytes(payload)).hexdigest() != self.epoch_sha256:
            raise ValueError("原生规范版本内容摘要不一致")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "epoch_sha256": "0" * 64})
        payload = value.to_wire()
        payload.pop("epoch_sha256")
        value = value.model_copy(
            update={"epoch_sha256": hashlib.sha256(_wire_bytes(payload)).hexdigest()}
        )
        value.validate_integrity()
        return value


class NativeRuleChangePlan(DomainModel):
    source_native_rules_sha256: Sha256
    target_native_rules_sha256: Sha256
    target: NativeRuleEpochReference
    changes: Annotated[
        tuple[NativeRuleDelta, ...], Field(min_length=1, max_length=MAX_NATIVE_RULE_SOURCES)
    ]
    change_sha256: Sha256

    @model_validator(mode="after")
    def exact_target(self) -> Self:
        ensure_unique((change.path for change in self.changes), "原生规范变更路径")
        if (
            self.target.rules_sha256 != self.target_native_rules_sha256
            or self.source_native_rules_sha256 == self.target_native_rules_sha256
            or tuple(sorted(self.changes, key=lambda change: change.path)) != self.changes
        ):
            raise ValueError("规范批准方案必须绑定精确完整目标清单和稳定差异")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        payload = self.to_wire()
        payload.pop("change_sha256")
        if hashlib.sha256(_wire_bytes(payload)).hexdigest() != self.change_sha256:
            raise ValueError("原生规范批准方案摘要不一致")

    def require_epoch(self, epoch: NativeRuleEpoch) -> None:
        self.validate_integrity()
        epoch.validate_integrity()
        if (
            self.target != epoch.reference
            or self.source_native_rules_sha256 != native_rules_sha256(epoch.source_rules)
            or self.changes != native_rule_delta(epoch.source_rules, epoch.rules)
        ):
            raise ValueError("原生规范批准方案与完整封存正文不一致")

    @classmethod
    def for_epoch(cls, epoch: NativeRuleEpoch) -> Self:
        epoch.validate_integrity()
        value = cls(
            source_native_rules_sha256=native_rules_sha256(epoch.source_rules),
            target_native_rules_sha256=native_rules_sha256(epoch.rules),
            target=epoch.reference,
            changes=native_rule_delta(epoch.source_rules, epoch.rules),
            change_sha256="0" * 64,
        )
        payload = value.to_wire()
        payload.pop("change_sha256")
        return value.model_copy(
            update={"change_sha256": hashlib.sha256(_wire_bytes(payload)).hexdigest()}
        )
