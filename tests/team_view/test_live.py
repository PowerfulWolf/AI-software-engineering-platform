"""Real production facts, no live providers and no dashboard writes."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest
from jsonschema import Draft202012Validator, FormatChecker
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
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from ai_software_engineer.runtime_workspace import OrganizationWorkspace
from ai_software_engineer.team_view.models import TeamReadError, TeamSnapshot
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.team_view.server import create_team_server
from tests.e2e.test_joint_delivery import setup_host
from tests.project_manager.test_production_backend import (
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
    _ScriptedDeliveryFactory,
)


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
    fail = False
    reads = 0

    def snapshot(self) -> TeamSnapshot:
        self.reads += 1
        if self.fail:
            raise RuntimeError("password=private-must-not-leak")
        return TeamSnapshot(as_of=datetime.now(UTC), company_id="company_test", company_name="Test")


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
    assert reader.reads == 1
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
