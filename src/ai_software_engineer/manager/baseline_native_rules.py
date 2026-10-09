"""Seal full Git-native rule epochs, keeping large bodies out of public Operations."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.execution_native_rules import (
    NativeRuleChangePlan,
    NativeRuleEpoch,
    NativeRuleEpochBody,
)
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_profile import NativeRuleSource
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer

NATIVE_RULE_EPOCH_NAMESPACE = "baseline-native-rules"


def load_native_rule_epoch(records: KnowledgeRecordStore, sha256: str) -> NativeRuleEpoch:
    """20 MB secure store budget exceeds the epoch's 16 MiB serialized byte limit."""
    epoch = records.get(NATIVE_RULE_EPOCH_NAMESPACE, sha256, NativeRuleEpoch)
    epoch.validate_integrity()
    if epoch.epoch_sha256 != sha256:
        raise ValueError("完整原生规范版本与绑定的摘要不一致")
    return epoch


def active_native_rule_epoch(
    records: KnowledgeRecordStore, bindings: Sequence[ExecutionBaselineBinding]
) -> NativeRuleEpoch | None:
    selected = next(
        (binding for binding in reversed(bindings) if binding.native_rule_epoch_sha256 is not None),
        None,
    )
    if selected is None or selected.native_rule_epoch_sha256 is None:
        return None
    epoch = load_native_rule_epoch(records, selected.native_rule_epoch_sha256)
    if (epoch.scope, epoch.task_id) != (selected.scope, selected.task_id):
        raise ValueError("原生规范版本不属于当前需求和执行工作空间")
    return epoch


def build_native_rule_change(
    *,
    git: GitWorktreeManager,
    records: KnowledgeRecordStore,
    scope: EngineeringScope,
    task_id: str,
    source_revision: str,
    target_base_ref: str,
    source_rules: tuple[NativeRuleSource, ...],
    target_rules: tuple[NativeRuleSource, ...],
    structured_project_rules: tuple[SpecRule, ...] = (),
) -> NativeRuleChangePlan | None:
    """Trusted collector-only input; no caller supplied rule body or approval flag."""
    source_rules = tuple(sorted(source_rules, key=lambda rule: rule.relative_path))
    target_rules = tuple(sorted(target_rules, key=lambda rule: rule.relative_path))
    if source_rules == target_rules:
        return None
    if (
        git._resolve_revision(target_base_ref) != target_base_ref
        or git._resolve_revision(source_revision) != source_revision
    ):
        raise ValueError("规范更新必须使用精确、不可变的完整 Git 提交")
    targets = {rule.uri: rule for rule in target_rules}
    native_source_uris = {rule.uri for rule in source_rules}
    for rule in structured_project_rules:
        if (rule.layer is SpecRuleLayer.PROJECT and rule.source_uri in native_source_uris) and (
            rule.source_uri not in targets or targets[rule.source_uri].sha256 != rule.source_sha256
        ):
            raise ValueError(
                "目标代码改变了显式结构化项目规范的来源, 需先重新编译并确认该规范; "
                "不能只替换原规则摘要"
            )
    # Re-enumeration verifies additions/deletions and regular-file modes. This
    # helper never discovers a mutable checkout or permits a omitted target rule.
    from ai_software_engineer.manager.baseline_production import native_rules_at_revision

    if (
        native_rules_at_revision(git, repository_id=scope.repository_id, revision=target_base_ref)
        != target_rules
    ):
        raise ValueError("目标原生规范清单与不可变 Git 版本不一致")
    if (
        native_rules_at_revision(git, repository_id=scope.repository_id, revision=source_revision)
        != source_rules
    ):
        raise ValueError("原原生规范清单与当前不可变执行版本不一致")

    def freeze_bodies(
        revision: str, rules: tuple[NativeRuleSource, ...]
    ) -> tuple[NativeRuleEpochBody, ...]:
        bodies = []
        for source in rules:
            object_name = f"{revision}:{source.relative_path}"
            raw = git._run_git_bytes(("cat-file", "blob", object_name), cwd=git._repository)
            if len(raw) != source.byte_length or hashlib.sha256(raw).hexdigest() != source.sha256:
                raise ValueError("原生规范正文与完整 Git 清单不一致")
            content = redact_text(raw.decode("utf-8")).text
            rendered = content.encode("utf-8")
            bodies.append(
                NativeRuleEpochBody(
                    source=source,
                    content=content,
                    content_sha256=hashlib.sha256(rendered).hexdigest(),
                    content_bytes=len(rendered),
                )
            )
        return tuple(bodies)

    epoch = NativeRuleEpoch.create(
        scope=scope,
        task_id=task_id,
        source_revision=source_revision,
        target_base_ref=target_base_ref,
        source_rules=source_rules,
        before_bodies=freeze_bodies(source_revision, source_rules),
        bodies=freeze_bodies(target_base_ref, target_rules),
    )
    change = NativeRuleChangePlan.for_epoch(epoch)
    records.put(NATIVE_RULE_EPOCH_NAMESPACE, epoch.epoch_sha256, epoch)
    change.require_epoch(load_native_rule_epoch(records, epoch.epoch_sha256))
    return change
