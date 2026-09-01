"""Command-line composition root for ai-software-engineer."""

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from ai_software_engineer import __version__
from ai_software_engineer.agents import AgentError
from ai_software_engineer.artifacts import ArtifactStoreError, FileArtifactStore
from ai_software_engineer.context import ContextError
from ai_software_engineer.domain import Task, TaskStatus
from ai_software_engineer.evaluation import (
    EvaluationEngine,
    EvaluationEventStoreError,
    EvaluationTraceBuilder,
    EvaluationTraceError,
    FileEvaluationEventStore,
    FileHandoffStore,
    HandoffBuilder,
    HandoffError,
)
from ai_software_engineer.orchestration import OrchestrationError
from ai_software_engineer.runtime import (
    RuntimeConfig,
    RuntimeConfigurationError,
    RuntimeSession,
)
from ai_software_engineer.store import SqliteTaskRepository, StoreError

app = typer.Typer(
    name="ase",
    help="Run the artifact-driven AI software engineering platform.",
    add_completion=False,
    no_args_is_help=False,
    pretty_exceptions_show_locals=False,
)
task_app = typer.Typer(help="Create and inspect durable Tasks.", no_args_is_help=True)
evaluation_app = typer.Typer(help="Recompute replayable evaluation reports.", no_args_is_help=True)
handoff_app = typer.Typer(
    help="Build human-readable terminal delivery handoffs.", no_args_is_help=True
)
app.add_typer(task_app, name="task")
app.add_typer(evaluation_app, name="evaluation")
app.add_typer(handoff_app, name="handoff")

DEFAULT_DATABASE = Path(".ase/state.sqlite3")
DEFAULT_ARTIFACTS = Path("artifacts/runs")
DEFAULT_EVALUATION_EVENTS = Path("artifacts/evaluation-events")
DEFAULT_HANDOFFS = Path("artifacts/handoffs")


class CliInputError(ValueError):
    """Raised when a CLI command's explicit input contract is not met."""


def _version_callback(show_version: bool) -> None:
    if show_version:
        typer.echo(f"ase {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def cli(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
    """Run the artifact-driven AI software engineering platform."""
    del version
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@task_app.command("create")
def create_task(
    file: Annotated[Path, typer.Option("--file", "-f", help="Path to a Task JSON document.")],
    database: Annotated[
        Path, typer.Option("--database", "-d", help="SQLite database path.")
    ] = DEFAULT_DATABASE,
) -> None:
    """Validate and persist one NEW Task."""
    try:
        task = Task.model_validate(_read_json(file))
        if task.status is not TaskStatus.NEW or task.attempts != 0:
            raise CliInputError("task create requires status=NEW and attempts=0")
        with SqliteTaskRepository(database) as repository:
            repository.create(task)
    except (CliInputError, OSError, JSONDecodeError, ValidationError, StoreError) as error:
        _fail(error)
    _emit(task.to_wire())


@task_app.command("show")
def show_task(
    task_id: Annotated[str, typer.Argument(help="Task ID, for example task_example_001.")],
    database: Annotated[
        Path, typer.Option("--database", "-d", help="SQLite database path.")
    ] = DEFAULT_DATABASE,
) -> None:
    """Print the latest typed Task snapshot."""
    try:
        with SqliteTaskRepository(database) as repository:
            task = repository.get(task_id)
    except (OSError, StoreError) as error:
        _fail(error)
    _emit(task.to_wire())


@task_app.command("events")
def list_task_events(
    task_id: Annotated[str, typer.Argument(help="Task ID, for example task_example_001.")],
    database: Annotated[
        Path, typer.Option("--database", "-d", help="SQLite database path.")
    ] = DEFAULT_DATABASE,
) -> None:
    """Print a Task's ordered, replayable StateEvent stream."""
    try:
        with SqliteTaskRepository(database) as repository:
            events = repository.list_events(task_id)
    except (OSError, StoreError) as error:
        _fail(error)
    _emit([event.to_wire() for event in events])


@task_app.command("run")
def run_task(
    task_id: Annotated[str, typer.Argument(help="Task ID to execute serially.")],
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Runtime configuration JSON document.")
    ],
    case_id: Annotated[
        str | None, typer.Option("--case-id", help="Optional stable Evaluation case ID.")
    ] = None,
) -> None:
    """Run one Task through the bounded Coder → QA → Reviewer workflow."""
    try:
        runtime_config = RuntimeConfig.from_file(config)
        with RuntimeSession(runtime_config) as runtime:
            result = runtime.run_task(task_id, case_id=case_id)
    except (
        OSError,
        JSONDecodeError,
        ValidationError,
        ValueError,
        StoreError,
        ArtifactStoreError,
        ContextError,
        AgentError,
        OrchestrationError,
        EvaluationEventStoreError,
        RuntimeConfigurationError,
    ) as error:
        _fail(error)
    _emit({"case_id": result.case_id, "result": result.result.to_wire()})


@evaluation_app.command("report")
def evaluation_report(
    case_id: Annotated[
        str, typer.Argument(help="Evaluation case ID, for example case_example_001.")
    ],
    database: Annotated[
        Path, typer.Option("--database", "-d", help="SQLite database path.")
    ] = DEFAULT_DATABASE,
    artifacts: Annotated[
        Path, typer.Option("--artifacts", help="Immutable ArtifactStore root.")
    ] = DEFAULT_ARTIFACTS,
    events: Annotated[
        Path, typer.Option("--events", help="Immutable EvaluationEventStore root.")
    ] = DEFAULT_EVALUATION_EVENTS,
) -> None:
    """Recompute one case's metrics and ADR from durable facts."""
    try:
        with SqliteTaskRepository(database) as repository:
            trace = EvaluationTraceBuilder(
                repository=repository,
                artifact_store=FileArtifactStore(artifacts),
                event_store=FileEvaluationEventStore(events),
            ).build(case_id)
            report = EvaluationEngine().evaluate((trace,))
    except (
        OSError,
        StoreError,
        ArtifactStoreError,
        EvaluationEventStoreError,
        EvaluationTraceError,
        ValueError,
    ) as error:
        _fail(error)
    _emit(report.to_wire())


@handoff_app.command("build")
def build_handoff(
    task_id: Annotated[str, typer.Argument(help="Terminal Task ID.")],
    database: Annotated[
        Path, typer.Option("--database", "-d", help="SQLite database path.")
    ] = DEFAULT_DATABASE,
    artifacts: Annotated[
        Path, typer.Option("--artifacts", help="Immutable ArtifactStore root.")
    ] = DEFAULT_ARTIFACTS,
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Handoff JSON/Markdown output root.")
    ] = DEFAULT_HANDOFFS,
) -> None:
    """Build and persist a DONE/BLOCKED human handoff."""
    try:
        with SqliteTaskRepository(database) as repository:
            bundle = HandoffBuilder(
                repository=repository,
                artifact_store=FileArtifactStore(artifacts),
            ).build(task_id)
        reference = FileHandoffStore(output).put(bundle)
    except (OSError, StoreError, ArtifactStoreError, HandoffError, ValueError) as error:
        _fail(error)
    _emit(
        {
            "handoff_id": reference.handoff_id,
            "sha256": reference.sha256,
            "json_path": str(reference.json_path),
            "markdown_path": str(reference.markdown_path),
        }
    )


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _emit(payload: object) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def _fail(error: Exception) -> NoReturn:
    typer.echo(f"error: {error}", err=True)
    raise typer.Exit(code=2)


def main() -> None:
    """Execute the console entry point."""
    app()


if __name__ == "__main__":
    main()
