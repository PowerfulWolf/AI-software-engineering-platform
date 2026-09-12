"""Operator recovery CLI fails closed and inspection never constructs Team Host."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from ai_software_engineer.cli import app
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.recovery import RecoveryPlan
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.recovery.test_authorization import make_plan


def test_candidate_verification_commands_are_top_level_and_annotated() -> None:
    runner = CliRunner()
    root = runner.invoke(app, ["--help"])
    assert root.exit_code == 0
    for command, words in (
        ("verify-propose", ("candidate", "model")),
        ("verify-inspect", ("Inspect", "model")),
        ("verify-approve", ("approval", "candidate")),
        ("verify-run", ("QA", "Reviewer")),
    ):
        assert command in root.output
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0
        assert all(word in result.output for word in words)


def test_inspect_is_read_only_and_approval_needs_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root,
        team_id=config.team_id,
        name=config.team_name,
    )
    project = team.project_registry().register(
        project_id="project_test",
        name="Test Project",
    )
    repository = project.repository_registry().register(repository_root)
    plan = make_plan(repository_root, repository_id=repository.repository_id)
    root = repository.root / "state" / f"recovery-{plan.source.scope.delivery_id}"
    store = FileRecoveryStore.initialize(root, scope=plan.source.scope)
    store.put_plan(plan)
    config_file = tmp_path / "config.json"
    config_file.write_text(config.model_dump_json())
    monkeypatch.setenv("ASE_CONFIG", str(config_file))
    path = root / f"plan-{plan.plan_sha256}.json"
    before = {
        str(item.relative_to(config.platform_root)): item.read_bytes()
        for item in Path(config.platform_root).rglob("*")
        if item.is_file()
    }
    result = CliRunner().invoke(app, ["recovery", "inspect", "--plan", str(path)])
    assert result.exit_code == 0, result.output
    assert plan.plan_sha256 in result.output and '"patch"' not in result.output
    assert before == {
        str(item.relative_to(config.platform_root)): item.read_bytes()
        for item in Path(config.platform_root).rglob("*")
        if item.is_file()
    }
    missing = CliRunner().invoke(app, ["recovery", "approve", "--plan", str(path)])
    assert missing.exit_code == 2
    assert before == {
        str(item.relative_to(config.platform_root)): item.read_bytes()
        for item in Path(config.platform_root).rglob("*")
        if item.is_file()
    }
    failed = CliRunner().invoke(app, ["recovery", "inspect", "--plan", str(tmp_path / "missing")])
    assert failed.exit_code == 2 and "Traceback" not in failed.output
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("reapply", [False, True])
def test_proposal_mode_is_explicit_and_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reapply: bool
) -> None:
    original = make_plan(tmp_path / "project")
    plan = RecoveryPlan.create(
        **{**original.to_wire(), "input_mode": "coder_reapply" if reapply else None}
    )
    host = Mock()
    host.recovery_entry.return_value.propose.return_value = (plan, tmp_path / "plan.json")
    monkeypatch.setattr(TeamHost, "from_environment", lambda: host)
    args = [
        "recovery",
        "propose",
        "--project",
        str(tmp_path / "project"),
        "--delivery",
        "delivery_original",
        "--run",
        "run_original",
        "--context",
        "ctx_original",
    ]
    result = CliRunner().invoke(app, args + (["--coder-reapply"] if reapply else []))
    assert result.exit_code == 0, result.output
    assert ("coder_reapply" if reapply else "git_seed") in result.output
    assert (
        host.recovery_entry.return_value.propose.call_args.kwargs["input_mode"] == plan.input_mode
    )
