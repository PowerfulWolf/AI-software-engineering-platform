"""Read-only, deterministic ProjectProfile discovery contract tests."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.project_profile import (
    BuildSystem,
    ProjectLanguage,
    ProjectProfile,
    ProjectProfileEncodingError,
    ProjectProfileMetadataError,
    ProjectProfilePathEscape,
    VcsKind,
    discover_project_profile,
)

OBSERVED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _validator() -> Draft202012Validator:
    schema_path = Path(__file__).parents[2] / "schemas" / "project-profile.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_empty_project_is_unknown_deterministic_and_read_only(tmp_path: Path) -> None:
    project = tmp_path / "empty"
    project.mkdir()

    first = discover_project_profile(project, observed_at=OBSERVED)
    replay = discover_project_profile(project, observed_at=OBSERVED + timedelta(hours=1))

    assert first.languages[0].language is ProjectLanguage.UNKNOWN
    assert first.build_systems[0].system is BuildSystem.UNKNOWN
    assert first.vcs.kind is VcsKind.NONE
    assert first.source_revision == "unknown"
    assert first.profile_sha256 == replay.profile_sha256
    assert first.observed_at != replay.observed_at
    assert tuple(project.iterdir()) == ()
    assert list(_validator().iter_errors(first.to_wire())) == []
    first.validate_integrity()


def test_multistack_markers_are_retained_in_stable_order(tmp_path: Path) -> None:
    project = tmp_path / "polyglot"
    project.mkdir()
    for relative in (
        "src/app.py",
        "service/pom.xml",
        "worker/go.mod",
        "web/package.json",
        "web/tsconfig.json",
        "native/CMakeLists.txt",
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("marker\n", encoding="utf-8")

    profile = discover_project_profile(project, observed_at=OBSERVED)

    assert tuple(fact.language for fact in profile.languages) == (
        ProjectLanguage.CPP,
        ProjectLanguage.GO,
        ProjectLanguage.JAVA,
        ProjectLanguage.PYTHON,
        ProjectLanguage.TYPESCRIPT,
    )
    assert {fact.system for fact in profile.build_systems} == {
        BuildSystem.CMAKE,
        BuildSystem.GO,
        BuildSystem.MAVEN,
        BuildSystem.NPM,
    }


def test_native_rule_sources_use_project_uris_hashes_and_schema(tmp_path: Path) -> None:
    project = tmp_path / "rules"
    project.mkdir()
    files = {
        "AGENTS.md": "Agent rules\n",
        "CONTRIBUTING.md": "Contributing\n",
        "README.md": "Read me\n",
        ".editorconfig": "root = true\n",
        ".github/workflows/ci.yml": "name: ci\n",
        ".trellis/spec/core.md": "# Core\n",
    }
    for relative, content in files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    profile = discover_project_profile(
        project,
        project_id="project_rules_001",
        observed_at=OBSERVED,
    )

    assert tuple(source.relative_path for source in profile.native_rules) == tuple(sorted(files))
    for source in profile.native_rules:
        assert source.uri == f"project://project_rules_001/{source.relative_path}"
        assert len(source.sha256) == 64
    assert list(_validator().iter_errors(profile.to_wire())) == []


def test_git_head_ref_and_expected_revision_are_verified(tmp_path: Path) -> None:
    project = tmp_path / "git-project"
    git_dir = project / ".git"
    branch = git_dir / "refs" / "heads" / "main"
    branch.parent.mkdir(parents=True)
    revision = "a" * 40
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    branch.write_text(f"{revision}\n", encoding="ascii")

    profile = discover_project_profile(project, observed_at=OBSERVED, revision=revision)

    assert profile.vcs.kind is VcsKind.GIT
    assert profile.vcs.ref == "refs/heads/main"
    assert profile.vcs.revision == revision
    assert profile.source_revision == revision
    with pytest.raises(ProjectProfileMetadataError, match="does not match"):
        discover_project_profile(project, observed_at=OBSERVED, revision="b" * 40)


def test_discovery_rejects_symlink_escape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    (project / "README.md").symlink_to(outside)

    with pytest.raises(ProjectProfilePathEscape):
        discover_project_profile(project, observed_at=OBSERVED)


def test_native_rule_invalid_utf8_fails_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_bytes(b"\xff\xfe")

    with pytest.raises(ProjectProfileEncodingError):
        discover_project_profile(project, observed_at=OBSERVED)


def test_profile_model_rejects_cross_project_native_rule_uri(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("rules\n", encoding="utf-8")
    payload = discover_project_profile(
        project,
        project_id="project_expected_001",
        observed_at=OBSERVED,
    ).to_wire()
    native_rules = payload["native_rules"]
    assert isinstance(native_rules, list)
    first_rule = cast(dict[str, object], native_rules[0])
    first_rule["uri"] = "project://project_wrong_001/README.md"

    with pytest.raises(ValidationError, match="project_id"):
        ProjectProfile.model_validate(payload)


def test_profile_integrity_detects_schema_valid_tampering(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    original = discover_project_profile(project, observed_at=OBSERVED)
    tampered = original.model_copy(update={"detector_version": "t020-v2"})

    with pytest.raises(ProjectProfileMetadataError, match="profile_sha256"):
        tampered.validate_integrity()
