"""Real production facts, no live providers and no dashboard writes."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pymysql.cursors import DictCursor
from typer.testing import CliRunner

from ai_software_engineer.agents import AgentRequest, AgentResult, StructuredModelResult
from ai_software_engineer.cli import app
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentProfile
from ai_software_engineer.domain.enums import AgentRole, TeamRole, WorkItemStatus
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    ResumeProjectDelivery,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryIntake,
)
from ai_software_engineer.manager.dispatch import VerificationReservation
from ai_software_engineer.manager.mysql_dispatch_authority import _decode_commit
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.attachments import RequirementScreenshot
from ai_software_engineer.multi_directory.models import (
    ChildDelivery,
    DialogueMessage,
    IntegrationEvidence,
    JointCheckpoint,
    JointDeliveryResult,
    JointExecutionPlan,
    JointStage,
    digest,
)
from ai_software_engineer.multi_directory.retirement import RequirementRetirementStore
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit, git_read
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.runtime_workspace import (
    FileTeamWorkforceStore,
    TeamWorkforceWorkspace,
)
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.team_view.models import (
    ProjectView,
    RequestView,
    ScopeView,
    TaskView,
    TeamReadError,
    TeamSnapshot,
)
from ai_software_engineer.team_view.reader import (
    ProductionTeamReader,
    _agent_views,
    _candidate_branch,
    _request_with_current_work,
)
from ai_software_engineer.team_view.server import create_team_server
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.e2e.test_joint_delivery import setup_host
from tests.manager.test_production_backend import (
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
    _ScriptedDeliveryFactory,
)
from tests.recovery.test_native import InterruptedFactory


def _bytes(root: Path) -> dict[str, str]:
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()
    }


def test_candidate_branch_is_read_from_the_exact_candidate_ref(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
    subprocess.run(("git", "config", "user.email", "test@example.com"), cwd=repository, check=True)
    subprocess.run(("git", "config", "user.name", "Test"), cwd=repository, check=True)
    (repository / "README.md").write_text("candidate\n", encoding="utf-8")
    subprocess.run(("git", "add", "README.md"), cwd=repository, check=True)
    subprocess.run(("git", "commit", "-qm", "candidate"), cwd=repository, check=True)
    candidate = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    task_id = "task_console_candidate"
    branch = f"ai/{task_id}/attempt-2"
    subprocess.run(("git", "branch", branch), cwd=repository, check=True)

    assert _candidate_branch(str(repository), task_id, candidate) == branch
    assert _candidate_branch(str(repository), task_id, "f" * 40) is None


def test_active_child_task_supersedes_stale_blocked_requirement_projection() -> None:
    scope = ScopeView(
        root="/workspace/repository",
        selected_paths=(".",),
        delivery_id="delivery_child_active",
    )
    request = RequestView(
        id="delivery_multi_stale_parent",
        project_id="project_test",
        title="Active recovery",
        stage="BLOCKED",
        scopes=(scope,),
        next_action="Inspect the old blocked checkpoint.",
        blocker="Repository is BLOCKED.",
        failed_stages=("PLANNING",),
        checkpoint_sha256="a" * 64,
    )
    task = TaskView(
        id="delivery_child_active",
        project_id="project_test",
        request_id=request.id,
        title=request.title,
        scope=scope,
        status="IMPLEMENTING",
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=datetime.now(UTC),
        next_action="RUN_DELIVERY",
    )

    projected = _request_with_current_work(request, [task])

    assert projected.stage == "DELIVERING"
    assert projected.blocker is None
    assert projected.failed_stages == ()
    assert projected.next_action == "RUN_DELIVERY"


def test_requirement_stages_populate_upstream_agent_queues() -> None:
    profiles = tuple(
        AgentProfile(
            id=f"agent_team_{role.value}",
            version="v0.1",
            display_name=f"{role.value} Agent",
            capabilities=(role.value,),
            eligible_roles=(role,),
            max_parallel_assignments=8,
            default_model_policy_id="model_policy_test",
        )
        for role in (
            TeamRole.MANAGER,
            TeamRole.PRODUCT,
            TeamRole.DESIGNER,
            TeamRole.PLANNER,
        )
    )
    scope = ScopeView(root="/workspace/repository", selected_paths=(".",))

    def request(identifier: str, stage: str) -> RequestView:
        return RequestView(
            id=identifier,
            project_id="project_test",
            title=stage,
            stage=stage,
            scopes=(scope,),
            next_action="Continue.",
            checkpoint_sha256="a" * 64,
        )

    requests = [
        request("request_preparing", "PREPARING"),
        request("request_product", "PRODUCT_DISCOVERY"),
        request("request_product_waiting", "WAITING_PRODUCT_REPLY"),
        request("request_design", "DESIGNING"),
        request("request_plan", "PLANNING"),
        request("request_blocked", "BLOCKED"),
        request("request_done", "DONE"),
        request("request_closed", "CLOSED"),
    ]

    views = {view.roles[0]: view for view in _agent_views(profiles, requests, [])}

    assert views[TeamRole.MANAGER].current_stage_delivery_ids == ("request_preparing",)
    assert views[TeamRole.PRODUCT].current_stage_delivery_ids == ("request_product",)
    assert "request_product_waiting" in views[TeamRole.PRODUCT].assigned_delivery_ids
    assert views[TeamRole.DESIGNER].current_stage_delivery_ids == ("request_design",)
    assert views[TeamRole.PLANNER].current_stage_delivery_ids == ("request_plan",)
    assert "request_blocked" in views[TeamRole.MANAGER].assigned_delivery_ids
    assert "request_blocked" not in views[TeamRole.MANAGER].current_stage_delivery_ids
    assert all(
        "request_blocked" not in views[role].assigned_delivery_ids
        for role in (TeamRole.PRODUCT, TeamRole.DESIGNER, TeamRole.PLANNER)
    )
    assert all(
        {"request_done", "request_closed"}.issubset(views[role].history_delivery_ids)
        for role in (
            TeamRole.MANAGER,
            TeamRole.PRODUCT,
            TeamRole.DESIGNER,
            TeamRole.PLANNER,
        )
    )


def test_missing_workspace_never_initializes(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path / "absent"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    with pytest.raises(TeamReadError):
        ProductionTeamReader(config, {}).snapshot()
    assert not Path(config.platform_root).exists()


def test_default_workspace_reader_never_initializes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr("ai_software_engineer.config.production.Path.home", lambda: home)
    monkeypatch.setattr("sys.platform", "linux")
    config = ProductionConfig(
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )

    with pytest.raises(TeamReadError):
        ProductionTeamReader(config, {}).snapshot()

    assert config.platform_root == str(home / ".ase")
    assert not (home / ".ase").exists()

    TeamWorkspace.initialize(
        config.platform_root,
        team_id=config.team_id,
        name=config.team_name,
    )

    assert (home / ".ase" / "team").is_dir()


def test_empty_team_needs_no_database_or_models(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    TeamWorkspace.initialize(tmp_path, team_id=config.team_id, name=config.team_name)
    before = _bytes(tmp_path)
    snapshot = ProductionTeamReader(config, {}).snapshot()
    assert not snapshot.agents and not snapshot.tasks and not snapshot.requests
    assert _bytes(tmp_path) == before


def test_pre_dispatch_failure_needs_no_database(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    repository = project.repository_registry().register(repository_root)
    store = FileProjectDeliveryCheckpointStore(repository.root / "state" / "project-deliveries")
    now = datetime.now(UTC)
    delivery_id = "delivery_pre_dispatch_failure"
    store.put_intake(
        ProjectDeliveryIntake.create(
            delivery_id=delivery_id,
            repository_id=repository.repository_id,
            repository_root=str(repository_root),
            title="Dispatch failed before Task creation",
            requirement="Show the durable failure without inventing an Assignment.",
            submitted_at=now,
        )
    )
    store.put(
        ProjectDeliveryCheckpoint.create(
            delivery_id=delivery_id,
            sequence=1,
            repository_id=repository.repository_id,
            repository_root=str(repository_root),
            stage=DeliveryStage.BLOCKED,
            stage_attempts=DeliveryStageAttempts(dispatching=1),
            next_action=DeliveryNextAction.REQUEST_HUMAN,
            failure_code=DeliveryFailureCode.CHECKPOINT_DRIFT,
            failure_summary="Dispatch rejected stale or inconsistent facts.",
            failed_stage=DeliveryStage.DISPATCHING,
            checkpointed_at=now,
        )
    )

    snapshot = ProductionTeamReader(config, {}).snapshot(project.manifest.project_id)

    assert len(snapshot.tasks) == 1
    task = snapshot.tasks[0]
    assert task.status == "BLOCKED"
    assert task.terminal
    assert task.task_id is None
    assert task.assignments == ()
    assert snapshot.requests[0].failed_stages == ("DISPATCHING",)


@pytest.mark.mysql
def test_joint_reader_accepts_committed_child_checkpoint_as_a_valid_prefix(
    tmp_path: Path,
) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=InterruptedFactory(),
    )
    service = host.requirement_entry()
    created = service.create(
        CreateRequirement(
            name="Advanced native child",
            repository_roots=tuple(map(str, projects)),
        )
    ).checkpoint
    product = service.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update both greetings",
        )
    ).checkpoint
    parent = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="team-view-prefix",
        )
    ).checkpoint
    assert parent.stage is JointStage.BLOCKED
    child = parent.children[0].checkpoint
    project = host.projects()[0]
    sidecar = project.root / "repositories" / child.repository_id / "state/project-deliveries"
    store = FileProjectDeliveryCheckpointStore(sidecar)
    values = child.to_wire()
    values.pop("checkpoint_sha256")
    advanced = store.put(
        ProjectDeliveryCheckpoint.create(
            **{
                **values,
                "sequence": child.sequence + 1,
                "previous_checkpoint_sha256": child.checkpoint_sha256,
                "checkpointed_at": child.checkpointed_at + timedelta(microseconds=1),
            }
        )
    )
    service.backend.reconcile(parent)

    snapshot = ProductionTeamReader(config, environment).snapshot()

    task = next(item for item in snapshot.tasks if item.id == child.delivery_id)
    assert task.last_activity >= advanced.checkpointed_at
    assert task.request_id == parent.delivery_id
    request = next(item for item in snapshot.requests if item.id == parent.delivery_id)
    assert request.failed_stages == (child.failed_stage.value,)


@pytest.mark.mysql
@pytest.mark.parametrize("extra_attempt", [False, True])
def test_joint_reader_preserves_child_ownership_through_integration_replanning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_attempt: bool,
) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    service = host.requirement_entry()
    reader = ProductionTeamReader(config, environment)
    original_complete = models.complete
    original_for_projects = models.for_projects
    observed: list[str] = []
    planning_revisions: list[tuple[str | None, ...]] = []
    plan_count = 0

    def for_projects(roots: tuple[Path, ...], role: TeamRole = TeamRole.PRODUCT) -> object:
        if role is TeamRole.PLANNER:
            planning_revisions.append(tuple(git_read(root, "rev-parse", "HEAD") for root in roots))
            assert all(git_read(root, "status", "--porcelain") == "" for root in roots)
        return original_for_projects(roots, role)

    monkeypatch.setattr(models, "for_projects", for_projects)

    def observe(expected_stage: str) -> None:
        before = _bytes(Path(config.platform_root))
        snapshot = reader.snapshot()
        assert _bytes(Path(config.platform_root)) == before
        assert len(snapshot.requests) == 1
        parent = snapshot.requests[0]
        assert parent.stage == expected_stage
        assert len(snapshot.tasks) == 2
        assert {task.request_id for task in snapshot.tasks} == {parent.id}
        assert {scope.delivery_id for scope in parent.scopes} == {
            task.id for task in snapshot.tasks
        }
        assert all(task.terminal and task.status == "DONE" for task in snapshot.tasks)
        observed.append(expected_stage)

    def complete(
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        nonlocal plan_count
        result = original_complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )
        if output_schema["title"] != "JointExecutionPlan":
            return result
        plan_count += 1
        plan = JointExecutionPlan.model_validate(result.payload)
        if plan_count == 1:
            check = plan.integration_checks[0].model_copy(
                update={"argv": (*plan.integration_checks[0].argv, "-p", "missing_*.py")}
            )
        else:
            assert input_payload.get("plan") is None
            observe("PLANNING")
            check = plan.integration_checks[0].model_copy(update={"id": "joint_retry"})
        return StructuredModelResult(
            payload=plan.model_copy(update={"integration_checks": (check,)}).to_wire(),
            duration_ms=0,
        )

    monkeypatch.setattr(models, "complete", complete)
    created = service.create(
        CreateRequirement(name="Integration retry", repository_roots=tuple(map(str, projects)))
    ).checkpoint
    product = service.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update both greetings",
        )
    ).checkpoint
    blocked = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="integration-reader-test",
        )
    ).checkpoint
    assert blocked.stage is JointStage.BLOCKED
    assert all(child.checkpoint.stage is DeliveryStage.DONE for child in blocked.children)
    if extra_attempt:
        blocked = service.journal.append(
            JointCheckpoint.seal(
                {
                    **blocked.to_wire(),
                    "sequence": blocked.sequence + 1,
                    "previous_checkpoint_sha256": blocked.checkpoint_sha256,
                    "attempts": {**blocked.attempts, "integration": 3},
                }
            ),
            expected=blocked.checkpoint_sha256,
        )
    original_integrate = service.backend.integrate

    def integrate(checkpoint: JointCheckpoint) -> IntegrationEvidence:
        observe("INTEGRATING")
        return original_integrate(checkpoint)

    def reject_rerun(*args: object, **kwargs: object) -> None:
        raise AssertionError("completed repository Agents must not rerun")

    monkeypatch.setattr(service.backend, "integrate", integrate)
    monkeypatch.setattr(_ScriptedDeliveryAdapter, "run", reject_rerun)
    command = ResumeProjectDelivery(delivery_id=blocked.delivery_id)
    if extra_attempt:
        proposed = host.resume_delivery(command)
        assert isinstance(proposed, JointDeliveryResult)
        proposal = proposed.integration_retry_proposal
        assert proposal is not None
        command = command.model_copy(
            update={
                "approved_plan_sha256": digest(proposal),
                "approval_reference": "one-extra-integration-test",
            }
        )
    result = host.resume_delivery(command).checkpoint
    assert result.stage is JointStage.DONE
    assert result.children == blocked.children
    assert planning_revisions[0] == tuple(unit.base_revision for unit in result.scope.units)
    assert planning_revisions[1] == tuple(c.checkpoint.candidate_revision for c in result.children)
    assert planning_revisions[0] != planning_revisions[1]
    observe("DONE")
    assert observed == ["PLANNING", "INTEGRATING", "DONE"]

    original_current = JointJournal.current
    first, second = result.children
    future_values = first.checkpoint.to_wire()
    future_values.pop("checkpoint_sha256")
    future_values.update(
        sequence=first.checkpoint.sequence + 1,
        previous_checkpoint_sha256=first.checkpoint.checkpoint_sha256,
    )
    corrupt_children = (
        (
            first.model_copy(update={"unit_id": second.unit_id}),
            second.model_copy(update={"unit_id": first.unit_id}),
        ),
        (
            first.model_copy(
                update={"checkpoint": ProjectDeliveryCheckpoint.create(**future_values)}
            ),
            second,
        ),
        (first.model_copy(update={"unit_id": "unit_" + "f" * 16}), second),
    )
    for children in corrupt_children:
        corrupt = JointCheckpoint.seal(
            {
                **result.to_wire(),
                "stage": JointStage.PLANNING,
                "plan": None,
                "children": children,
                "integration_retry_approval": None,
            }
        )

        def current(
            journal: JointJournal,
            delivery_id: str,
            captured: JointCheckpoint = corrupt,
        ) -> JointCheckpoint | None:
            if delivery_id == result.delivery_id:
                return captured
            return original_current(journal, delivery_id)

        with monkeypatch.context() as patch:
            patch.setattr(JointJournal, "current", current)
            with pytest.raises(TeamReadError):
                reader.snapshot()


@pytest.mark.mysql
def test_real_inflight_joint_and_terminal_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    service = host.requirement_entry()
    reader = ProductionTeamReader(config, environment)
    original_run = _ScriptedDeliveryAdapter.run
    seen: list[tuple[AgentRole, TeamSnapshot]] = []

    def observe(adapter: _ScriptedDeliveryAdapter, request: AgentRequest) -> AgentResult:
        before = _bytes(Path(config.platform_root) / "team")
        snapshot = reader.snapshot()
        assert _bytes(Path(config.platform_root) / "team") == before
        current = next(t for t in snapshot.tasks if t.task_id == request.task_id)
        assert sum(a.current_stage for a in current.assignments) == 1
        assert next(a.role for a in current.assignments if a.current_stage) == request.role
        (executing,) = tuple(
            step for step in current.role_queue if step.status is WorkItemStatus.RUNNING
        )
        assert executing.role is request.role
        assert executing.lease_liveness == "LEASE_VALID"
        assert executing.heartbeat_at is not None and executing.lease_expires_at is not None
        assert all(
            step.status is WorkItemStatus.CLOSED or step is executing for step in current.role_queue
        )
        assert current.scope.root in tuple(map(str, projects))
        assert current.execution_liveness == "UNKNOWN"
        assert len(snapshot.requests) >= 1
        seen.append((request.role, snapshot))
        return original_run(adapter, request)

    monkeypatch.setattr(_ScriptedDeliveryAdapter, "run", observe)
    for index in range(2):
        created = service.create(
            CreateRequirement(
                name=f"Live team request {index}",
                repository_roots=tuple(map(str, projects)),
            )
        ).checkpoint
        initial = reader.snapshot()
        assert any(r.stage == "READY_FOR_DISCUSSION" for r in initial.requests)
        product = service.reply(
            ReplyToProduct(
                delivery_id=created.delivery_id,
                expected_checkpoint_sha256=created.checkpoint_sha256,
                message="Update both greetings",
            )
        ).checkpoint
        done = service.approve(
            ApproveProductSpec(
                delivery_id=product.delivery_id,
                expected_checkpoint_sha256=product.checkpoint_sha256,
                approval_reference=f"human-{index}",
            )
        ).checkpoint
        assert done.stage == "DONE", done.next_action
    assert len(seen) == 12
    first = seen[0][1]
    assert len(first.tasks) == 1 and first.requests[0].stage == "DELIVERING"
    final = reader.snapshot()
    assert len(final.requests) == 2 and len(final.tasks) == 4 and len(final.agents) == 7
    assert all(
        not a.current_stage_delivery_ids and not a.assigned_delivery_ids for a in final.agents
    )
    delivery_agents = tuple(
        agent
        for agent in final.agents
        if set(agent.roles) & {TeamRole.CODER, TeamRole.QA, TeamRole.REVIEWER}
    )
    upstream_agents = tuple(agent for agent in final.agents if agent not in delivery_agents)
    assert all(len(a.history_delivery_ids) == 4 for a in delivery_agents)
    assert all(len(a.history_delivery_ids) == 2 for a in upstream_agents)
    assert all(t.candidate_revision and len(t.assignments) == 3 for t in final.tasks)
    assert all(t.timeline and t.documents for t in final.tasks)
    assert all(len(t.role_queue) == 3 for t in final.tasks)
    assert all(step.status is WorkItemStatus.CLOSED for t in final.tasks for step in t.role_queue)
    assert all(len(t.runs) == 3 and all(r.model == "gpt-5.5" for r in t.runs) for t in final.tasks)
    assert all(len(r.scopes) == 2 and len(r.documents) == 4 for r in final.requests)

    # Unrecognized top-level directories are not treated as Projects.
    foreign = Path(config.platform_root) / "unrelated" / "requirements"
    foreign.mkdir(parents=True)
    (foreign / "bad.json").write_text("bad")
    assert reader.snapshot().tasks == final.tasks

    project = host.projects()[0]
    journal = JointJournal(project.requirements_root, read_only=True)
    with pytest.raises(ValueError, match="read-only"):
        journal.append(done, expected=done.checkpoint_sha256)
    checkpoint_file = next(project.requirements_root.glob("delivery_multi_*/*.json"))
    checkpoint_file.write_text("{}")
    with pytest.raises(TeamReadError):
        reader.snapshot()


class _Reader:
    def __init__(self) -> None:
        self.fail = False
        self.reads = 0
        self.selected: list[str | None] = []

    def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
        self.reads += 1
        self.selected.append(project_id)
        if self.fail:
            raise RuntimeError("password=private-must-not-leak")
        selected = project_id or "project_test"
        return TeamSnapshot(
            as_of=datetime.now(UTC),
            team_id="team_test",
            team_name="Test",
            selected_project_id=selected,
            projects=(
                ProjectView(id="project_test", name="Test"),
                ProjectView(id="project_other", name="Other"),
            ),
        )


@pytest.fixture
def server() -> Iterator[tuple[int, _Reader]]:
    reader = _Reader()
    with create_team_server(reader, port=0) as instance:
        thread = Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        try:
            yield instance.server_port, reader
        finally:
            instance.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def test_write_methods_rejected(server: tuple[int, _Reader], method: str) -> None:
    port, reader = server
    with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as client:
        client.request(method, "/api/v1/team")
        response = client.getresponse()
        assert response.status == 405 and response.getheader("Allow") == "GET"
    assert reader.reads == 0


def test_http_refresh_and_security(server: tuple[int, _Reader]) -> None:
    port, reader = server
    for path in ("/", "/app.js", "/style.css", "/api/v1/team"):
        with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as client:
            client.request("GET", path)
            response = client.getresponse()
            assert response.status == 200 and response.read()
            assert response.getheader("Cache-Control") == "no-store"
            assert "frame-ancestors 'none'" in str(response.getheader("Content-Security-Policy"))
            assert response.getheader("Access-Control-Allow-Origin") is None
    with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as client:
        client.request("GET", "/api/v1/team?project_id=project_other")
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["selected_project_id"] == "project_other"
    for headers in (
        {"Host": "evil.example"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
    ):
        with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as client:
            client.request("GET", "/api/v1/team", headers=headers)
            assert client.getresponse().status == 403
    for path in ("/../../etc/passwd", "/api/v1/team?file=/etc/passwd", "/unknown"):
        with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as client:
            client.request("GET", path)
            assert client.getresponse().status == 404
    assert reader.reads == 2
    assert reader.selected == [None, "project_other"]
    reader.fail = True
    with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as client:
        client.request("GET", "/api/v1/team")
        response = client.getresponse()
        assert response.status == 503
        assert b"private" not in response.read()


def test_cli_missing_config_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ASE_CONFIG", str(tmp_path / "missing"))
    result = CliRunner().invoke(app, ["team", "serve"])
    assert result.exit_code == 2 and "Traceback" not in result.output
    assert CliRunner().invoke(app, ["team", "serve", "--help"]).exit_code == 0


def test_wire_schema_and_extra_fields() -> None:
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/team-snapshot.schema.json").read_text()
    )
    generated = TeamSnapshot.model_json_schema()
    assert {k: v for k, v in schema.items() if k not in {"$id", "$schema"}} == generated
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    payload = _Reader().snapshot().to_wire()
    validator.validate(payload)
    payload["agents_online"] = 99
    assert list(validator.iter_errors(payload))


def test_reader_selects_project_without_cross_project_writes(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path),
        team_id="team_test",
        team_name="Test",
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    team = TeamWorkspace.initialize(tmp_path, team_id="team_test", name="Test")
    team.project_registry().register(project_id="project_test", name="Test")
    team.project_registry().register(project_id="project_other", name="Other")
    before = _bytes(tmp_path)
    snapshot = ProductionTeamReader(config, {}).snapshot("project_other")
    assert snapshot.team_id == "team_test"
    assert snapshot.selected_project_id == "project_other"
    assert tuple((item.id, item.name) for item in snapshot.projects) == (
        ("project_other", "Other"),
        ("project_test", "Test"),
    )
    assert _bytes(tmp_path) == before


def test_ui_contracts() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the dependency-free DOM contract harness")
    result = subprocess.run(
        (node, "--test", str(Path(__file__).with_name("ui.test.cjs"))),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_selected_modules_waiting_and_symlink_rejection(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    checkpoint = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_" + "a" * 32,
            "team_id": team.manifest.team_id,
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_id": project.manifest.project_id,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "sequence": 1,
            "stage": JointStage.WAITING_HUMAN,
            "scope": DirectoryScope(
                units=(
                    DirectoryUnit(
                        id="unit_" + "b" * 16,
                        root=str(tmp_path / "code"),
                        selected_paths=("module-a", "module-b"),
                        base_revision=None,
                    ),
                )
            ),
            "title": "<script>alert(1)</script> password=hidden_secret",
            "submitted_at": datetime.now(UTC),
            "next_action": "SPEC_CONFLICT: human decision required",
        }
    )
    JointJournal(project.requirements_root).append(checkpoint, expected=None)
    reader = ProductionTeamReader(config, {})
    view = reader.snapshot()
    assert view.requests[0].scopes[0].selected_paths == ("module-a", "module-b")
    assert view.requests[0].blocker == checkpoint.next_action
    assert "hidden_secret" not in view.model_dump_json()
    assert not view.tasks
    link = project.requirements_root / ("delivery_multi_" + "c" * 32)
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(TeamReadError):
        reader.snapshot()


def test_retired_requirement_is_hidden_and_excluded_from_project_count(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    FileTeamWorkforceStore(TeamWorkforceWorkspace.from_team(team)).put_agent(
        AgentProfile(
            id="agent_team_manager",
            version="v0.1",
            display_name="Manager",
            capabilities=("manager",),
            eligible_roles=(TeamRole.MANAGER,),
            max_parallel_assignments=8,
            default_model_policy_id="model_policy_test",
        )
    )
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    repository_root = tmp_path / "code"
    repository_root.mkdir()
    repository = project.repository_registry().register(repository_root)
    native_store = FileProjectDeliveryCheckpointStore(
        repository.root / "state" / "project-deliveries"
    )
    native_delivery_id = "delivery_retired_child"
    now = datetime.now(UTC)
    native_store.put_intake(
        ProjectDeliveryIntake.create(
            delivery_id=native_delivery_id,
            repository_id=repository.repository_id,
            repository_root=str(repository_root),
            title="Retired child",
            requirement="Must disappear with its parent Requirement.",
            submitted_at=now,
        )
    )
    native_checkpoint = native_store.put(
        ProjectDeliveryCheckpoint.create(
            delivery_id=native_delivery_id,
            sequence=1,
            repository_id=repository.repository_id,
            repository_root=str(repository_root),
            stage=DeliveryStage.BLOCKED,
            stage_attempts=DeliveryStageAttempts(dispatching=1),
            next_action=DeliveryNextAction.REQUEST_HUMAN,
            failure_code=DeliveryFailureCode.CHECKPOINT_DRIFT,
            failure_summary="Retired child failure.",
            failed_stage=DeliveryStage.DISPATCHING,
            checkpointed_at=now,
        )
    )
    unit_id = "unit_" + "a" * 16
    checkpoint = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_" + "a" * 40,
            "team_id": team.manifest.team_id,
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_id": project.manifest.project_id,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "sequence": 1,
            "stage": JointStage.BLOCKED,
            "scope": DirectoryScope(
                units=(
                    DirectoryUnit(
                        id=unit_id,
                        root=str(repository_root),
                        selected_paths=(".",),
                        base_revision="b" * 40,
                    ),
                )
            ),
            "title": "Retired draft",
            "submitted_at": now,
            "children": (ChildDelivery(unit_id=unit_id, checkpoint=native_checkpoint),),
            "next_action": "Retired Requirement is blocked.",
        }
    )
    journal = JointJournal(project.requirements_root)
    journal.append(checkpoint, expected=None)
    RequirementRetirementStore(
        project.requirements_root,
        team_id=team.manifest.team_id,
        team_manifest_sha256=team.manifest.manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
    ).retire(checkpoint, reason="deleted", retired_at=datetime.now(UTC))

    snapshot = ProductionTeamReader(config, {}).snapshot()

    assert snapshot.requests == ()
    assert snapshot.tasks == ()
    assert len(snapshot.agents) == 1
    assert snapshot.agents[0].assigned_delivery_ids == ()
    assert snapshot.agents[0].current_stage_delivery_ids == ()
    assert snapshot.agents[0].history_delivery_ids == ()
    selected = next(item for item in snapshot.projects if item.id == project.manifest.project_id)
    assert selected.requirement_count == 0


def test_product_dialogue_is_projected_in_order_with_safe_attachment_metadata(
    tmp_path: Path,
) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    delivery_id = "delivery_multi_" + "d" * 32
    provisional = RequirementScreenshot(
        id="requirement_attachment_" + "e" * 40,
        project_id=project.manifest.project_id,
        delivery_id=delivery_id,
        source_name="checkout.png",
        media_type="image/png",
        source_bytes=2048,
        source_sha256="f" * 64,
        source_relative_path=("attachments/requirement_attachment_" + "e" * 40 + "/source.png"),
        uploaded_at=datetime.now(UTC),
        manifest_sha256="0" * 64,
    )
    screenshot = provisional.model_copy(update={"manifest_sha256": provisional.recompute_digest()})
    checkpoint = JointCheckpoint.seal(
        {
            "delivery_id": delivery_id,
            "team_id": team.manifest.team_id,
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_id": project.manifest.project_id,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "sequence": 1,
            "stage": JointStage.WAITING_PRODUCT_REPLY,
            "scope": DirectoryScope(
                units=(
                    DirectoryUnit(
                        id="unit_" + "d" * 16,
                        root=str(tmp_path / "code"),
                        selected_paths=(".",),
                        base_revision=None,
                    ),
                )
            ),
            "title": "Checkout flow",
            "requirement": "Improve checkout",
            "dialogue": (
                DialogueMessage(
                    speaker="user",
                    text="Support password=private-secret",
                    screenshots=(screenshot,),
                ),
                DialogueMessage(
                    speaker="product",
                    text="Which environments must be supported?",
                ),
            ),
            "submitted_at": datetime.now(UTC),
            "next_action": "Reply to the Product Agent questions.",
        }
    )
    JointJournal(project.requirements_root).append(checkpoint, expected=None)

    request = ProductionTeamReader(config, {}).snapshot().requests[0]

    assert tuple((turn.sequence, turn.speaker) for turn in request.dialogue) == (
        (1, "user"),
        (2, "product"),
    )
    assert "private-secret" not in request.dialogue[0].text
    assert request.dialogue[0].attachments[0].name == "checkout.png"
    assert request.dialogue[0].attachments[0].sha256 == "f" * 64
    assert request.dialogue[1].text == "Which environments must be supported?"


@pytest.mark.mysql
def test_single_repository_entry_remains_visible(tmp_path: Path) -> None:
    config, environment, _, projects = setup_host(tmp_path)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    checkpoint = (
        host.project_entry()
        .start(
            StartProjectDelivery(
                repository_root=str(projects[0]),
                requirement="Update greeting",
                title="Single repository",
            )
        )
        .checkpoint
    )
    snapshot = ProductionTeamReader(config, environment).snapshot()
    assert len(snapshot.requests) == 1 and len(snapshot.tasks) == 1
    request, task = snapshot.requests[0], snapshot.tasks[0]
    assert request.id == task.id == checkpoint.delivery_id
    assert request.title == "Single repository"
    assert request.scopes[0].root == str(projects[0])
    assert request.scopes[0].selected_paths == (".",)
    assert request.blocker and task.status == "WAITING_PRODUCT_APPROVAL"
    assert task.assignments == ()


@pytest.mark.mysql
def test_active_candidate_verification_is_visible_as_qa_work(tmp_path: Path) -> None:
    config, environment, _, projects = setup_host(tmp_path)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    service = host.project_entry()
    started = service.start(
        StartProjectDelivery(
            repository_root=str(projects[0]),
            requirement="Update greeting",
            title="Visible candidate verification",
        )
    ).checkpoint
    product = (
        service.reply(
            ReplyToProduct(
                delivery_id=started.delivery_id,
                expected_checkpoint_sha256=started.checkpoint_sha256,
                message="Update greeting",
            )
        ).checkpoint
        if started.stage == "WAITING_PRODUCT_REPLY"
        else started
    )
    completed = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="human-verification-view",
        )
    ).checkpoint
    assert completed.stage == "DONE"

    dsn = config.require_mysql_dsn(environment)
    with open_mysql_connection(dsn) as connection, connection.cursor(DictCursor) as cursor:
        cursor.execute("SELECT * FROM dispatch_commits WHERE task_id = %s", (completed.task_id,))
        row = cursor.fetchone()
        assert row is not None
        dispatch = _decode_commit(row)
        suffix = hashlib.sha256(str(completed.task_id).encode()).hexdigest()[:16]
        execution_task_id = f"task_verify_team_view_{suffix}"
        phases = []
        for index, phase in enumerate(dispatch.phases[1:]):
            assignment_id = f"assignment_verify_team_view_{suffix}_{index}"
            lease_id = f"lease_verify_team_view_{suffix}_{index}"
            phases.append(
                phase.model_copy(
                    update={
                        "assignment": phase.assignment.model_copy(
                            update={
                                "id": assignment_id,
                                "lease_id": lease_id,
                                "task_id": execution_task_id,
                            }
                        ),
                        "lease": phase.lease.model_copy(
                            update={
                                "id": lease_id,
                                "assignment_id": assignment_id,
                                "task_id": execution_task_id,
                            }
                        ),
                    }
                )
            )
        reservation = VerificationReservation(
            plan_sha256=hashlib.sha256(execution_task_id.encode()).hexdigest(),
            repository_id=dispatch.repository_id,
            source_task_id=dispatch.task_id,
            task_id=execution_task_id,
            workforce_snapshot_sha256=dispatch.workforce_snapshot_sha256,
            phases=tuple(phases),
            committed_at=datetime.now(UTC),
        )
        cursor.execute(
            "INSERT INTO verification_reservations "
            "(plan_sha256, payload_json, completion_sha256) VALUES (%s, %s, NULL)",
            (reservation.plan_sha256, reservation.model_dump_json()),
        )
        connection.commit()

    snapshot = ProductionTeamReader(config, environment).snapshot()
    verification = next(task for task in snapshot.tasks if task.task_id == execution_task_id)
    assert not verification.terminal
    assert verification.status == "VERIFY_QA"
    assert verification.scope.root == str(projects[0])
    assert (
        next(item for item in verification.assignments if item.current_stage).role is AgentRole.QA
    )
    qa = next(agent for agent in snapshot.agents if agent.id == "agent_team_qa")
    assert verification.id in qa.assigned_delivery_ids
    assert verification.id in qa.current_stage_delivery_ids
