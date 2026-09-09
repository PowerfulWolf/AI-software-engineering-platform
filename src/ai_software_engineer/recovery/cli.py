"""Human recovery commands; trusted local operator, never an Agent tool."""

import json
import os
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from ai_software_engineer.recovery.entry import open_recovery_plan, read_recovery_task
from ai_software_engineer.recovery.store import RecoveryRecordMissing
from ai_software_engineer.recovery.verification_entry import open_candidate_verification_plan

app = typer.Typer(help="Explicitly recover a failed pre-candidate Coder with preserved edits.")


def _error(error: Exception | None = None) -> NoReturn:
    if error is not None:
        typer.echo(f"error: {error}", err=True)
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
    except Exception as error:
        _error(error)
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
    except Exception as error:
        _error(error)


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
    except Exception as error:
        _error(error)
    typer.echo("Recovery approved and sealed. No Agent has been started.")


@app.command("run")
def run_recovery(plan: Annotated[Path, typer.Option()]) -> None:
    """Allocate, seed and run a fresh serial Coder → QA → Reviewer attempt."""
    try:
        result = OrganizationTeamHost.from_environment().recovery_entry().execute(plan)
    except Exception as error:
        _error(error)
    typer.echo(json.dumps(result.to_wire(), ensure_ascii=False, indent=2))
    if result.task.status is not TaskStatus.DONE:
        raise typer.Exit(code=3)


@app.command("verify-propose")
def verify_propose(
    project: Annotated[str, typer.Option(help="Absolute root of the candidate repository.")],
    delivery: Annotated[
        str,
        typer.Option(help="Child delivery that owns the failed QA checkpoint."),
    ],
) -> None:
    """Pin the existing Coder candidate and current verifier allocation; no model call."""
    try:
        plan, path = (
            OrganizationTeamHost.from_environment()
            .verification_entry()
            .propose_project(project_root=project, delivery_id=delivery)
        )
    except Exception as error:
        _error(error)
    typer.echo(
        json.dumps(
            {
                "plan_file": str(path),
                "plan_sha256": plan.plan_sha256,
                "source_task_id": plan.inputs.task_id,
                "verification_task_id": plan.execution_task_id,
                "candidate_commit": plan.inputs.candidate_revision,
                "roles": [
                    {
                        "role": definition.role.value,
                        "agent_id": definition.id,
                        "provider": definition.provider,
                        "model": definition.model,
                    }
                    for definition in plan.definitions
                    if definition.role.value in ("qa", "reviewer")
                ],
                "next_command": (
                    "ase verify-approve --plan <plan_file> "
                    f"--confirm {plan.plan_sha256} --reference <approval-reference>"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("verify-inspect")
def verify_inspect(plan: Annotated[Path, typer.Option()]) -> None:
    """Inspect the exact plan, approval and sealed result; never invokes a model."""
    try:
        config = ProductionConfig.from_environment(os.environ)
        store, value = open_candidate_verification_plan(config, os.environ, plan)
        try:
            authorization = store.get_verification_authorization(value.plan_sha256)
        except RecoveryRecordMissing:
            authorization = None
        try:
            completion = store.get_verification_completion(value.plan_sha256)
        except RecoveryRecordMissing:
            completion = None
        invocations: dict[str, dict[str, str] | None] = {}
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            try:
                invocation = store.get_verification_invocation(value.plan_sha256, role)
            except RecoveryRecordMissing:
                invocations[role.value] = None
            else:
                invocations[role.value] = {
                    "run_id": invocation.request.run_id,
                    "admitted_at": invocation.admitted_at.isoformat(),
                }
    except Exception as error:
        _error(error)
    typer.echo(
        json.dumps(
            {
                "plan_file": str(plan),
                "plan_sha256": value.plan_sha256,
                "approved": bool(authorization and authorization.decision.approved),
                "source_task_id": value.inputs.task_id,
                "verification_task_id": value.execution_task_id,
                "candidate_commit": value.inputs.candidate_revision,
                "invocations": invocations,
                "qa": {
                    "artifact_id": completion.qa.artifact_id,
                    "status": completion.qa.content.status.value,
                }
                if completion
                else None,
                "review": {
                    "artifact_id": completion.review.artifact_id,
                    "verdict": completion.review.content.verdict.value,
                }
                if completion and completion.review
                else None,
                "verified": completion.verified if completion else None,
                "completion_sha256": completion.completion_sha256 if completion else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("verify-approve")
def verify_approve(
    plan: Annotated[Path, typer.Option()],
    confirm: Annotated[str, typer.Option(help="Exact plan_sha256 printed by verify-propose.")],
    reference: Annotated[str, typer.Option(help="Human approval audit reference.")],
) -> None:
    """Seal explicit human approval for exactly one candidate verification plan."""
    try:
        OrganizationTeamHost.from_environment().verification_entry().approve(
            plan,
            confirmed_plan=confirm,
            reference=reference,
        )
    except Exception as error:
        _error(error)
    typer.echo("Candidate verification approved. Coder was not started.")


@app.command("verify-run")
def verify_run(plan: Annotated[Path, typer.Option()]) -> None:
    """Run only independent QA then Reviewer against the pinned candidate commit."""
    try:
        completion = OrganizationTeamHost.from_environment().verification_entry().execute(plan)
    except Exception as error:
        _error(error)
    typer.echo(
        json.dumps(
            {
                "plan_sha256": completion.plan_sha256,
                "candidate_commit": completion.qa.source_revision,
                "qa_status": completion.qa.content.status.value,
                "review_verdict": completion.review.content.verdict.value
                if completion.review
                else None,
                "verified": completion.verified,
                "completion_sha256": completion.completion_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not completion.verified:
        raise typer.Exit(code=3)
