"""Organization/project workspace isolation and Runtime path binding tests."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from ai_software_engineer.domain import (
    AcceptanceCriterion,
    AgentProfile,
    BrainTier,
    ModelPolicy,
    ModelRoute,
    RiskModelFloor,
    RiskTier,
    Task,
    TaskStatus,
    TeamRole,
)
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.repository_workspace import RepositoryWorkspace
from ai_software_engineer.runtime import RuntimeConfig
from ai_software_engineer.runtime_workspace import (
    TEAM_WORKFORCE_DIRECTORIES,
    FileTeamWorkforceStore,
    RuntimeWorkspaceBinder,
    RuntimeWorkspaceBinding,
    RuntimeWorkspaceConflict,
    RuntimeWorkspaceCorruption,
    TeamWorkforceWorkspace,
)
from ai_software_engineer.spec_compiler import SpecCompiler, SpecRule, SpecRuleLayer
from ai_software_engineer.team_workspace import TeamWorkspace

NOW = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


def repository_workspace(tmp_path: Path) -> tuple[RepositoryWorkspace, RepositoryProfile, Path]:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("repository-owned\n", encoding="utf-8")
    team = TeamWorkspace.initialize(
        tmp_path / "platform", team_id="team_engineering_001", name="Engineering"
    )
    project = team.project_registry().register(
        project_id="project_runtime_001", name="Runtime Project"
    )
    workspace = project.repository_registry().register(repository)
    profile = RepositoryProfile.discover(
        repository,
        repository_id=workspace.repository_id,
        observed_at=NOW,
    )
    return workspace, profile, repository


def organization(tmp_path: Path) -> TeamWorkforceWorkspace:
    team = TeamWorkspace.initialize(
        tmp_path / "platform", team_id="team_engineering_001", name="Engineering"
    )
    return TeamWorkforceWorkspace.from_team(team)


def bind(
    tmp_path: Path,
) -> tuple[
    TeamWorkforceWorkspace,
    RepositoryWorkspace,
    RepositoryProfile,
    Path,
    RuntimeWorkspaceBinding,
]:
    workspace, profile, project = repository_workspace(tmp_path)
    org = organization(tmp_path)
    binding = RuntimeWorkspaceBinder().bind(org, workspace, profile, bound_at=NOW)
    return org, workspace, profile, project, binding


def hard_rule() -> SpecRule:
    return SpecRule(
        id="rule_runtime_no_self_approval_001",
        field="safety.self_approval",
        value=False,
        layer=SpecRuleLayer.PLATFORM_HARD,
        priority=10,
        source_uri="platform://hard-safety/v1",
        source_sha256="a" * 64,
        rationale="No Agent may approve its own work.",
    )


def runtime_task(project: Path) -> Task:
    return Task(
        id="task_runtime_binding_001",
        title="Bind runtime",
        description="Run against the bound target project.",
        repository=str(project),
        base_ref="b" * 40,
        acceptance_criteria=(
            AcceptanceCriterion(
                id="ac_models_01",
                description="Runtime is isolated",
                required=True,
                verification="contract test",
            ),
        ),
        status=TaskStatus.NEW,
        max_attempts=3,
        created_at=NOW,
        updated_at=NOW,
    )


def test_binding_places_platform_state_outside_target_and_matches_schema(tmp_path: Path) -> None:
    org, workspace, profile, project, binding = bind(tmp_path)

    assert Path(binding.repository_root) == project.resolve()
    assert Path(binding.team_root) == org.root
    assert Path(binding.paths.database).parent == workspace.directory("state")
    assert Path(binding.paths.artifacts) == workspace.directory("artifacts")
    assert Path(binding.paths.contexts) == workspace.directory("contexts")
    assert Path(binding.paths.evaluation_events) == workspace.directory("evaluations")
    assert Path(binding.paths.handoffs) == workspace.directory("handoffs")
    assert {
        *TEAM_WORKFORCE_DIRECTORIES,
        "team.json",
    } <= {path.name for path in org.root.iterdir()}
    assert set(path.name for path in project.iterdir()) == {"README.md"}
    assert not (project / ".ase").exists()
    assert (workspace.directory("profile") / "repository-profile.json").is_file()
    assert (workspace.directory("policy") / "runtime-workspace-binding.json").is_file()
    binding.validate_integrity()
    profile.validate_integrity()
    schema_path = Path(__file__).parents[2] / "schemas" / "runtime-workspace-binding.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert (
        list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                binding.to_wire()
            )
        )
        == []
    )


def test_binding_replay_preserves_first_observation(tmp_path: Path) -> None:
    org, workspace, profile, _project, first = bind(tmp_path)

    replay = RuntimeWorkspaceBinder().bind(
        org,
        workspace,
        profile,
        bound_at=NOW + timedelta(minutes=5),
    )

    assert replay == first
    assert replay.bound_at == NOW


def test_binding_rejects_stale_profile_and_tampered_project_manifest(tmp_path: Path) -> None:
    workspace, profile, project = repository_workspace(tmp_path)
    org = organization(tmp_path)
    (project / "pyproject.toml").write_text("[project]\nname='changed'\n", encoding="utf-8")
    with pytest.raises(RuntimeWorkspaceConflict, match="current repository facts"):
        RuntimeWorkspaceBinder().bind(org, workspace, profile, bound_at=NOW)

    fresh_profile = RepositoryProfile.discover(
        project,
        repository_id=workspace.repository_id,
        observed_at=NOW,
    )
    payload = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    payload["created_at"] = "2026-09-01T15:00:00Z"
    workspace.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeWorkspaceCorruption):
        RuntimeWorkspaceBinder().bind(org, workspace, fresh_profile, bound_at=NOW)


def test_compose_runtime_config_replaces_legacy_paths_and_injects_compiled_spec(
    tmp_path: Path,
) -> None:
    _org, _workspace, profile, _project, binding = bind(tmp_path)
    task = runtime_task(Path(binding.repository_root))
    compiled = SpecCompiler().compile(profile, task, (hard_rule(),), compiled_at=NOW)
    assert compiled.compiled_spec is not None
    config = RuntimeConfig(
        endpoint="https://api.example.test/v1",
        model="fallback-model",
        api_key_required=False,
    )

    bound = binding.compose_runtime_config(config, compiled.compiled_spec)

    assert bound.paths == binding.paths
    assert bound.context_sources[-1].source_id == "compiled.spec"
    assert bound.spec_version == f"compiled-{compiled.compiled_spec.compiled_sha256}"
    assert Path(bound.paths.database).is_absolute()


def test_team_workforce_store_is_idempotent_and_detects_tampering(
    tmp_path: Path,
) -> None:
    org = organization(tmp_path)
    store = FileTeamWorkforceStore(org)
    agent = AgentProfile(
        id="agent_runtime_coder_001",
        version="v1",
        display_name="Runtime Coder",
        capabilities=("python",),
        eligible_roles=(TeamRole.CODER,),
        max_parallel_assignments=2,
        default_model_policy_id="model_policy_runtime_001",
    )
    policy = model_policy()

    assert store.put_agent(agent) == agent
    assert store.put_agent(agent) == agent
    assert store.put_policy(policy) == policy
    assert store.get_agent(agent.id) == agent
    assert store.get_policy(policy.id) == policy

    path = org.directory("agents") / f"{agent.id}.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["display_name"] = "tampered"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(RuntimeWorkspaceCorruption, match="integrity"):
        store.get_agent(agent.id)


def test_policy_revisions_preserve_legacy_and_require_exact_version(tmp_path: Path) -> None:
    org = organization(tmp_path)
    store = FileTeamWorkforceStore(org)
    old = model_policy()
    store.put_policy(old)
    legacy = org.directory("model-policies") / f"{old.id}.json"
    original = legacy.read_bytes()
    new = old.model_copy(
        update={
            "version": "v2",
            "routes": tuple(
                route.model_copy(update={"model": f"new-{route.model}"}) for route in old.routes
            ),
        }
    )
    assert store.put_policy(new, versioned=True) == new
    assert store.put_policy(new, versioned=True) == new
    assert store.get_policy(old.id) == old
    assert store.get_policy(old.id, version=old.version) == old
    assert store.get_policy(new.id, version=new.version) == new
    assert legacy.read_bytes() == original
    with pytest.raises(RuntimeWorkspaceConflict):
        store.put_policy(new.model_copy(update={"routes": old.routes}), versioned=True)
    with pytest.raises(RuntimeWorkspaceCorruption):
        store.get_policy(old.id, version="missing")
    revision = org.directory("model-policies") / f"{store._policy_key(new.id, new.version)}.json"
    revision.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeWorkspaceCorruption):
        store.get_policy(old.id, version=new.version)
    assert store.get_policy(old.id) == old


def model_policy() -> ModelPolicy:
    return ModelPolicy(
        id="model_policy_runtime_001",
        version="v1",
        default_tier=BrainTier.STANDARD,
        routes=tuple(
            ModelRoute(provider="provider-a", model=f"model-{tier.value}", tier=tier)
            for tier in BrainTier
        ),
        risk_floors=(
            RiskModelFloor(risk=RiskTier.LOW, minimum_tier=BrainTier.ECONOMY),
            RiskModelFloor(risk=RiskTier.NORMAL, minimum_tier=BrainTier.STANDARD),
            RiskModelFloor(risk=RiskTier.HIGH, minimum_tier=BrainTier.REASONING),
            RiskModelFloor(risk=RiskTier.CRITICAL, minimum_tier=BrainTier.CRITICAL),
        ),
    )
