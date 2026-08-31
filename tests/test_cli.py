"""CLI contract tests."""

from importlib.metadata import version as installed_version

from typer.testing import CliRunner

from ai_software_engineer import __version__
from ai_software_engineer.cli import app

runner = CliRunner()


def test_package_metadata_uses_the_public_version() -> None:
    assert installed_version("ai-software-engineer") == __version__


def test_help_describes_the_platform() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "artifact-driven AI software engineering platform" in result.stdout


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app)

    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert "--version" in result.stdout


def test_version_uses_package_metadata() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"ase {__version__}"


def test_unknown_option_returns_a_usage_error() -> None:
    result = runner.invoke(app, ["--unknown-option"])

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert "Traceback" not in result.output
