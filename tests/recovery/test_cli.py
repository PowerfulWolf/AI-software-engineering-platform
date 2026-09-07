"""Operator recovery CLI fails closed and inspection never constructs Team Host."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_software_engineer.cli import app
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.recovery.store import FileRecoveryStore
from tests.recovery.test_authorization import make_plan


def test_inspect_is_read_only_and_approval_needs_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan(tmp_path / "project")
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        company_id=plan.source.scope.company_id,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    root = (
        Path(config.platform_root)
        / "companies"
        / config.company_id
        / "projects"
        / plan.source.scope.project_id
        / "state"
        / f"recovery-{plan.source.scope.delivery_id}"
    )
    root.parent.mkdir(parents=True)
    store = FileRecoveryStore.initialize(root, scope=plan.source.scope)
    store.put_plan(plan)
    config_file = tmp_path / "config.json"
    config_file.write_text(config.model_dump_json())
    monkeypatch.setenv("ASE_CONFIG", str(config_file))
    path = root / f"plan-{plan.plan_sha256}.json"
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    result = CliRunner().invoke(app, ["recovery", "inspect", "--plan", str(path)])
    assert result.exit_code == 0, result.output
    assert plan.plan_sha256 in result.output and '"patch"' not in result.output
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}
    assert not (Path(config.platform_root) / "organization").exists()
    missing = CliRunner().invoke(app, ["recovery", "approve", "--plan", str(path)])
    assert missing.exit_code == 2
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}
    failed = CliRunner().invoke(app, ["recovery", "inspect", "--plan", str(tmp_path / "missing")])
    assert failed.exit_code == 2 and "Traceback" not in failed.output
    assert not (tmp_path / "missing").exists()
