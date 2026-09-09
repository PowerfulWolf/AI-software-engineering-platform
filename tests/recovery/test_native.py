"""Native failed-delivery inspection with real MySQL/Git and offline Agents."""

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    StoredContextResolver,
)
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.design import FileDesignRecordStore
from ai_software_engineer.domain import AgentDefinition, AgentRole
from ai_software_engineer.multi_directory.service import CreateRequirementProject
from ai_software_engineer.planning import FileExecutionPlanStore
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.project_manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from ai_software_engineer.project_manager.store import FileProjectPreparationStore
from ai_software_engineer.recovery import RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.native import NativeRecoverySourceReader
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from tests.e2e.test_joint_delivery import setup_host
from tests.project_manager.test_production_backend import _git, _ScriptedClientFactory
from tests.project_manager.test_production_backend import mysql_dsn as mysql_dsn


class InterruptedCoder:
    def __init__(self, root: Path, requests: list[AgentRequest]) -> None:
        self.root, self.requests = root, requests

    def run(self, request: AgentRequest) -> AgentResult:
        assert request.role is AgentRole.CODER
        self.requests.append(request)
        (self.root / "hello.txt").write_text("partially implemented\n")
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=AgentErrorCode.POLICY_VIOLATION,
                message="offline interrupted Coder",
                transient=False,
            ),
        )


class InterruptedFactory:
    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []

    def create(
        self,
        *,
        route: ProviderRouteConfig,
        definition: AgentDefinition,
        binding: RoleWorktreeBinding,
        context_resolver: StoredContextResolver,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> AgentAdapter:
        return InterruptedCoder(binding.worktree.path, self.requests)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.mysql
def test_native_source_is_verified_read_only_and_rejects_corruption(
    tmp_path: Path, mysql_dsn: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=project)
    _git("add", "hello.txt", cwd=project)
    _git("commit", "-m", "initial", cwd=project)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
        live_model_execution=True,
    )
    environment = {"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")}
    factory = InterruptedFactory()
    host = OrganizationTeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=factory,
    )
    entry = host.project_entry()
    started = entry.start(
        StartProjectDelivery(project_root=str(project), requirement="Change greeting.")
    )
    failed = entry.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="test-approval",
        )
    )
    cp = failed.checkpoint
    assert cp.stage.value == "BLOCKED" and cp.candidate_revision is None
    assert len(factory.requests) == 1
    request = factory.requests[0]
    scope = RecoveryScope(
        company_id=config.company_id,
        project_id=cp.project_id,
        project_root=str(project),
        delivery_id=cp.delivery_id,
    )
    sidecar = (
        Path(config.platform_root) / "companies" / config.company_id / "projects" / cp.project_id
    )
    before = _snapshot(Path(config.platform_root))
    original = _snapshot(project)
    reader = NativeRecoverySourceReader(config, environment)
    arguments = {"failed_run_id": request.run_id, "failed_context_id": request.context_manifest_id}
    observed = reader.inspect(scope, **arguments)
    assert reader.discover_failed_coder(scope) == observed
    assert observed.source.task_id == request.task_id
    assert observed.source.task_revision == cp.task_revision
    assert observed.source.checkpoint_sha256 == cp.checkpoint_sha256
    assert observed.source.parent_delivery_id is None
    assert observed.permissions == request.permissions
    readonly_product = FileProductRecordStore(sidecar / "state/product", read_only=True)
    with pytest.raises(RuntimeError, match="read-only"):
        readonly_product.put_product_spec(observed.product)
    with pytest.raises(RuntimeError, match="read-only"):
        readonly_product.put_approval(observed.approval)
    with pytest.raises(RuntimeError, match="read-only"), readonly_product.request_revision_fence():
        pytest.fail("read-only store acquired a write fence")
    with pytest.raises(RuntimeError, match="read-only"):
        FileDesignRecordStore(sidecar / "state/design", read_only=True).put_design(observed.design)
    with pytest.raises(RuntimeError, match="read-only"):
        FileExecutionPlanStore(sidecar / "state/planning", read_only=True).put_execution_plan(
            observed.plan
        )
    context_store = FileContextStore(sidecar / "contexts", read_only=True)
    with pytest.raises(RuntimeError, match="read-only"):
        context_store.put(context_store.get(request.context_manifest_id))
    with pytest.raises(RuntimeError, match="read-only"):
        FileProjectPreparationStore(sidecar / "policy", read_only=True).put(observed.preparation)
    assert NativeRecoverySourceReader(config, environment).inspect(scope, **arguments) == observed
    assert _snapshot(Path(config.platform_root)) == before
    assert _snapshot(project) == original
    assert len(factory.requests) == 1
    with pytest.raises(RecoveryRejected):
        reader.inspect(scope.model_copy(update={"company_id": "company_other"}), **arguments)
    with pytest.raises(RecoveryRejected):
        reader.inspect(scope, **{**arguments, "failed_run_id": "run_missing"})
    with pytest.raises(RecoveryRejected):
        reader.inspect(scope, **{**arguments, "failed_context_id": "ctx_" + "0" * 64})
    for category in (
        "product/specs",
        "product/approvals",
        "design/checkpoints",
        "planning/checkpoints",
    ):
        record = next((sidecar / "state" / category).rglob("*.json"))
        original_bytes = record.read_bytes()
        record.write_text("{}")
        with pytest.raises(RecoveryRejected, match="original delivery facts"):
            reader.inspect(scope, **arguments)
        record.write_bytes(original_bytes)
    assert reader.inspect(scope, **arguments) == observed
    assert _snapshot(project) == original


def test_inspection_does_not_initialize_missing_platform(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    scope = RecoveryScope(
        company_id=config.company_id,
        project_id="project_missing",
        delivery_id="delivery_missing",
        project_root=str(tmp_path / "project"),
    )
    with pytest.raises(RecoveryRejected):
        NativeRecoverySourceReader(config, {}).inspect(
            scope, failed_run_id="run_missing", failed_context_id="ctx_" + "0" * 64
        )
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("kind", ["product", "design", "planning", "preparation", "context"])
def test_readonly_store_never_initializes(tmp_path: Path, kind: str) -> None:
    store_type = {
        "product": FileProductRecordStore,
        "design": FileDesignRecordStore,
        "planning": FileExecutionPlanStore,
        "preparation": FileProjectPreparationStore,
        "context": FileContextStore,
    }[kind]
    root = tmp_path / "missing"
    with pytest.raises(RuntimeError):
        store_type(root, read_only=True)
    assert not root.exists()
    root.mkdir()
    store_type(root, read_only=True)
    assert list(root.iterdir()) == []


@pytest.mark.mysql
def test_joint_parent_cannot_be_omitted_from_source_lineage(tmp_path: Path) -> None:
    from ai_software_engineer.project_manager.delivery import ReplyToProduct

    config, environment, models, projects = setup_host(tmp_path)
    factory = InterruptedFactory()
    entry = OrganizationTeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=factory,
    ).requirement_entry()
    created = entry.create(
        CreateRequirementProject(name="Interrupted joint", project_roots=tuple(map(str, projects)))
    ).checkpoint
    product = entry.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update both greetings",
        )
    ).checkpoint
    parent = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="joint-approved",
        )
    ).checkpoint
    assert parent.stage == "BLOCKED" and len(factory.requests) == 1
    cp = parent.children[0].checkpoint
    request = factory.requests[0]
    scope = RecoveryScope(
        company_id=config.company_id,
        project_id=cp.project_id,
        project_root=cp.project_root,
        delivery_id=cp.delivery_id,
    )
    before = _snapshot(Path(config.platform_root))
    reader = NativeRecoverySourceReader(config, environment)
    observed = reader.inspect(
        scope, failed_run_id=request.run_id, failed_context_id=request.context_manifest_id
    )
    assert observed.source.parent_delivery_id == parent.delivery_id
    assert observed.source.parent_checkpoint_sha256 == parent.checkpoint_sha256
    assert _snapshot(Path(config.platform_root)) == before
    assert len(models.calls) == 3
    parent_path = (
        Path(config.platform_root)
        / "companies"
        / config.company_id
        / "requests"
        / parent.delivery_id
    )
    original = next(parent_path.glob("*.json"))
    original.write_text("{}")
    with pytest.raises(RecoveryRejected):
        reader.inspect(
            scope, failed_run_id=request.run_id, failed_context_id=request.context_manifest_id
        )
