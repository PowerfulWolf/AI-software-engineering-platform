"""CLI contract tests and offline composition checks."""

import json
from importlib.metadata import version as installed_version
from pathlib import Path

from typer.testing import CliRunner

from ai_software_engineer import __version__
from ai_software_engineer.cli import app
from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import make_task

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


def test_task_create_show_and_events_round_trip(tmp_path: Path) -> None:
    task = make_task().model_copy(update={"repository": str(tmp_path / "project")})
    task_file = tmp_path / "task.json"
    database = tmp_path / "state.sqlite3"
    task_file.write_text(json.dumps(task.to_wire()), encoding="utf-8")

    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--file",
            str(task_file),
            "--database",
            str(database),
        ],
    )
    assert created.exit_code == 0
    assert json.loads(created.stdout)["id"] == task.id

    shown = runner.invoke(app, ["task", "show", task.id, "--database", str(database)])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout) == task.to_wire()

    events = runner.invoke(app, ["task", "events", task.id, "--database", str(database)])
    assert events.exit_code == 0
    assert json.loads(events.stdout) == []


def test_task_create_rejects_non_new_task_without_traceback(tmp_path: Path) -> None:
    task = make_task().model_copy(update={"status": TaskStatus.DONE})
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps(task.to_wire()), encoding="utf-8")

    result = runner.invoke(
        app,
        ["task", "create", "--file", str(task_file), "--database", str(tmp_path / "state.db")],
    )

    assert result.exit_code == 2
    assert "status=NEW" in result.stderr
    assert "Traceback" not in result.output


def test_handoff_build_rejects_non_terminal_task_without_side_effect(tmp_path: Path) -> None:
    task = make_task()
    database = tmp_path / "state.sqlite3"

    with SqliteTaskRepository(database) as repository:
        repository.create(task)

    result = runner.invoke(
        app,
        [
            "handoff",
            "build",
            task.id,
            "--database",
            str(database),
            "--artifacts",
            str(tmp_path / "artifacts"),
            "--output",
            str(tmp_path / "handoffs"),
        ],
    )

    assert result.exit_code == 2
    assert "PLANNING" not in result.output
    assert "Traceback" not in result.output
    assert not (tmp_path / "handoffs").exists()


def test_evaluation_report_missing_case_is_a_stable_cli_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "evaluation",
            "report",
            "case_missing_001",
            "--database",
            str(tmp_path / "state.sqlite3"),
            "--artifacts",
            str(tmp_path / "artifacts"),
            "--events",
            str(tmp_path / "evaluation-events"),
        ],
    )

    assert result.exit_code == 2
    assert "Traceback" not in result.output
    assert "error:" in result.stderr


def test_task_run_missing_runtime_secret_is_a_stable_cli_error(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    task = make_task().model_copy(update={"repository": str(project_root)})
    database = tmp_path / "state.sqlite3"
    config_file = tmp_path / "runtime.json"
    config_file.write_text(
        json.dumps(
            {
                "endpoint": "https://api.example.test/v1",
                "model": "runtime-model",
                "paths": {
                    "database": str(database),
                    "artifacts": str(tmp_path / "artifacts"),
                    "contexts": str(tmp_path / "contexts"),
                    "evaluation_events": str(tmp_path / "evaluation-events"),
                    "handoffs": str(tmp_path / "handoffs"),
                },
            }
        ),
        encoding="utf-8",
    )
    with SqliteTaskRepository(database) as repository:
        repository.create(task)

    result = runner.invoke(app, ["task", "run", task.id, "--config", str(config_file)])

    assert result.exit_code == 2
    assert "OPENAI_API_KEY" in result.stderr
    assert "Traceback" not in result.output
