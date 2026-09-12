"""Shared exact RepositoryProfile/baseline fixtures for Product contracts."""

from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.domain import ProjectPreparation
from ai_software_engineer.manager.baseline import (
    ProjectBaselineCompilationStatus,
    ProjectBaselineCompiler,
    ProjectSpecBaseline,
)
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def prepared_product_facts(
    tmp_path: Path,
    *,
    repository_id: str = "repository_product_001",
) -> tuple[ProjectPreparation, RepositoryProfile, ProjectSpecBaseline]:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    marker = project / "pyproject.toml"
    if not marker.exists():
        marker.write_text("[project]\nname = 'product-fixture'\n", encoding="utf-8")
    profile = RepositoryProfile.discover(project, repository_id=repository_id, observed_at=NOW)
    baseline = _baseline(profile)
    preparation = ProjectPreparation.create(
        team_id="team_roster_001",
        project_id="project_product_001",
        project_manifest_sha256="d" * 64,
        repository_id=repository_id,
        repository_root=str(project),
        repository_workspace_root=str(tmp_path / "sidecar"),
        team_root=str(tmp_path / "team"),
        repository_profile_sha256=profile.profile_sha256,
        runtime_binding_sha256="b" * 64,
        baseline_spec_sha256=baseline.baseline_sha256,
        baseline_source_uris=baseline.source_uris,
        prepared_at=NOW,
    )
    return preparation, profile, baseline


def product_knowledge(
    preparation: ProjectPreparation,
) -> tuple[RepositoryProfile, ProjectSpecBaseline]:
    profile = RepositoryProfile.discover(
        preparation.repository_root,
        repository_id=preparation.repository_id,
        observed_at=NOW,
    )
    baseline = _baseline(profile)
    assert profile.profile_sha256 == preparation.repository_profile_sha256
    assert baseline.baseline_sha256 == preparation.baseline_spec_sha256
    return profile, baseline


def _baseline(profile: RepositoryProfile) -> ProjectSpecBaseline:
    hard_rule = SpecRule(
        id="rule_no_self_approval_product_001",
        field="safety.self_approval",
        value=False,
        layer=SpecRuleLayer.PLATFORM_HARD,
        priority=10,
        scopes=("*",),
        source_uri="platform://hard-safety/v1",
        source_sha256="a" * 64,
        rationale="No Agent may approve its own work.",
    )
    compilation = ProjectBaselineCompiler().compile(profile, (hard_rule,), compiled_at=NOW)
    assert compilation.status is ProjectBaselineCompilationStatus.COMPILED
    assert compilation.compiled_spec is not None
    return compilation.compiled_spec
