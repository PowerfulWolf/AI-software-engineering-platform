"""Human recovery commands; trusted local operator, never an Agent tool."""

import json
import os
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from ai_software_engineer.recovery.entry import open_recovery_plan, read_recovery_task

app = typer.Typer(help="Explicitly recover a failed pre-candidate Coder with preserved edits.")


def _error() -> NoReturn:
    typer.echo(
        "Recovery stopped safely; inspect configuration, exact approval and current facts.",
        err=True,
    )
    raise typer.Exit(code=2) from None


@app.command("propose")
def propose(
    project: Annotated[str, typer.Option()],
    delivery: Annotated[str, typer.Option()],
    run: Annotated[str, typer.Option()],
    context: Annotated[str, typer.Option()],
    coder_reapply: Annotated[
        bool,
        typer.Option(
            help="Start clean and let Coder adapt the approved patch; requires new approval."
        ),
    ] = False,
) -> None:
    """Prepare current base and capture the stopped original executor; no model call."""
    try:
        plan, path = (
            OrganizationTeamHost.from_environment()
            .recovery_entry()
            .propose(
                project_root=project,
                delivery_id=delivery,
                failed_run_id=run,
                failed_context_id=context,
                input_mode="coder_reapply" if coder_reapply else None,
            )
        )
    except Exception:
        _error()
    typer.echo(
        json.dumps(
            {
                "plan_file": str(path),
                "plan_sha256": plan.plan_sha256,
                "new_task_id": plan.new_task_id,
                "target_base": plan.target_base_revision,
                "input_mode": plan.input_mode or "git_seed",
                "changed_files": [f.path for f in plan.capture.files],
            },
            indent=2,
        )
    )


@app.command("inspect")
def inspect(plan: Annotated[Path, typer.Option()], runtime: bool = False) -> None:
    """Read stored plan/approval without prepare, database initialization or execution."""
    try:
        config = ProductionConfig.from_environment(os.environ)
        store, value = open_recovery_plan(config, plan)
        authorization = store.find_authorization(value.plan_sha256)
        task = read_recovery_task(config, os.environ, store, value) if runtime else None
        payload = value.to_wire()
        # A public inspection does not dump source patches; the private plan retains them.
        payload["capture"] = {
            "capture_sha256": value.capture.capture_sha256,
            "files": [f.to_wire() for f in value.capture.files],
        }
        typer.echo(
            json.dumps(
                {
                    "plan": payload,
                    "authorization": authorization.to_wire() if authorization else None,
                    "task": task.to_wire() if task else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception:
        _error()


@app.command("approve")
def approve(
    plan: Annotated[Path, typer.Option()],
    confirm: Annotated[str, typer.Option()],
    reference: Annotated[str, typer.Option()],
) -> None:
    """Human confirms exact plan digest, original solution reuse, base and captured edits."""
    try:
        OrganizationTeamHost.from_environment().recovery_entry().approve(
            plan,
            confirmed_plan=confirm,
            reference=reference,
        )
    except Exception:
        _error()
    typer.echo("Recovery approved and sealed. No Agent has been started.")


@app.command("run")
def run_recovery(plan: Annotated[Path, typer.Option()]) -> None:
    """Allocate, seed and run a fresh serial Coder → QA → Reviewer attempt."""
    try:
        result = OrganizationTeamHost.from_environment().recovery_entry().execute(plan)
    except Exception:
        _error()
    typer.echo(json.dumps(result.to_wire(), ensure_ascii=False, indent=2))
    if result.task.status is not TaskStatus.DONE:
        raise typer.Exit(code=3)
