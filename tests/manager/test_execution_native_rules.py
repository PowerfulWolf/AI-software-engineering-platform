"""Exact engineering rule epochs retain old records and freeze target Git bodies."""

import hashlib
import json
from pathlib import Path

import pytest

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.execution_native_rules import NativeRuleEpoch
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_native_rules import (
    build_native_rule_change,
    load_native_rule_epoch,
)
from ai_software_engineer.manager.baseline_production import native_rules_at_revision
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer
from tests.manager.test_production_backend import _git, _git_output


def _fixture(tmp_path: Path) -> tuple[Path, GitWorktreeManager, str, EngineeringScope]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git("init", "-b", "main", cwd=repository)
    (repository / "README.md").write_text("Original guidance.\n")
    (repository / "CONTRIBUTING.md").write_text("Old contribution rules.\n")
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "Original rules", cwd=repository)
    base = _git_output("rev-parse", "HEAD", cwd=repository)
    return (
        repository,
        GitWorktreeManager(repository, tmp_path / "worktrees"),
        base,
        EngineeringScope(
            team_id="team_fixture",
            project_id="project_fixture",
            repository_id="repository_fixture",
            repository_root=str(repository),
        ),
    )


def test_rule_epoch_freezes_complete_add_modify_delete_and_redacts(tmp_path: Path) -> None:
    repository, git, base, scope = _fixture(tmp_path)
    source_rules = native_rules_at_revision(git, repository_id=scope.repository_id, revision=base)
    (repository / "README.md").write_text("New guidance.\n")
    (repository / "CONTRIBUTING.md").unlink()
    (repository / "AGENTS.md").write_text("Independent reviewers.\napi_key = 'secret-example'\n")
    _git("add", "-A", cwd=repository)
    _git("commit", "-m", "Target rules", cwd=repository)
    target = _git_output("rev-parse", "HEAD", cwd=repository)
    target_rules = native_rules_at_revision(git, repository_id=scope.repository_id, revision=target)
    records = KnowledgeRecordStore(tmp_path / "records")
    change = build_native_rule_change(
        git=git,
        records=records,
        scope=scope,
        task_id="task_fixture",
        source_revision=base,
        target_base_ref=target,
        source_rules=source_rules,
        target_rules=target_rules,
    )
    assert change is not None
    assert {item.path: item.change for item in change.changes} == {
        "AGENTS.md": "added",
        "CONTRIBUTING.md": "deleted",
        "README.md": "modified",
    }
    epoch = load_native_rule_epoch(records, change.target.epoch_sha256)
    assert epoch.rules == target_rules
    assert epoch.source_rules == source_rules
    inspection = epoch.inspect_change("README.md")
    assert inspection.before_body is not None and inspection.after_body is not None
    assert inspection.before_body.content == "Original guidance.\n"
    assert inspection.after_body.content == "New guidance.\n"
    assert "-Original guidance." in inspection.unified_diff
    assert "+New guidance." in inspection.unified_diff
    assert epoch.inspect_change("CONTRIBUTING.md").after_body is None
    assert epoch.inspect_change("AGENTS.md").before_body is None
    with pytest.raises(ValueError, match="所选路径"):
        epoch.inspect_change("../runtime.env")
    assert "secret-example" not in json.dumps(epoch.to_wire())
    assert "REDACTED" in epoch.bodies[0].content
    assert (
        epoch.bodies[0].source.sha256
        == hashlib.sha256((repository / "AGENTS.md").read_bytes()).hexdigest()
    )
    assert "content" not in json.dumps(change.to_wire())
    original_bytes = {path: path.read_bytes() for path in records.root.glob("*.json")}
    (repository / "README.md").write_text("Unapproved mutable checkout guidance.\n")
    assert load_native_rule_epoch(records, change.target.epoch_sha256) == epoch
    assert original_bytes == {path: path.read_bytes() for path in records.root.glob("*.json")}
    assert (
        build_native_rule_change(
            git=git,
            records=records,
            scope=scope,
            task_id="task_fixture",
            source_revision=base,
            target_base_ref=target,
            source_rules=source_rules,
            target_rules=target_rules,
        )
        == change
    )


def test_rule_epoch_substitutes_target_sources_without_scope_or_checkout_drift(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.context.native import execution_native_rule_sources

    repository, git, base, scope = _fixture(tmp_path)
    source_rules = native_rules_at_revision(git, repository_id=scope.repository_id, revision=base)
    (repository / "README.md").write_text("Approved QA rule.\n")
    (repository / "AGENTS.md").write_text("Approved rules for all delivery roles.\n")
    _git("add", "-A", cwd=repository)
    _git("commit", "-m", "Approved target rules", cwd=repository)
    target = _git_output("rev-parse", "HEAD", cwd=repository)
    target_rules = native_rules_at_revision(git, repository_id=scope.repository_id, revision=target)
    records = KnowledgeRecordStore(tmp_path / "records")
    change = build_native_rule_change(
        git=git,
        records=records,
        scope=scope,
        task_id="task_fixture",
        source_revision=base,
        target_base_ref=target,
        source_rules=source_rules,
        target_rules=target_rules,
    )
    assert change is not None
    epoch = load_native_rule_epoch(records, change.target.epoch_sha256)
    profile = RepositoryProfile.discover(repository, repository_id=scope.repository_id)
    original = (
        ContextSource(source_id="joint.fixture", uri="joint://fixture", content="Product scope"),
        ContextSource(
            source_id="native.rule.0",
            uri=f"project://{scope.repository_id}/README.md",
            content="Original guidance.\n",
            roles=(AgentRole.QA,),
            required=True,
        ),
    )
    (repository / "README.md").write_text("Mutable checkout must not enter context.\n")
    result = execution_native_rule_sources(original, epoch, profile=profile)
    assert result[0] == original[0]
    native = {
        source.uri: source for source in result if source.source_id.startswith("native.rule.")
    }
    assert native[f"project://{scope.repository_id}/README.md"].roles == (AgentRole.QA,)
    assert native[f"project://{scope.repository_id}/README.md"].content == "Approved QA rule.\n"
    assert native[f"project://{scope.repository_id}/AGENTS.md"].required
    assert native[f"project://{scope.repository_id}/AGENTS.md"].roles == ()
    assert sum(source.source_id == "execution.native_rules" for source in result) == 1
    assert original[1].content == "Original guidance.\n"


def test_rule_epoch_does_not_reinterpret_structured_project_rules(tmp_path: Path) -> None:
    repository, git, base, scope = _fixture(tmp_path)
    source_rules = native_rules_at_revision(git, repository_id=scope.repository_id, revision=base)
    rule_source = next(rule for rule in source_rules if rule.relative_path == "README.md")
    rule = SpecRule(
        id="rule_project_fixture",
        field="engineering.example",
        value="original",
        layer=SpecRuleLayer.PROJECT,
        priority=10,
        source_uri=rule_source.uri,
        source_sha256=rule_source.sha256,
        rationale="A structured contract with exact native source provenance.",
    )
    (repository / "README.md").write_text("New structured meaning.\n")
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "Change structured source", cwd=repository)
    target = _git_output("rev-parse", "HEAD", cwd=repository)
    target_rules = native_rules_at_revision(git, repository_id=scope.repository_id, revision=target)
    records = KnowledgeRecordStore(tmp_path / "records")
    with pytest.raises(ValueError, match="结构化"):
        build_native_rule_change(
            git=git,
            records=records,
            scope=scope,
            task_id="task_fixture",
            source_revision=base,
            target_base_ref=target,
            source_rules=source_rules,
            target_rules=target_rules,
            structured_project_rules=(rule,),
        )
    assert not tuple(records.root.glob("*.json"))


def test_native_update_keeps_independent_frozen_sidecar_project_rule(tmp_path: Path) -> None:
    repository, git, base, scope = _fixture(tmp_path)
    source_rules = native_rules_at_revision(git, repository_id=scope.repository_id, revision=base)
    rule = SpecRule(
        id="rule_sidecar_fixture",
        field="engineering.example",
        value="frozen sidecar",
        layer=SpecRuleLayer.PROJECT,
        priority=10,
        source_uri=f"project://{scope.repository_id}/.ase/specs/sidecar_fixture",
        source_sha256="a" * 64,
        rationale="Previously admitted sidecar source remains immutable and is not a Git file.",
    )
    (repository / "README.md").write_text("New opaque guidance.\n")
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "Change native guidance only", cwd=repository)
    target = _git_output("rev-parse", "HEAD", cwd=repository)
    change = build_native_rule_change(
        git=git,
        records=KnowledgeRecordStore(tmp_path / "records"),
        scope=scope,
        task_id="task_fixture",
        source_revision=base,
        target_base_ref=target,
        source_rules=source_rules,
        target_rules=native_rules_at_revision(
            git, repository_id=scope.repository_id, revision=target
        ),
        structured_project_rules=(rule,),
    )
    assert change is not None
    assert [delta.path for delta in change.changes] == ["README.md"]
    assert rule.value == "frozen sidecar"


def test_epoch_rejects_tampered_rendered_body_even_when_outer_hash_recomputed(
    tmp_path: Path,
) -> None:
    repository, git, base, scope = _fixture(tmp_path)
    source_rules = native_rules_at_revision(git, repository_id=scope.repository_id, revision=base)
    (repository / "README.md").write_text("Target guidance.\n")
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "Target", cwd=repository)
    target = _git_output("rev-parse", "HEAD", cwd=repository)
    change = build_native_rule_change(
        git=git,
        records=KnowledgeRecordStore(tmp_path / "records"),
        scope=scope,
        task_id="task_fixture",
        source_revision=base,
        target_base_ref=target,
        source_rules=source_rules,
        target_rules=native_rules_at_revision(
            git, repository_id=scope.repository_id, revision=target
        ),
    )
    assert change is not None
    records = KnowledgeRecordStore(tmp_path / "records")
    epoch = load_native_rule_epoch(records, change.target.epoch_sha256)
    wire = epoch.to_wire()
    bodies = wire["bodies"]
    assert isinstance(bodies, list) and isinstance(bodies[0], dict)
    bodies[0]["content"] = "Tampered rendered rules"
    with pytest.raises(ValueError, match="正文"):
        NativeRuleEpoch.model_validate(wire)


def test_epoch_reads_large_rule_symmetrically_and_required_prompt_cannot_truncate(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.context import ContextBudget
    from ai_software_engineer.context.native import execution_native_rule_sources
    from ai_software_engineer.context.ports import ContextBudgetExceeded
    from ai_software_engineer.orchestration.context import FileRunContextBuilder
    from tests.domain.factories import make_task
    from tests.orchestration.test_runner import _definitions

    repository, git, base, scope = _fixture(tmp_path)
    source_rules = native_rules_at_revision(git, repository_id=scope.repository_id, revision=base)
    (repository / "AGENTS.md").write_text("Require independent review.\n" * 11_000)
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "Large exact target rules", cwd=repository)
    target = _git_output("rev-parse", "HEAD", cwd=repository)
    records = KnowledgeRecordStore(tmp_path / "records")
    change = build_native_rule_change(
        git=git,
        records=records,
        scope=scope,
        task_id=make_task().id,
        source_revision=base,
        target_base_ref=target,
        source_rules=source_rules,
        target_rules=native_rules_at_revision(
            git, repository_id=scope.repository_id, revision=target
        ),
    )
    assert change is not None
    (path,) = tuple(records.root.glob("*.json"))
    assert path.stat().st_size > 256_000
    epoch = load_native_rule_epoch(
        KnowledgeRecordStore(records.root, read_only=True), change.target.epoch_sha256
    )
    assert len(epoch.inspect_change("AGENTS.md").after_body.content) > 256_000  # type: ignore[union-attr]
    sources = execution_native_rule_sources(
        (), epoch, profile=RepositoryProfile.discover(repository, repository_id=scope.repository_id)
    )
    task = make_task().model_copy(update={"repository": str(repository), "base_ref": target})
    with pytest.raises(ContextBudgetExceeded):
        FileRunContextBuilder(
            repository,
            sources=sources,
            budget=ContextBudget(max_input_tokens=1000, reserved_output_tokens=100),
        ).build(task, _definitions()[AgentRole.CODER], attempt=1)


def test_epoch_serialized_utf8_budget_includes_json_escaping(tmp_path: Path) -> None:
    from ai_software_engineer.domain.execution_native_rules import NativeRuleEpochBody
    from ai_software_engineer.repository_profile import NativeRuleKind, NativeRuleSource

    _, _, base, scope = _fixture(tmp_path)
    content = "\0" * 800_000
    bodies = tuple(
        NativeRuleEpochBody(
            source=NativeRuleSource(
                uri=f"project://{scope.repository_id}/AGENTS-{index}.md",
                relative_path=f"AGENTS-{index}.md",
                kinds=(NativeRuleKind.AGENTS,),
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                byte_length=len(content),
            ),
            content=content,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            content_bytes=len(content),
        )
        for index in range(4)
    )
    with pytest.raises(ValueError, match="持久化字节预算"):
        NativeRuleEpoch.create(
            scope=scope,
            task_id="task_fixture",
            source_revision=base,
            target_base_ref=base,
            source_rules=(),
            before_bodies=(),
            bodies=bodies,
        )
