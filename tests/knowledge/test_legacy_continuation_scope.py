"""A missing parent source must not strand or silently rebind a historical gap."""

from pathlib import Path

import pytest

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised
from ai_software_engineer.knowledge.models import KnowledgeError
from tests.knowledge.test_delivery_context import _builder
from tests.orchestration.test_runner import _definitions


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
@pytest.mark.parametrize("changed_rule", [False, True])
def test_legacy_snapshot_retained_when_previously_sealed_rule_is_materialized(
    tmp_path: Path, role: AgentRole, changed_rule: bool
) -> None:
    """Historical baselines had native references but omitted their readable bodies."""
    import json

    from ai_software_engineer.knowledge.models import KnowledgeSnapshot
    from ai_software_engineer.manager.baseline import ProjectBaselineCompiler
    from ai_software_engineer.orchestration.context import FileRunContextBuilder
    from ai_software_engineer.repository_profile import RepositoryProfile
    from tests.manager.test_baseline import NOW, hard_rule

    task, contexts, records, builder = _builder(tmp_path, enabled=False)
    task = task.model_copy(update={"id": "task_continue_legacy"})
    root = Path(task.repository)
    rule_text = "# Rules\nUse independent candidate verification.\n"
    (root / "AGENTS.md").write_text(rule_text)
    profile = RepositoryProfile.discover(root, repository_id=builder.repository_id)
    compilation = ProjectBaselineCompiler().compile(profile, (hard_rule(),), compiled_at=NOW)
    assert compilation.compiled_spec is not None
    baseline = compilation.compiled_spec
    baseline_source = ContextSource(
        source_id="project.baseline",
        uri=f"baseline://{builder.repository_id}/{baseline.baseline_sha256}",
        content=json.dumps(baseline.to_wire()),
        required=True,
    )
    builder.sources = (baseline_source,)
    builder.delegate = FileRunContextBuilder(
        task.repository, sources=builder.sources, context_store=contexts
    )
    definition = _definitions()[role]
    with pytest.raises(KnowledgeGapRaised) as original:
        builder.build(task, definition, attempt=1)
    gap = original.value.gap
    snapshot = records.get("snapshots", gap.binding.snapshot_sha256, KnowledgeSnapshot)
    assert snapshot.documents == ()
    rule = profile.native_rules[0]
    builder.sources = (
        baseline_source,
        ContextSource(
            source_id="joint.approved_context",
            uri="joint://delivery_multi_fixture/hash",
            content="Approved Requirement",
            required=True,
        ),
        ContextSource(
            source_id="native.rule.0",
            uri=rule.uri,
            content="Changed rule" if changed_rule else rule_text,
            required=True,
        ),
    )
    builder.delegate = FileRunContextBuilder(
        task.repository, sources=builder.sources, context_store=contexts
    )
    if changed_rule:
        with pytest.raises(KnowledgeError, match="LEGACY_KNOWLEDGE_SCOPE_CHANGED"):
            builder.build(task, definition, attempt=1)
    else:
        with pytest.raises(KnowledgeGapRaised) as resumed:
            builder.build(task, definition, attempt=1)
        assert resumed.value.gap == gap
    assert records.get("snapshots", snapshot.snapshot_sha256, KnowledgeSnapshot) == snapshot


@pytest.mark.parametrize("changed_documents", [False, True])
def test_legacy_verifier_gap_keeps_exact_scope_and_rejects_snapshot_drift(
    tmp_path: Path, changed_documents: bool
) -> None:
    task, _, _, builder = _builder(tmp_path, enabled=False)
    task = task.model_copy(update={"id": "task_continue_legacy"})
    definition = _definitions()[AgentRole.QA]
    with pytest.raises(KnowledgeGapRaised) as original:
        builder.build(task, definition, attempt=1)
    assert original.value.gap.binding.requirement_id == task.id
    builder.sources = (
        ContextSource(
            source_id="joint.approved_context",
            uri="joint://delivery_multi_fixture/hash",
            content="Approved Requirement",
        ),
    )
    if changed_documents:
        builder.sources = (
            *builder.sources,
            ContextSource(
                source_id="native.rule.changed",
                uri="repository://AGENTS.md",
                content="Changed rule",
            ),
        )
        with pytest.raises(KnowledgeError, match="LEGACY_KNOWLEDGE_SCOPE_CHANGED"):
            builder.build(task, definition, attempt=1)
    else:
        with pytest.raises(KnowledgeGapRaised) as reopened:
            builder.build(task, definition, attempt=1)
        assert reopened.value.gap == original.value.gap
