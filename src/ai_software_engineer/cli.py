"""Command-line composition root for ai-software-engineer."""

import json
from contextlib import suppress
from json import JSONDecodeError
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from ai_software_engineer import __version__
from ai_software_engineer.agents import AgentError, StructuredModelError
from ai_software_engineer.artifacts import ArtifactStoreError, FileArtifactStore
from ai_software_engineer.config import ProductionConfigError
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
from ai_software_engineer.execution import CommandExecutionError
from ai_software_engineer.git import GitWorkspaceError, WorkspacePolicyError
from ai_software_engineer.multi_directory.service import (
    CreateRequirementProject,
    JointDeliveryService,
)
from ai_software_engineer.orchestration import OrchestrationError
from ai_software_engineer.project_manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    ResumeProjectDelivery,
    StartProjectDelivery,
    UnifiedProjectEntryError,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryId,
    ProjectDeliveryCheckpointError,
)
from ai_software_engineer.project_manager.entrypoint import (
    ProjectEntryNotConfigured,
    project_entry,
    requirement_entry,
)
from ai_software_engineer.recovery.cli import app as recovery_app
from ai_software_engineer.runtime import (
    RuntimeConfig,
    RuntimeConfigurationError,
    RuntimeSession,
)
from ai_software_engineer.runtime_workspace import RuntimeWorkspaceError
from ai_software_engineer.store import SqliteTaskRepository, StoreError
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.team_view.server import create_team_server

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
project_app = typer.Typer(help="Start and resume Project Manager deliveries.", no_args_is_help=True)
request_app = typer.Typer(
    help="Prepare a named requirement project, then discuss and deliver.", no_args_is_help=True
)
app.add_typer(task_app, name="task")
app.add_typer(evaluation_app, name="evaluation")
app.add_typer(handoff_app, name="handoff")
app.add_typer(project_app, name="project")
app.add_typer(request_app, name="request")
app.add_typer(recovery_app, name="recovery")
team_app = typer.Typer(
    help="Observe the real team without modifying deliveries.", no_args_is_help=True
)
app.add_typer(team_app, name="team")


@team_app.command("serve")
def serve_team(port: Annotated[int, typer.Option(min=1, max=65535)] = 8765) -> None:
    """Serve the current company's read-only team workspace on loopback."""
    try:
        reader = ProductionTeamReader.from_environment()
        with create_team_server(reader, port=port) as server:
            typer.echo(f"Team workspace: http://127.0.0.1:{server.server_port}")
            typer.echo("Read-only; Ctrl+C stops the view without stopping delivery processes.")
            with suppress(KeyboardInterrupt):
                server.serve_forever()
    except (OSError, ValueError, ProductionConfigError):
        typer.echo("Cannot start team view; check ASE_CONFIG and the local port.", err=True)
        raise typer.Exit(code=2) from None


DEFAULT_DATABASE = Path(".ase/state.sqlite3")
DEFAULT_ARTIFACTS = Path("artifacts/runs")
DEFAULT_EVALUATION_EVENTS = Path("artifacts/evaluation-events")
DEFAULT_HANDOFFS = Path("artifacts/handoffs")


class CliInputError(ValueError):
    """Raised when a CLI command's explicit input contract is not met."""


_PROJECT_ERRORS = (
    RuntimeWorkspaceError,
    StructuredModelError,
    CommandExecutionError,
    GitWorkspaceError,
    WorkspacePolicyError,
    OSError,
    ValidationError,
    ValueError,
    UnifiedProjectEntryError,
    ProjectDeliveryCheckpointError,
    ProjectEntryNotConfigured,
    ProductionConfigError,
    StoreError,
)


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


@project_app.command("start")
def start_project_delivery(
    project_root: Annotated[
        list[Path], typer.Argument(help="One or more absolute code directories.")
    ],
    requirement: Annotated[
        str, typer.Option("--requirement", "-r", help="Requirement to clarify and deliver.")
    ],
    title: Annotated[
        str, typer.Option("--title", help="Short Product discovery title.")
    ] = "Software delivery request",
) -> None:
    """Prepare a project and run Product discovery to its human gate."""
    try:
        entry = requirement_entry() if len(project_root) > 1 else project_entry()
        result = entry.start(
            StartProjectDelivery(
                project_root=str(project_root[0]),
                additional_project_roots=tuple(str(p) for p in project_root[1:]),
                requirement=requirement,
                title=title,
            )
        )
    except _PROJECT_ERRORS as error:
        _fail(error)
    _emit(result.to_wire())


@request_app.command("discuss")
@project_app.command("reply")
def reply_to_product(
    delivery_id: Annotated[DeliveryId, typer.Argument(help="Delivery ID.")],
    message: Annotated[str, typer.Option("--message", "-m", help="Answer to the Product Agent.")],
    checkpoint: Annotated[
        str, typer.Option("--checkpoint", help="Exact current checkpoint SHA-256.")
    ],
) -> None:
    """Add one human Product clarification and run one bounded Product turn."""
    try:
        result = _delivery_entry(delivery_id).reply(
            ReplyToProduct(
                delivery_id=delivery_id,
                expected_checkpoint_sha256=checkpoint,
                message=message,
            )
        )
    except _PROJECT_ERRORS as error:
        _fail(error)
    _emit(result.to_wire())


@request_app.command("approve")
@project_app.command("approve")
def approve_product_spec(
    delivery_id: Annotated[DeliveryId, typer.Argument(help="Delivery ID.")],
    checkpoint: Annotated[
        str, typer.Option("--checkpoint", help="Exact Product checkpoint SHA-256.")
    ],
    approval_reference: Annotated[
        str | None,
        typer.Option("--approval-reference", help="Trusted external approval reference."),
    ] = None,
) -> None:
    """Approve the exact ProductSpec and continue the serial delivery."""
    try:
        result = _delivery_entry(delivery_id).approve(
            ApproveProductSpec(
                delivery_id=delivery_id,
                expected_checkpoint_sha256=checkpoint,
                approval_reference=(approval_reference or f"cli-product-approval:{checkpoint}"),
            )
        )
    except _PROJECT_ERRORS as error:
        _fail(error)
    _emit(result.to_wire())


@request_app.command("resume")
@project_app.command("resume")
def resume_project_delivery(
    delivery_id: Annotated[DeliveryId, typer.Argument(help="Delivery ID.")],
) -> None:
    """Reconcile native facts and continue the first incomplete automatic stage."""
    try:
        result = _delivery_entry(delivery_id).resume(ResumeProjectDelivery(delivery_id=delivery_id))
    except _PROJECT_ERRORS as error:
        _fail(error)
    _emit(result.to_wire())


@request_app.command("status")
@project_app.command("status")
def show_project_delivery(
    delivery_id: Annotated[DeliveryId, typer.Argument(help="Delivery ID.")],
) -> None:
    """Show the latest verified delivery checkpoint."""
    try:
        result = _delivery_entry(delivery_id).status(delivery_id)
    except _PROJECT_ERRORS as error:
        _fail(error)
    _emit(result.to_wire())


@request_app.command("create")
def create_requirement_project(
    directories: Annotated[list[Path], typer.Argument(help="Absolute code scope directories.")],
    name: Annotated[str, typer.Option("--name", help="Requirement project name.")],
) -> None:
    """Register and prepare all code scopes before any requirement/model conversation."""
    try:
        result = requirement_entry().create(
            CreateRequirementProject(
                name=name, project_roots=tuple(str(path) for path in directories)
            )
        )
    except _PROJECT_ERRORS as error:
        _fail(error)
    _emit(result.to_wire())


def _delivery_entry(delivery_id: str) -> UnifiedProjectEntryService | JointDeliveryService:
    return requirement_entry() if delivery_id.startswith("delivery_multi_") else project_entry()


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
