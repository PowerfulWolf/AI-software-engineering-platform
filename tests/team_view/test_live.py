"""Real production facts, no live providers and no dashboard writes."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pymysql.cursors import DictCursor
from typer.testing import CliRunner

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.cli import app
from ai_software_engineer.company_workspace import CompanyWorkspace
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain.enums import AgentRole, OrganizationRole
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import CreateRequirementProject
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.project_manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    StartProjectDelivery,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.project_manager.dispatch import VerificationReservation
from ai_software_engineer.project_manager.mysql_dispatch_authority import _decode_commit
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from ai_software_engineer.runtime_workspace import OrganizationWorkspace
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.team_view.models import CompanyView, TeamReadError, TeamSnapshot
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.team_view.server import create_team_server
from tests.e2e.test_joint_delivery import setup_host
from tests.project_manager.test_production_backend import (
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
    _ScriptedDeliveryFactory,
)
from tests.recovery.test_native import InterruptedFactory


def _bytes(root: Path) -> dict[str, str]:
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()
    }


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


def test_empty_company_needs_no_database_or_models(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    CompanyWorkspace.initialize(tmp_path, company_id=config.company_id, name=config.company_name)
    OrganizationWorkspace.initialize(
        tmp_path / "organization", organization_id="organization_test", created_at=datetime.now(UTC)
    )
    before = _bytes(tmp_path)
    snapshot = ProductionTeamReader(config, {}).snapshot()
    assert not snapshot.agents and not snapshot.tasks and not snapshot.requests
    assert _bytes(tmp_path) == before


@pytest.mark.mysql
def test_joint_reader_accepts_committed_child_checkpoint_as_a_valid_prefix(
    tmp_path: Path,
) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    host = OrganizationTeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=InterruptedFactory(),
    )
    service = host.requirement_entry()
    created = service.create(
        CreateRequirementProject(
            name="Advanced native child",
            project_roots=tuple(map(str, projects)),
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
    sidecar = (
        host.company_workspace.root / "projects" / child.project_id / "state/project-deliveries"
    )
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


@pytest.mark.mysql
def test_real_inflight_joint_and_terminal_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    host = OrganizationTeamHost(
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
        before = _bytes(Path(config.platform_root) / "companies")
        snapshot = reader.snapshot()
        assert _bytes(Path(config.platform_root) / "companies") == before
        current = next(t for t in snapshot.tasks if t.task_id == request.task_id)
        assert sum(a.current_stage for a in current.assignments) == 1
        assert next(a.role for a in current.assignments if a.current_stage) == request.role
        assert current.scope.root in tuple(map(str, projects))
        assert current.execution_liveness == "UNKNOWN"
        assert len(snapshot.requests) >= 1
        seen.append((request.role, snapshot))
        return original_run(adapter, request)

    monkeypatch.setattr(_ScriptedDeliveryAdapter, "run", observe)
    for index in range(2):
        created = service.create(
            CreateRequirementProject(
                name=f"Live team request {index}",
                project_roots=tuple(map(str, projects)),
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
        if set(agent.roles)
        & {OrganizationRole.CODER, OrganizationRole.QA, OrganizationRole.REVIEWER}
    )
    upstream_agents = tuple(agent for agent in final.agents if agent not in delivery_agents)
    assert all(len(a.history_delivery_ids) == 4 for a in delivery_agents)
    assert all(not a.history_delivery_ids for a in upstream_agents)
    assert all(t.candidate_revision and len(t.assignments) == 3 for t in final.tasks)
    assert all(t.timeline and t.documents for t in final.tasks)
    assert all(len(t.runs) == 3 and all(r.model == "gpt-5.5" for r in t.runs) for t in final.tasks)
    assert all(len(r.scopes) == 2 and len(r.documents) == 4 for r in final.requests)

    # Other company requests are not scanned, even if corrupted.
    foreign = Path(config.platform_root) / "companies" / "company_foreign" / "requests"
    foreign.mkdir(parents=True)
    (foreign / "bad.json").write_text("bad")
    assert reader.snapshot().tasks == final.tasks

    company = host._company
    journal = JointJournal(company.requests_root, read_only=True)
    with pytest.raises(ValueError, match="read-only"):
        journal.append(done, expected=done.checkpoint_sha256)
    checkpoint_file = next(company.requests_root.glob("delivery_multi_*/*.json"))
    checkpoint_file.write_text("{}")
    with pytest.raises(TeamReadError):
        reader.snapshot()


class _Reader:
    def __init__(self) -> None:
        self.fail = False
        self.reads = 0
        self.selected: list[str | None] = []

    def snapshot(self, company_id: str | None = None) -> TeamSnapshot:
        self.reads += 1
        self.selected.append(company_id)
        if self.fail:
            raise RuntimeError("password=private-must-not-leak")
        selected = company_id or "company_test"
        return TeamSnapshot(
            as_of=datetime.now(UTC),
            company_id=selected,
            company_name="Other" if selected == "company_other" else "Test",
            companies=(
                CompanyView(id="company_test", name="Test"),
                CompanyView(id="company_other", name="Other"),
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
        client.request("GET", "/api/v1/team/company_other")
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["company_id"] == "company_other"
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
    assert reader.selected == [None, "company_other"]
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


def test_reader_selects_prepared_company_without_cross_company_writes(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path),
        company_id="company_test",
        company_name="Test",
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    CompanyWorkspace.initialize(tmp_path, company_id="company_test", name="Test")
    CompanyWorkspace.initialize(tmp_path, company_id="company_other", name="Other")
    OrganizationWorkspace.initialize(
        tmp_path / "organization", organization_id="organization_test", created_at=datetime.now(UTC)
    )
    before = _bytes(tmp_path)
    snapshot = ProductionTeamReader(config, {}).snapshot("company_other")
    assert snapshot.company_id == "company_other"
    assert tuple((item.id, item.name) for item in snapshot.companies) == (
        ("company_other", "Other"),
        ("company_test", "Test"),
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
    company = CompanyWorkspace.initialize(
        config.platform_root, company_id=config.company_id, name=config.company_name
    )
    OrganizationWorkspace.initialize(
        Path(config.platform_root) / "organization",
        organization_id="organization_test",
        created_at=datetime.now(UTC),
    )
    checkpoint = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_" + "a" * 32,
            "company_id": company.manifest.company_id,
            "company_manifest_sha256": company.manifest.manifest_sha256,
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
    JointJournal(company.requests_root).append(checkpoint, expected=None)
    reader = ProductionTeamReader(config, {})
    view = reader.snapshot()
    assert view.requests[0].scopes[0].selected_paths == ("module-a", "module-b")
    assert view.requests[0].blocker == checkpoint.next_action
    assert "hidden_secret" not in view.model_dump_json()
    assert not view.tasks
    link = company.requests_root / ("delivery_multi_" + "c" * 32)
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(TeamReadError):
        reader.snapshot()


@pytest.mark.mysql
def test_single_repository_entry_remains_visible(tmp_path: Path) -> None:
    config, environment, _, projects = setup_host(tmp_path)
    host = OrganizationTeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    checkpoint = (
        host.project_entry()
        .start(
            StartProjectDelivery(
                project_root=str(projects[0]),
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
    host = OrganizationTeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    service = host.project_entry()
    started = service.start(
        StartProjectDelivery(
            project_root=str(projects[0]),
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
            project_id=dispatch.project_id,
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
