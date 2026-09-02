"""Project-level, Task-free rule baseline contract tests."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.domain.model import JsonValue
from ai_software_engineer.project_manager.baseline import (
    FileProjectBaselineCompilationStore,
    ProjectBaselineCompilationStatus,
    ProjectBaselineCompiler,
    ProjectBaselineIntegrityError,
    ProjectBaselineRecordCorruption,
    ProjectSpecBaseline,
    TaskScopedRuleRejected,
)
from ai_software_engineer.project_profile import ProjectProfile
from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.spec_compiler import (
    HardPolicyMissing,
    SpecConflictClass,
    SpecRule,
    SpecRuleLayer,
    SpecSourceMismatch,
)

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
SCHEMA_DIR = Path(__file__).parents[2] / "schemas"


def profile(tmp_path: Path) -> ProjectProfile:
    project = tmp_path / "target"
    project.mkdir()
    (project / "AGENTS.md").write_text("Use a line length of 88.\n", encoding="utf-8")
    return ProjectProfile.discover(
        project,
        project_id="project_prepare_001",
        observed_at=NOW,
    )


def hard_rule(*, value: JsonValue = False, scopes: tuple[str, ...] = ("*",)) -> SpecRule:
    return SpecRule(
        id="rule_no_self_approval_prepare_001",
        field="safety.self_approval",
        value=value,
        layer=SpecRuleLayer.PLATFORM_HARD,
        priority=10,
        scopes=scopes,
        source_uri="platform://hard-safety/v1",
        source_sha256="a" * 64,
        rationale="No Agent may approve its own work.",
    )


def engineering_rule(
    *,
    value: JsonValue = 100,
    scopes: tuple[str, ...] = ("*",),
) -> SpecRule:
    return SpecRule(
        id="rule_line_length_prepare_platform_001",
        field="style.line_length",
        value=value,
        layer=SpecRuleLayer.PLATFORM_ENGINEERING,
        priority=100,
        scopes=scopes,
        source_uri="platform://python/style-v1",
        source_sha256="b" * 64,
        rationale="Organization engineering convention.",
    )


def project_rule(
    project_profile: ProjectProfile,
    *,
    value: JsonValue = 88,
    scopes: tuple[str, ...] = ("*",),
) -> SpecRule:
    source = project_profile.native_rules[0]
    return SpecRule(
        id="rule_line_length_prepare_project_001",
        field="style.line_length",
        value=value,
        layer=SpecRuleLayer.PROJECT,
        priority=200,
        scopes=scopes,
        source_uri=source.uri,
        source_sha256=source.sha256,
        rationale="Explicitly interpreted project-native rule.",
    )


def test_compiles_stable_task_free_baseline_with_opaque_native_sources(
    tmp_path: Path,
) -> None:
    project_profile = profile(tmp_path)
    compiler = ProjectBaselineCompiler()
    rules = (engineering_rule(), hard_rule())

    first = compiler.compile(project_profile, rules, compiled_at=NOW)
    replay = compiler.compile(
        project_profile,
        tuple(reversed(rules)),
        compiled_at=NOW + timedelta(hours=1),
    )

    assert first.status is ProjectBaselineCompilationStatus.COMPILED
    assert first.compilation_sha256 == replay.compilation_sha256
    assert first.compiled_spec is not None and replay.compiled_spec is not None
    assert first.compiled_spec.baseline_sha256 == replay.compiled_spec.baseline_sha256
    assert first.compiled_spec.project_profile_sha256 == project_profile.profile_sha256
    assert first.compiled_spec.opaque_project_sources[0].uri.endswith("/AGENTS.md")
    assert first.compiled_spec.source_uris == (
        "platform://hard-safety/v1",
        "platform://python/style-v1",
        project_profile.native_rules[0].uri,
    )
    payload = first.compiled_spec.to_wire()
    schema = json.loads((SCHEMA_DIR / "project-baseline.schema.json").read_text())
    errors = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).iter_errors(payload)
    assert list(errors) == []
    assert (
        list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                first.to_wire()
            )
        )
        == []
    )


def test_overlapping_project_rule_conflict_waits_for_human_and_blocks_product(
    tmp_path: Path,
) -> None:
    project_profile = profile(tmp_path)
    rules = (hard_rule(), engineering_rule(), project_rule(project_profile))

    result = ProjectBaselineCompiler().compile(
        project_profile,
        rules,
        compiled_at=NOW,
    )
    replay = ProjectBaselineCompiler().compile(
        project_profile,
        tuple(reversed(rules)),
        compiled_at=NOW + timedelta(hours=1),
    )

    assert result.status is ProjectBaselineCompilationStatus.CONFLICT
    assert result.compiled_spec is None and result.route is not None
    assert result.route.work_item_status == "WAITING_HUMAN"
    assert result.route.product_agent_start_allowed is False
    conflict = result.conflicts[0]
    assert conflict.classification is SpecConflictClass.ENGINEERING
    assert not hasattr(conflict, "task_id")
    assert result.route.conflict_ids == (conflict.id,)
    assert replay.compilation_sha256 == result.compilation_sha256
    schema = json.loads((SCHEMA_DIR / "project-baseline.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert list(validator.iter_errors(conflict.to_wire())) == []
    assert list(validator.iter_errors(result.route.to_wire())) == []
    assert list(validator.iter_errors(result.to_wire())) == []


def test_non_overlapping_scopes_with_different_values_do_not_conflict(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    result = ProjectBaselineCompiler().compile(
        project_profile,
        (
            hard_rule(),
            engineering_rule(scopes=("language:python",)),
            project_rule(project_profile, scopes=("language:java",)),
        ),
        compiled_at=NOW,
    )

    assert result.status is ProjectBaselineCompilationStatus.COMPILED
    assert result.compiled_spec is not None
    assert len(result.compiled_spec.rules) == 3
    assert result.compiled_spec.opaque_project_sources == ()


def test_structured_project_sources_are_removed_from_opaque_sources(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "AGENTS.md").write_text("Use a line length of 88.\n", encoding="utf-8")
    (project / "CONTRIBUTING.md").write_text("Run all tests.\n", encoding="utf-8")
    project_profile = ProjectProfile.discover(
        project,
        project_id="project_prepare_001",
        observed_at=NOW,
    )
    structured = project_rule(project_profile)

    result = ProjectBaselineCompiler().compile(
        project_profile,
        (hard_rule(), structured),
        compiled_at=NOW,
    )

    assert result.compiled_spec is not None
    opaque_uris = {source.uri for source in result.compiled_spec.opaque_project_sources}
    assert structured.source_uri not in opaque_uris
    assert opaque_uris == {
        source.uri for source in project_profile.native_rules if source.uri != structured.source_uri
    }


def test_project_baseline_schema_requires_hard_policy_and_rejects_task_rules(
    tmp_path: Path,
) -> None:
    result = ProjectBaselineCompiler().compile(
        profile(tmp_path),
        (hard_rule(), engineering_rule()),
        compiled_at=NOW,
    )
    baseline = result.compiled_spec
    assert baseline is not None
    schema = json.loads((SCHEMA_DIR / "project-baseline.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    payload = baseline.to_wire()
    rules_payload = cast(list[dict[str, JsonValue]], payload["rules"])

    no_hard_payload = {
        **payload,
        "rules": [{**rule, "layer": "platform_engineering"} for rule in rules_payload],
    }
    task_payload = {
        **payload,
        "rules": [
            rules_payload[0],
            {**rules_payload[1], "layer": "task"},
        ],
    }

    assert list(validator.iter_errors(no_hard_payload))
    assert list(validator.iter_errors(task_payload))


def test_missing_hard_safety_and_task_rule_fail_closed(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    compiler = ProjectBaselineCompiler()

    with pytest.raises(HardPolicyMissing):
        compiler.compile(project_profile, (engineering_rule(),), compiled_at=NOW)

    task_rule = SpecRule(
        id="rule_fake_task_constraint_prepare_001",
        field="task.max_attempts",
        value=3,
        layer=SpecRuleLayer.TASK,
        priority=400,
        source_uri="task://task_not_created_001",
        source_sha256="c" * 64,
        rationale="Must never enter a project baseline.",
    )
    with pytest.raises(TaskScopedRuleRejected, match="before a Task exists"):
        compiler.compile(project_profile, (hard_rule(), task_rule), compiled_at=NOW)


def test_project_rule_must_bind_exact_profile_source(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    changed = project_rule(project_profile).model_copy(update={"source_sha256": "f" * 64})

    with pytest.raises(SpecSourceMismatch, match="hash-mismatched"):
        ProjectBaselineCompiler().compile(
            project_profile,
            (hard_rule(), changed),
            compiled_at=NOW,
        )


def test_baseline_is_frozen_strict_and_integrity_checked(tmp_path: Path) -> None:
    result = ProjectBaselineCompiler().compile(
        profile(tmp_path),
        (hard_rule(),),
        compiled_at=NOW,
    )
    baseline = result.compiled_spec
    assert baseline is not None

    with pytest.raises(ValidationError):
        ProjectSpecBaseline.model_validate({**baseline.to_wire(), "unknown": True})
    changed = baseline.model_copy(update={"project_profile_sha256": "f" * 64})
    with pytest.raises(ProjectBaselineIntegrityError):
        changed.validate_integrity()


def test_hard_safety_conflict_is_classified_without_silent_precedence(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    source = project_profile.native_rules[0]
    unsafe_project_rule = SpecRule(
        id="rule_allow_self_approval_prepare_001",
        field="safety.self_approval",
        value=True,
        layer=SpecRuleLayer.PROJECT,
        priority=9999,
        source_uri=source.uri,
        source_sha256=source.sha256,
        rationale="Unsafe fixture must not override organization hard safety.",
    )

    result = ProjectBaselineCompiler().compile(
        project_profile,
        (hard_rule(), unsafe_project_rule),
        compiled_at=NOW,
    )

    assert result.status is ProjectBaselineCompilationStatus.CONFLICT
    assert result.conflicts[0].classification is SpecConflictClass.HARD_SAFETY
    assert {rule.id for rule in result.conflicts[0].rules} == {
        hard_rule().id,
        unsafe_project_rule.id,
    }


def test_file_store_is_append_once_and_exact_replay_returns_first_record(
    tmp_path: Path,
) -> None:
    project_profile = profile(tmp_path)
    workspace = ProjectWorkspaceRegistry(tmp_path / "sidecars").register(
        tmp_path / "target",
        project_id=project_profile.project_id,
    )
    compiler = ProjectBaselineCompiler()
    first = compiler.compile(project_profile, (hard_rule(),), compiled_at=NOW)
    replay = compiler.compile(
        project_profile,
        (hard_rule(),),
        compiled_at=NOW + timedelta(hours=2),
    )
    store = FileProjectBaselineCompilationStore()

    persisted = store.record(workspace, first)
    replayed = store.record(workspace, replay)

    assert replayed == persisted
    assert replayed.compiled_at == NOW
    assert store.get(workspace, first.compilation_sha256) == persisted
    target = (
        workspace.directory("policy")
        / "project-baseline-compilations"
        / f"{first.compilation_sha256}.json"
    )
    assert target.is_file()
    assert list((tmp_path / "target").iterdir()) == [tmp_path / "target" / "AGENTS.md"]


def test_file_store_separates_conflicts_and_rejects_tampered_envelope(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    workspace = ProjectWorkspaceRegistry(tmp_path / "sidecars").register(
        tmp_path / "target",
        project_id=project_profile.project_id,
    )
    conflict = ProjectBaselineCompiler().compile(
        project_profile,
        (hard_rule(), engineering_rule(), project_rule(project_profile)),
        compiled_at=NOW,
    )
    store = FileProjectBaselineCompilationStore()
    persisted = store.record(workspace, conflict)
    replay = ProjectBaselineCompiler().compile(
        project_profile,
        tuple(reversed((hard_rule(), engineering_rule(), project_rule(project_profile)))),
        compiled_at=NOW + timedelta(hours=1),
    )
    assert store.record(workspace, replay) == persisted
    target = (
        workspace.directory("spec-conflicts")
        / "project-baseline-compilations"
        / f"{conflict.compilation_sha256}.json"
    )
    assert target.is_file()

    envelope = json.loads(target.read_text(encoding="utf-8"))
    envelope["sha256"] = "f" * 64
    target.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ProjectBaselineRecordCorruption, match="digest mismatch"):
        store.get(workspace, conflict.compilation_sha256)


def test_baseline_store_concurrent_replay_preserves_first_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_profile = profile(tmp_path)
    workspace = ProjectWorkspaceRegistry(tmp_path / "sidecars").register(
        tmp_path / "target",
        project_id=project_profile.project_id,
    )
    compiler = ProjectBaselineCompiler()
    first = compiler.compile(project_profile, (hard_rule(),), compiled_at=NOW)
    replay = compiler.compile(
        project_profile,
        (hard_rule(),),
        compiled_at=NOW + timedelta(hours=1),
    )
    store = FileProjectBaselineCompilationStore()

    def publish_first_then_report_collision(source: str | Path, target: str | Path) -> None:
        del source
        compilation_payload = first.to_wire()
        canonical = json.dumps(
            compilation_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        envelope = {
            "compilation": compilation_payload,
            "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }
        Path(target).write_text(
            json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        raise FileExistsError(str(target))

    monkeypatch.setattr(os, "link", publish_first_then_report_collision)
    assert store.record(workspace, replay) == first


def test_baseline_store_maps_non_finite_json_to_typed_corruption(tmp_path: Path) -> None:
    project_profile = profile(tmp_path)
    workspace = ProjectWorkspaceRegistry(tmp_path / "sidecars").register(
        tmp_path / "target",
        project_id=project_profile.project_id,
    )
    compilation = ProjectBaselineCompiler().compile(
        project_profile,
        (hard_rule(),),
        compiled_at=NOW,
    )
    store = FileProjectBaselineCompilationStore()
    store.record(workspace, compilation)
    target = (
        workspace.directory("policy")
        / "project-baseline-compilations"
        / f"{compilation.compilation_sha256}.json"
    )
    target.write_text(
        target.read_text(encoding="utf-8").replace('"value":false', '"value":NaN'),
        encoding="utf-8",
    )

    with pytest.raises(ProjectBaselineRecordCorruption):
        store.get(workspace, compilation.compilation_sha256)


def test_baseline_store_rechecks_symlink_after_root_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_profile = profile(tmp_path)
    workspace = ProjectWorkspaceRegistry(tmp_path / "sidecars").register(
        tmp_path / "target",
        project_id=project_profile.project_id,
    )
    compilation = ProjectBaselineCompiler().compile(
        project_profile,
        (hard_rule(),),
        compiled_at=NOW,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    original_mkdir = Path.mkdir

    def replace_store_root_with_symlink(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path.name == "project-baseline-compilations":
            path.symlink_to(outside, target_is_directory=True)
            return
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", replace_store_root_with_symlink)
    with pytest.raises(ProjectBaselineRecordCorruption, match="escaped its sidecar"):
        FileProjectBaselineCompilationStore().record(workspace, compilation)
