"""Unified project command surface tests."""

from pathlib import Path

from typer.testing import CliRunner

from ai_software_engineer.cli import app

runner = CliRunner()


def test_project_commands_expose_only_business_inputs() -> None:
    result = runner.invoke(app, ["project", "start", "--help"])

    assert result.exit_code == 0
    assert "project_root" in result.stdout
    assert "--requirement" in result.stdout
    assert "--database" not in result.stdout
    assert "--artifacts" not in result.stdout
    assert "--contexts" not in result.stdout


def test_unconfigured_application_host_fails_without_traceback(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = runner.invoke(
        app,
        ["project", "start", str(project.resolve()), "--requirement", "add a feature"],
    )

    assert result.exit_code == 2
    assert "team runtime is not configured" in result.stderr
    assert "Traceback" not in result.stderr
