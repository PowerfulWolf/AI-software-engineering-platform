"""Structured rule compilation, conflict routing, and human resolution tests."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.domain import (
    AcceptanceCriterion,
    Task,
    TaskConstraints,
    TaskStatus,
)
from ai_software_engineer.domain.model import JsonValue
from ai_software_engineer.project_profile import ProjectProfile
from ai_software_engineer.spec_compiler import (
    FileSpecRecordStore,
    HardPolicyMissing,
    SpecCompilationStatus,
    SpecCompiler,
    SpecConflictClass,
    SpecRecordCorruption,
    SpecResolution,
    SpecResolutionAction,
    SpecResolutionRejected,
    SpecRule,
    SpecRuleLayer,
    SpecSourceMismatch,
)

NOW = datetime(2026, 9, 1, 13, 0, tzinfo=UTC)


def task(*, constraints: TaskConstraints | None = None) -> Task:
    return Task(
        id="task_spec_001",
        title="Compile project rules",
        description="Compile project rules without hidden precedence.",
        repository="local",
        base_ref="a" * 40,
        acceptance_criteria=(
            AcceptanceCriterion(
                id="ac_rules_01",
                description="Rules are enforced",
                required=True,
                verification="contract test",
            ),
        ),
        constraints=constraints,
        status=TaskStatus.NEW,
        max_attempts=3,
        created_at=NOW,
        updated_at=NOW,
    )


def profile(tmp_path: Path) -> ProjectProfile:
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("Use four spaces.\n", encoding="utf-8")
    return ProjectProfile.discover(
        project,
        project_id="project_spec_001",
        observed_at=NOW,
    )


def hard_rule(*, value: JsonValue = False) -> SpecRule:
    return SpecRule(
        id="rule_no_self_approval_001",
        field="safety.self_approval",
        value=value,
        layer=SpecRuleLayer.PLATFORM_HARD,
        priority=10,
        source_uri="platform://hard-safety/v1",
        source_sha256="a" * 64,
        rationale="No Agent may approve its own work.",
    )


def engineering_rule(
    *,
    value: JsonValue = 100,
    rule_id: str = "rule_line_length_platform_001",
) -> SpecRule:
    return SpecRule(
        id=rule_id,
        field="style.line_length",
        value=value,
        layer=SpecRuleLayer.PLATFORM_ENGINEERING,
        priority=100,
        source_uri="platform://python/style-v1",
        source_sha256="b" * 64,
        rationale="Organization Python convention.",
    )


def project_rule(project_profile: ProjectProfile, *, value: JsonValue = 88) -> SpecRule:
    source = project_profile.native_rules[0]
    return SpecRule(
        id="rule_line_length_project_001",
        field="style.line_length",
        value=value,
        layer=SpecRuleLayer.PROJECT,
        priority=200,
        source_uri=source.uri,
        source_sha256=source.sha256,
        rationale="Project-native formatting convention.",
    )


def _schema(name: str) -> Draft202012Validator:
    path = Path(__file__).parents[2] / "schemas" / name
    return Draft202012Validator(
        json.loads(path.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )


def test_conflict_free_compilation_is_stable_and_context_ready(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    compiler = SpecCompiler()
    rules = (hard_rule(), engineering_rule())

    first = compiler.compile(project_profile, task(), rules, compiled_at=NOW)
    replay = compiler.compile(
        project_profile,
        task(),
        rules,
        compiled_at=NOW + timedelta(hours=1),
    )

    assert first.status is SpecCompilationStatus.COMPILED
    assert first.compilation_sha256 == replay.compilation_sha256
    assert first.compiled_spec is not None and replay.compiled_spec is not None
    assert first.compiled_spec.compiled_sha256 == replay.compiled_spec.compiled_sha256
    assert first.compiled_spec.opaque_project_sources[0].uri.endswith("/AGENTS.md")
    source = first.compiled_spec.to_context_source()
    assert source.required and source.priority == 10
    assert source.uri.startswith("spec://project_spec_001/task_spec_001/")


def test_engineering_conflict_routes_waiting_human_with_full_provenance(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    compiler = SpecCompiler()
    rules = (hard_rule(), engineering_rule(), project_rule(project_profile))

    first = compiler.compile(project_profile, task(), rules, compiled_at=NOW)
    replay = compiler.compile(
        project_profile,
        task(),
        rules,
        compiled_at=NOW + timedelta(minutes=5),
    )

    assert first.status is SpecCompilationStatus.CONFLICT
    assert first.compiled_spec is None and first.route is not None
    assert first.route.release_lease and first.route.preserve_task_checkpoint
    assert first.route.work_item_status == "WAITING_HUMAN"
    conflict = first.conflicts[0]
    assert conflict.classification is SpecConflictClass.ENGINEERING
    assert conflict.affected_criteria == ("ac_rules_01",)
    assert {rule.source_uri for rule in conflict.rules} == {
        "platform://python/style-v1",
        project_profile.native_rules[0].uri,
    }
    assert conflict.conflict_sha256 == replay.conflicts[0].conflict_sha256
    assert list(_schema("spec-conflict.schema.json").iter_errors(conflict.to_wire())) == []


def test_project_rule_requires_profile_uri_and_exact_hash(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    untrusted = project_rule(project_profile).model_copy(update={"source_sha256": "f" * 64})

    with pytest.raises(SpecSourceMismatch, match="hash-mismatched"):
        SpecCompiler().compile(
            project_profile,
            task(),
            (hard_rule(), untrusted),
            compiled_at=NOW,
        )


def test_missing_hard_policy_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(HardPolicyMissing):
        SpecCompiler().compile(
            profile(tmp_path),
            task(),
            (engineering_rule(),),
            compiled_at=NOW,
        )


def test_hard_conflict_cannot_select_lower_rule_but_can_keep_hard_policy(
    tmp_path: Path,
) -> None:
    project_profile = profile(tmp_path)
    lower = SpecRule(
        id="rule_allow_self_approval_001",
        field="safety.self_approval",
        value=True,
        layer=SpecRuleLayer.PROJECT,
        priority=200,
        source_uri=project_profile.native_rules[0].uri,
        source_sha256=project_profile.native_rules[0].sha256,
        rationale="Unsafe project rule used to verify fail-closed behavior.",
    )
    compiler = SpecCompiler()
    backup_hard = hard_rule().model_copy(
        update={
            "id": "rule_no_self_approval_backup_001",
            "source_uri": "platform://hard-safety/backup-v1",
        }
    )
    initial = compiler.compile(
        project_profile,
        task(),
        (hard_rule(), backup_hard, lower),
        compiled_at=NOW,
    )
    conflict = initial.conflicts[0]
    assert conflict.classification is SpecConflictClass.HARD_SAFETY

    with pytest.raises(SpecResolutionRejected, match="hard safety"):
        SpecResolution.create(
            conflict,
            action=SpecResolutionAction.SELECT_RULE,
            selected_rule_id=lower.id,
            operator_id="human_architect",
            rationale="Attempt an unsafe override.",
            evidence_uris=("evidence://decision/1",),
            resolved_at=NOW,
        )

    resolution = SpecResolution.create(
        conflict,
        action=SpecResolutionAction.KEEP_HARD_POLICY,
        selected_rule_id=hard_rule().id,
        operator_id="human_architect",
        rationale="Hard safety remains mandatory; update the project rule.",
        evidence_uris=("evidence://decision/2",),
        resolved_at=NOW,
    )
    compiled = compiler.compile(
        project_profile,
        task(),
        (hard_rule(), backup_hard, lower),
        compiled_at=NOW,
        resolutions=(resolution,),
    )
    assert compiled.status is SpecCompilationStatus.COMPILED
    assert compiled.compiled_spec is not None
    assert tuple(rule.id for rule in compiled.compiled_spec.rules) == (
        hard_rule().id,
        "rule_no_self_approval_backup_001",
    )


def test_engineering_resolution_requires_evidence_and_is_schema_valid(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    compiler = SpecCompiler()
    initial = compiler.compile(
        project_profile,
        task(),
        (hard_rule(), engineering_rule(), project_rule(project_profile)),
        compiled_at=NOW,
    )
    conflict = initial.conflicts[0]
    with pytest.raises(ValidationError):
        SpecResolution.create(
            conflict,
            action=SpecResolutionAction.SELECT_RULE,
            selected_rule_id=project_rule(project_profile).id,
            operator_id="human_architect",
            rationale="Use project convention.",
            evidence_uris=(),
            resolved_at=NOW,
        )

    resolution = SpecResolution.create(
        conflict,
        action=SpecResolutionAction.SELECT_RULE,
        selected_rule_id=project_rule(project_profile).id,
        operator_id="human_architect",
        rationale="The project convention is deliberate and documented.",
        evidence_uris=("evidence://decision/3",),
        resolved_at=NOW,
    )
    assert list(_schema("spec-resolution.schema.json").iter_errors(resolution.to_wire())) == []
    resolved = compiler.compile(
        project_profile,
        task(),
        (hard_rule(), engineering_rule(), project_rule(project_profile)),
        compiled_at=NOW,
        resolutions=(resolution,),
    )
    assert resolved.status is SpecCompilationStatus.COMPILED
    assert resolved.compiled_spec is not None
    assert project_rule(project_profile).id in {rule.id for rule in resolved.compiled_spec.rules}
    assert engineering_rule().id not in {rule.id for rule in resolved.compiled_spec.rules}


def test_task_constraints_are_structured_and_conflicting_values_wait(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    source = project_profile.native_rules[0]
    task_rule = SpecRule(
        id="rule_project_allowed_paths_001",
        field="task.allowed_paths",
        value=["src/**"],
        layer=SpecRuleLayer.PROJECT,
        priority=200,
        source_uri=source.uri,
        source_sha256=source.sha256,
        rationale="Project code ownership rule.",
    )
    constrained = task(constraints=TaskConstraints(allowed_paths=("tests/**",)))

    result = SpecCompiler().compile(
        project_profile,
        constrained,
        (hard_rule(), task_rule),
        compiled_at=NOW,
    )

    assert result.status is SpecCompilationStatus.CONFLICT
    assert result.conflicts[0].field == "task.allowed_paths"
    assert {rule.layer for rule in result.conflicts[0].rules} == {
        SpecRuleLayer.PROJECT,
        SpecRuleLayer.TASK,
    }


def test_non_overlapping_scopes_do_not_conflict(tmp_path: Path) -> None:
    left = engineering_rule().model_copy(update={"scopes": ("role:coder",)})
    right = engineering_rule(value=88, rule_id="rule_line_length_qa_001").model_copy(
        update={"scopes": ("role:qa",)}
    )

    result = SpecCompiler().compile(
        profile(tmp_path),
        task(),
        (hard_rule(), left, right),
        compiled_at=NOW,
    )

    assert result.status is SpecCompilationStatus.COMPILED


def test_file_store_is_append_only_and_detects_tampering(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    result = SpecCompiler().compile(
        project_profile,
        task(),
        (hard_rule(), engineering_rule(), project_rule(project_profile)),
        compiled_at=NOW,
    )
    conflict = result.conflicts[0]
    resolution = SpecResolution.create(
        conflict,
        action=SpecResolutionAction.SELECT_RULE,
        selected_rule_id=project_rule(project_profile).id,
        operator_id="human_architect",
        rationale="Choose the documented project convention.",
        evidence_uris=("evidence://decision/4",),
        resolved_at=NOW,
    )
    store = FileSpecRecordStore(tmp_path / "sidecar" / "spec-conflicts")

    assert store.put_conflict(conflict) == conflict
    assert store.put_conflict(conflict) == conflict
    assert store.put_resolution(resolution) == resolution
    assert store.get_resolution(conflict.id) == resolution

    changed = resolution.model_copy(update={"rationale": "Different decision"})
    with pytest.raises(SpecRecordCorruption):
        store.put_resolution(changed)

    conflict_path = tmp_path / "sidecar" / "spec-conflicts" / "conflicts" / f"{conflict.id}.json"
    payload = json.loads(conflict_path.read_text(encoding="utf-8"))
    payload["reason"] = "tampered but schema-valid"
    conflict_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SpecRecordCorruption):
        store.get_conflict(conflict.id)


def test_store_rejects_changed_replay_for_same_conflict_identity(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    result = SpecCompiler().compile(
        project_profile,
        task(),
        (hard_rule(), engineering_rule(), project_rule(project_profile)),
        compiled_at=NOW,
    )
    conflict = result.conflicts[0]
    store = FileSpecRecordStore(tmp_path / "records")
    store.put_conflict(conflict)
    replay = conflict.model_copy(update={"detected_at": NOW + timedelta(minutes=1)})
    assert store.put_conflict(replay) == conflict

    different = conflict.model_copy(update={"reason": "changed"})
    with pytest.raises(SpecRecordCorruption):
        store.put_conflict(different)
