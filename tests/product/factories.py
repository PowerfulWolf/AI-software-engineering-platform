"""Shared exact ProjectProfile/baseline fixtures for Product contracts."""

from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.domain import ProjectPreparation
from ai_software_engineer.project_manager.baseline import (
    ProjectBaselineCompilationStatus,
    ProjectBaselineCompiler,
    ProjectSpecBaseline,
)
from ai_software_engineer.project_profile import ProjectProfile
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def prepared_product_facts(
    tmp_path: Path,
    *,
    project_id: str = "project_product_001",
) -> tuple[ProjectPreparation, ProjectProfile, ProjectSpecBaseline]:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    marker = project / "pyproject.toml"
    if not marker.exists():
        marker.write_text("[project]\nname = 'product-fixture'\n", encoding="utf-8")
    profile = ProjectProfile.discover(project, project_id=project_id, observed_at=NOW)
    baseline = _baseline(profile)
    preparation = ProjectPreparation.create(
        organization_id="organization_team_001",
        project_id=project_id,
        project_root=str(project),
        project_workspace_root=str(tmp_path / "sidecar"),
        organization_root=str(tmp_path / "organization"),
        project_profile_sha256=profile.profile_sha256,
        runtime_binding_sha256="b" * 64,
        baseline_spec_sha256=baseline.baseline_sha256,
        baseline_source_uris=baseline.source_uris,
        prepared_at=NOW,
    )
    return preparation, profile, baseline


def product_knowledge(
    preparation: ProjectPreparation,
) -> tuple[ProjectProfile, ProjectSpecBaseline]:
    profile = ProjectProfile.discover(
        preparation.project_root,
        project_id=preparation.project_id,
        observed_at=NOW,
    )
    baseline = _baseline(profile)
    assert profile.profile_sha256 == preparation.project_profile_sha256
    assert baseline.baseline_sha256 == preparation.baseline_spec_sha256
    return profile, baseline


def _baseline(profile: ProjectProfile) -> ProjectSpecBaseline:
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
