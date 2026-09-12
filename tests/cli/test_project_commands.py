"""Unified project command surface tests."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from ai_software_engineer.cli import app
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.recovery import RecoveryRejected

runner = CliRunner()


def test_project_commands_expose_only_business_inputs() -> None:
    result = runner.invoke(app, ["project", "start", "--help"])

    assert result.exit_code == 0
    assert "repository_root" in result.stdout
    assert "--requirement" in result.stdout
    assert "--database" not in result.stdout
    assert "--artifacts" not in result.stdout
    assert "--contexts" not in result.stdout


def test_missing_production_config_fails_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("ASE_CONFIG", str(tmp_path / "missing-production-config.json"))

    result = runner.invoke(
        app,
        ["project", "start", str(project.resolve()), "--requirement", "add a feature"],
    )

    assert result.exit_code == 2
    assert "cannot load production configuration" in result.stderr
    assert "Traceback" not in result.stderr


def test_request_resume_exposes_exact_plan_approval_and_safe_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    help_result = runner.invoke(app, ["request", "resume", "--help"])
    assert help_result.exit_code == 0
    assert "--approve-plan" in help_result.output
    assert "--approval-reference" in help_result.output

    host = Mock()
    host.resume_delivery.side_effect = RecoveryRejected("verification source drifted")
    monkeypatch.setattr(TeamHost, "from_environment", lambda: host)
    failed = runner.invoke(
        app,
        [
            "request",
            "resume",
            "delivery_example",
            "--approve-plan",
            "a" * 64,
            "--approval-reference",
            "test-approval",
        ],
    )

    assert failed.exit_code == 2
    assert "verification source drifted" in failed.stderr
    assert "Traceback" not in failed.output


def test_request_resume_rejects_approval_reference_without_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = Mock()
    monkeypatch.setattr(TeamHost, "from_environment", lambda: host)

    result = runner.invoke(
        app,
        [
            "request",
            "resume",
            "delivery_example",
            "--approval-reference",
            "orphaned-approval",
        ],
    )

    assert result.exit_code == 2
    assert "plan approval digest and reference must be supplied together" in result.stderr
    host.resume_delivery.assert_not_called()
