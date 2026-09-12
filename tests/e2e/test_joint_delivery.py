"""Joint production path with real MySQL, Git candidates, and cross-repo test execution."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn

import pytest
from typer.testing import CliRunner

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.cli import app
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    DeliveryCheckpointStale,
    ReplyToProduct,
    ResumeProjectDelivery,
)
from ai_software_engineer.manager.production_agents import (
    ExecutionPlanDraft,
    TechnicalDesignDraft,
)
from ai_software_engineer.manager.production_backend import StructuredClientFactory
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.scope import DirectoryScope
from ai_software_engineer.multi_directory.service import CreateRequirement
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedDeliveryFactory,
    _ScriptedStructuredClient,
)


class JointModels(StructuredClientFactory, StructuredModelClient):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def for_project(self, repository_root: Path) -> StructuredModelClient:
        return self

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
    ) -> StructuredModelResult:
        title = str(output_schema["title"])
        self.calls.append(title)
        simple = _ScriptedStructuredClient()
        if title == "ProductDraft":
            return simple.complete(
                instructions=instructions,
                input_payload=input_payload,
                output_schema=output_schema,
                timeout_seconds=timeout_seconds,
            )
        scope = DirectoryScope.model_validate(input_payload["scope"])
        first, second = scope.units
        if title == "JointTechnicalDesign":
            draft = simple.complete(
                instructions="",
                input_payload={},
                output_schema=TechnicalDesignDraft.model_json_schema(),
                timeout_seconds=1,
            ).payload
            return StructuredModelResult(
                payload={
                    "product_spec_sha256": input_payload["product_spec_sha256"],
                    "summary": "Keep producer and consumer greetings compatible.",
                    "units": [
                        {"unit_id": unit.id, "requirement_ids": ["req_001"], "design": draft}
                        for unit in scope.units
                    ],
                    "interfaces": [
                        {
                            "id": "greeting_contract",
                            "producer": first.id,
                            "consumers": [second.id],
                            "specification": "Same greeting in both repos.",
                            "compatibility": "Verify both exact candidates together.",
                        }
                    ],
                },
                duration_ms=0,
            )
        assert title == "JointExecutionPlan"
        plan = simple.complete(
            instructions="",
            input_payload={},
            output_schema=ExecutionPlanDraft.model_json_schema(),
            timeout_seconds=1,
        ).payload
        return StructuredModelResult(
            payload={
                "design_sha256": input_payload["design_sha256"],
                "units": [
                    {"unit_id": first.id, "plan": plan},
                    {"unit_id": second.id, "depends_on": [first.id], "plan": plan},
                ],
                "integration_checks": [
                    {
                        "id": "joint_greeting",
                        "unit_id": second.id,
                        "consumes": [first.id, second.id],
                        "acceptance_ids": ["ac_001_001"],
                        "interface_ids": ["greeting_contract"],
                        "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"],
                    }
                ],
            },
            duration_ms=0,
        )


def setup_host(
    tmp_path: Path, *, fail_integration: bool = False
) -> tuple[ProductionConfig, dict[str, str], JointModels, tuple[Path, Path]]:
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    projects = (tmp_path / "backend", tmp_path / "elsewhere" / "frontend")
    for project in projects:
        project.mkdir(parents=True)
        _git("init", cwd=project)
        (project / "hello.txt").write_text("hello\n")
        (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.1.0"\n')
        (project / "tests").mkdir()
        expected = "deliberate-failure" if fail_integration else "hello from the team\n"
        (project / "tests" / "test_joint.py").write_text(
            "import os, unittest\nfrom pathlib import Path\n"
            "class JointTest(unittest.TestCase):\n"
            "    def test_candidates(self):\n"
            "        roots = [Path(v) for k, v in os.environ.items() "
            "if k.startswith('ASE_UNIT_')]\n"
            "        self.assertEqual(len(roots), 2)\n"
            "        self.assertNotIn('PRIVATE_TEST_SECRET', os.environ)\n"
            "        values = [(p/'hello.txt').read_text() for p in roots]\n"
            f"        self.assertEqual(values, [{expected!r}]*2)\n"
        )
        _git("add", ".", cwd=project)
        _git("commit", "-m", "base", cwd=project)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    environment = {
        "ASE_MYSQL_DSN": dsn,
        "PATH": os.environ.get("PATH", os.defpath),
        "PRIVATE_TEST_SECRET": "must-not-be-inherited",
    }
    return config, environment, JointModels(), projects


@pytest.mark.mysql
@pytest.mark.parametrize("fail_integration", [False, True])
def test_joint_cli_to_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_integration: bool
) -> None:
    config, environment, models, projects = setup_host(tmp_path, fail_integration=fail_integration)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    service = host.requirement_entry()
    monkeypatch.setattr("ai_software_engineer.cli.requirement_entry", lambda: service)
    cli = CliRunner()
    created = cli.invoke(
        app, ["request", "create", *map(str, projects), "--name", "Joint greeting"]
    )
    assert created.exit_code == 0, created.output
    initial = JointCheckpoint.model_validate(json.loads(created.output)["checkpoint"])
    assert initial.stage is JointStage.READY_FOR_DISCUSSION
    assert not models.calls
    discussed = cli.invoke(
        app,
        [
            "request",
            "discuss",
            initial.delivery_id,
            "--checkpoint",
            initial.checkpoint_sha256,
            "--message",
            "Update both greetings together",
        ],
    )
    assert discussed.exit_code == 0, discussed.output
    product = JointCheckpoint.model_validate(json.loads(discussed.output)["checkpoint"])
    assert product.stage is JointStage.WAITING_PRODUCT_APPROVAL
    with pytest.raises(DeliveryCheckpointStale, match="checkpoint"):
        service.approve(
            ApproveProductSpec(
                delivery_id=product.delivery_id,
                expected_checkpoint_sha256=initial.checkpoint_sha256,
                approval_reference="stale-approval",
            )
        )
    assert models.calls == ["ProductDraft"]
    # Restart the entire Host before approval, not merely the Python service object.
    reopened = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    ).requirement_entry()
    result = reopened.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="joint-user-approval",
        )
    )
    checkpoint = result.checkpoint
    assert checkpoint.stage is (JointStage.BLOCKED if fail_integration else JointStage.DONE)
    assert len(checkpoint.children) == 2
    assert models.calls == ["ProductDraft", "JointTechnicalDesign", "JointExecutionPlan"]
    assert checkpoint.integration is not None
    assert (checkpoint.integration.checks[0].returncode != 0) == fail_integration
    for child in checkpoint.children:
        root = Path(child.checkpoint.repository_root)
        assert child.checkpoint.candidate_revision
        assert (root / "hello.txt").read_text() == "hello\n"
        assert _git_output("status", "--porcelain", cwd=root) == ""
        assert (
            _git_output("show", child.checkpoint.candidate_revision + ":hello.txt", cwd=root)
            == "hello from the team"
        )
    replay = reopened.resume(ResumeProjectDelivery(delivery_id=checkpoint.delivery_id))
    assert replay.checkpoint == checkpoint
    assert len(models.calls) == 3


@pytest.mark.mysql
def test_serial_joint_deliveries_do_not_exhaust_finished_agent_capacity(tmp_path: Path) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    service = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    ).requirement_entry()
    # Ten native Tasks exceed the eight slots of each organization Agent before lease expiry.
    for index in range(5):
        created = service.create(
            CreateRequirement(
                name=f"Continuous delivery {index}", repository_roots=tuple(map(str, projects))
            )
        ).checkpoint
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
                approval_reference=f"approval-{index}",
            )
        ).checkpoint
        assert done.stage is JointStage.DONE, done.next_action
        assert len(done.children) == 2
    assert len(models.calls) == 15


@pytest.mark.mysql
def test_native_completed_child_is_reused_after_parent_checkpoint_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    service = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    ).requirement_entry()
    created = service.create(
        CreateRequirement(name="Recover joint", repository_roots=tuple(map(str, projects)))
    )
    product = service.reply(
        ReplyToProduct(
            delivery_id=created.checkpoint.delivery_id,
            expected_checkpoint_sha256=created.checkpoint.checkpoint_sha256,
            message="Update greetings",
        )
    )
    original = service.backend.deliver
    completed_ids: list[str] = []

    def crash_after_child(checkpoint: JointCheckpoint, unit_id: str) -> NoReturn:
        child = original(checkpoint, unit_id)
        completed_ids.append(child.checkpoint.delivery_id)
        raise RuntimeError("simulated process crash before parent publication")

    monkeypatch.setattr(service.backend, "deliver", crash_after_child)
    with pytest.raises(RuntimeError, match="simulated"):
        service.approve(
            ApproveProductSpec(
                delivery_id=product.checkpoint.delivery_id,
                expected_checkpoint_sha256=product.checkpoint.checkpoint_sha256,
                approval_reference="approved",
            )
        )
    reopened = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    ).requirement_entry()
    done = reopened.resume(
        ResumeProjectDelivery(delivery_id=product.checkpoint.delivery_id)
    ).checkpoint
    assert done.stage is JointStage.DONE
    assert done.children[0].checkpoint.delivery_id == completed_ids[0]
    assert models.calls == ["ProductDraft", "JointTechnicalDesign", "JointExecutionPlan"]
