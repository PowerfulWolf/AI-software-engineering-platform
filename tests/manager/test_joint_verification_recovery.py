"""Same-Requirement correction needs genuine stopped native lineage, never a fake success."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.manager.delivery import DeliveryCheckpointStale, ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_agents import ProductDraft
from ai_software_engineer.manager.production_backend import ProductionProjectDeliveryBackend
from ai_software_engineer.manager.production_rules import production_rules
from ai_software_engineer.multi_directory.models import (
    JointApproval,
    JointExecutionPlan,
    JointProductSpec,
    JointStage,
    JointTechnicalDesign,
    digest,
)
from ai_software_engineer.multi_directory.production import ProductionJointBackend
from ai_software_engineer.multi_directory.service import CreateRequirement, JointDeliveryService
from ai_software_engineer.multi_directory.verification_recovery import (
    UnstartedDesignCorrectionRejected,
    unstarted_design_rejection,
)
from ai_software_engineer.multi_directory.verification_recovery_production import (
    ProductionUnstartedDesignVerifier,
)
from ai_software_engineer.runtime_workspace import TeamWorkforceWorkspace
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.e2e.test_joint_delivery import JointModels
from tests.manager.test_joint_verification_admission import inspected_design
from tests.manager.test_production_backend import _git, _git_output


def seeded_native_failure(tmp_path: Path):
    roots = (tmp_path / "a", tmp_path / "b")
    for root in roots:
        root.mkdir()
        _git("init", cwd=root)
        (root / "hello.txt").write_text("hello\n")
        (root / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.1.0"\n')
        _git("add", ".", cwd=root)
        _git("commit", "-m", "base", cwd=root)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(provider="codex", model="fake", kind=ModelProviderKind.CODEX_CLI),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().register(project_id="project_test", name="Test")
    registry = project.repository_registry()
    models = JointModels()
    common = {
        "config": config,
        "environment": {"ASE_MYSQL_DSN": "mysql://fake:fake@localhost/unused"},
        "organization": TeamWorkforceWorkspace.from_team(team),
        "registry": registry,
        "platform_rules": production_rules(team, (), ()),
    }
    native = ProductionProjectDeliveryBackend(**common, structured_clients=models)

    def factory(clients, sources, verifier, prepared, source):
        return ProductionProjectDeliveryBackend(
            **common,
            structured_clients=clients,
            delivery_context_sources=sources,
            human_decision_verifier=verifier,
            frozen_preparation=prepared,
            frozen_source_revision=source,
            trusted_plan_projection=True,
            trusted_legacy_product_projection=True,
        )

    backend = ProductionJointBackend(
        native=native, factory=factory, clients=models, team=team, project=project, environment={}
    )
    service = JointDeliveryService(backend=backend, team=team, project=project)
    ready = service.create(
        CreateRequirement(name="Legacy joint validation", repository_roots=tuple(map(str, roots)))
    ).checkpoint
    draft = ProductDraft.model_validate(
        models.complete(
            instructions="",
            input_payload={},
            output_schema=ProductDraft.model_json_schema(),
            timeout_seconds=1,
        ).payload
    )
    product = JointProductSpec(scope_sha256=digest(ready.scope), version=1, product=draft)
    design = JointTechnicalDesign.model_validate(
        models.complete(
            instructions="",
            input_payload={"scope": ready.scope.to_wire(), "product_spec_sha256": digest(product)},
            output_schema=JointTechnicalDesign.model_json_schema(),
            timeout_seconds=1,
        ).payload
    )
    design = inspected_design(design, "source", ("source_inspection", "integration"))
    plan = JointExecutionPlan.model_validate(
        models.complete(
            instructions="",
            input_payload={"scope": ready.scope.to_wire(), "design_sha256": digest(design)},
            output_schema=JointExecutionPlan.model_json_schema(),
            timeout_seconds=1,
        ).payload
    )
    first = plan.units[0]
    graph = first.plan.work_graph
    package = graph.packages[0]
    graph = graph.model_copy(
        update={
            "packages": (
                package.model_copy(
                    update={
                        "tests": (
                            package.tests[0].model_copy(
                                update={"id": "test_source", "level": "source_inspection"}
                            ),
                            package.tests[0].model_copy(
                                update={"id": "test_integration", "level": "integration"}
                            ),
                        )
                    }
                ),
            )
        }
    )
    plan = plan.model_copy(
        update={
            "units": (
                first.model_copy(
                    update={"plan": first.plan.model_copy(update={"work_graph": graph})}
                ),
                *plan.units[1:],
            )
        }
    )
    # Reproduce old published input, which intentionally remains readable after
    # adding the publication-only validator. Actual native rejection is not mocked.
    accepted = service._save(
        ready,
        stage=JointStage.DELIVERING,
        product_spec=product,
        approval=JointApproval(
            product_spec_sha256=digest(product),
            checkpoint_sha256=ready.checkpoint_sha256,
            reference="exact-test-product-approval",
            approved_at=datetime.now(UTC),
        ),
        design=design,
        plan=plan,
        attempts={"product": 1, "design": 1, "plan": 1},
    )
    child = backend.deliver(accepted, accepted.scope.units[0].id)
    assert child.checkpoint.stage is DeliveryStage.BLOCKED
    assert "ac_001_001" in child.checkpoint.failure_summary
    assert "检查不能替代" in child.checkpoint.failure_summary
    blocked = service._save(
        accepted, stage=JointStage.BLOCKED, children=(child,), next_action="设计契约失败"
    )
    return service, backend, blocked


def inventory(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_production_proof_reads_genuine_failed_receipt_without_mutation(tmp_path: Path) -> None:
    service, _, blocked = seeded_native_failure(tmp_path)
    before = inventory(service.project.root)
    proof = ProductionUnstartedDesignVerifier(service.project).verify(blocked)
    assert proof.checkpoint_sha256 == blocked.checkpoint_sha256
    assert len(proof.native_run_sha256s) == 1
    assert inventory(service.project.root) == before


def test_same_requirement_continue_preserves_history_approval_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, blocked = seeded_native_failure(tmp_path)
    original = inventory(service.project.root)
    # Stop exactly before invoking the new Designer. No role verdict is fabricated.
    monkeypatch.setattr(service, "_advance", lambda checkpoint: checkpoint)
    resumed = service.resume(ResumeProjectDelivery(delivery_id=blocked.delivery_id)).checkpoint
    assert resumed.stage is JointStage.DESIGNING and resumed.delivery_id == blocked.delivery_id
    assert resumed.approval == blocked.approval and resumed.product_spec == blocked.product_spec
    assert resumed.attempts == blocked.attempts
    assert resumed.design_feedback == blocked.design
    assert not resumed.children and resumed.design is None and resumed.plan is None
    assert "ac_001_001" in resumed.next_action
    assert service.journal.history(blocked.delivery_id)[-2] == blocked
    after = inventory(service.project.root)
    assert all(after[path] == data for path, data in original.items())


@pytest.mark.parametrize(
    "tamper",
    ["checkpoint", "source", "input_hash", "context", "request", "approved_reference", "receipt"],
)
def test_unverifiable_native_history_refuses_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    from ai_software_engineer.design.store import FileDesignRecordStore
    from ai_software_engineer.product.store import FileProductRecordStore

    service, _, blocked = seeded_native_failure(tmp_path)
    before = inventory(service.project.root)
    if tamper == "checkpoint":
        blocked = blocked.model_copy(update={"checkpoint_sha256": "f" * 64})
    elif tamper == "source":
        unit = blocked.scope.units[0]
        _git("commit", "--allow-empty", "-m", "new", cwd=Path(unit.root))
        baseline = next(
            (
                Path(service.team.manifest.platform_root)
                / "worktrees/requirements"
                / blocked.delivery_id
                / unit.id
            ).rglob("reviewer-attempt-01")
        )
        (baseline / "hello.txt").write_text("dirty source")
    elif tamper in {"input_hash", "context", "receipt"}:
        getter = FileDesignRecordStore.get_run

        def modified(store, run_id):
            run = getter(store, run_id)
            if tamper == "input_hash":
                return run.model_copy(update={"input_sha256": "f" * 64})
            if tamper == "context":
                return run.model_copy(update={"context_id": "ctx_" + "f" * 64})
            return run.model_copy(update={"error_code": "PROVIDER_ERROR"})

        monkeypatch.setattr(FileDesignRecordStore, "get_run", modified)
    elif tamper == "request":
        getter = FileProductRecordStore.current_request_revision
        monkeypatch.setattr(
            FileProductRecordStore,
            "current_request_revision",
            lambda store, rid: getter(store, rid).model_copy(
                update={"request_revision_sha256": "f" * 64}
            ),
        )
    else:
        getter = FileProductRecordStore.find_approval
        monkeypatch.setattr(
            FileProductRecordStore,
            "find_approval",
            lambda store, aid: getter(store, aid).model_copy(
                update={"rationale": "another approval"}
            ),
        )
    with pytest.raises((UnstartedDesignCorrectionRejected, ValueError, RuntimeError)):
        ProductionUnstartedDesignVerifier(service.project).verify(blocked)
    assert inventory(service.project.root) == before


def test_existing_native_handoff_is_not_recoverable(tmp_path: Path) -> None:
    _, _, blocked = seeded_native_failure(tmp_path)
    child = blocked.children[0]
    changed = child.checkpoint.model_copy(
        update={"technical_design_id": "technical_design_started"}
    )
    assert (
        unstarted_design_rejection(
            blocked.model_copy(
                update={"children": (child.model_copy(update={"checkpoint": changed}),)}
            )
        )
        is None
    )


def test_unstarted_unit_source_must_also_be_clean(tmp_path: Path) -> None:
    service, _, blocked = seeded_native_failure(tmp_path)
    unit = blocked.scope.units[1]
    assert all(child.unit_id != unit.id for child in blocked.children)
    baseline = next(
        (
            Path(service.team.manifest.platform_root)
            / "worktrees/requirements"
            / blocked.delivery_id
            / unit.id
        ).rglob("reviewer-attempt-01")
    )
    (baseline / "hello.txt").write_text("dirty unstarted source")
    before = inventory(service.project.root)
    with pytest.raises(UnstartedDesignCorrectionRejected, match="基线已有改动"):
        ProductionUnstartedDesignVerifier(service.project).verify(blocked)
    assert inventory(service.project.root) == before


def test_hidden_native_design_commit_refuses_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.design.store import FileDesignRecordStore

    service, _, blocked = seeded_native_failure(tmp_path)
    monkeypatch.setattr(FileDesignRecordStore, "find_checkpoint", lambda store, rid: object())
    with pytest.raises(UnstartedDesignCorrectionRejected, match="已发布交接"):
        ProductionUnstartedDesignVerifier(service.project).verify(blocked)


@pytest.mark.parametrize("refusal", ["principal", "budget", "stale_proof"])
def test_public_continue_checks_duty_budget_and_exact_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    from ai_software_engineer.domain.engineering_authority import (
        LocalOperatorPrincipal,
        OperatorDuty,
    )

    service, backend, blocked = seeded_native_failure(tmp_path)
    if refusal == "principal":
        service.operator_principal = LocalOperatorPrincipal(
            operator_id="product-user", duties=(OperatorDuty.PRODUCT,)
        )
    elif refusal == "budget":
        blocked = service._save(blocked, attempts={**blocked.attempts, "design": 3})
    else:
        proof = ProductionUnstartedDesignVerifier(service.project).verify(blocked)
        monkeypatch.setattr(
            backend,
            "verify_unstarted_design_rejection",
            lambda cp: proof.model_copy(update={"checkpoint_sha256": "f" * 64}),
        )
    before = inventory(service.project.root)
    with pytest.raises((ValueError, DeliveryCheckpointStale)):
        service.resume(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert inventory(service.project.root) == before


def test_public_host_continue_corrects_design_before_native_recovery_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
    from ai_software_engineer.manager.production_host import TeamHost

    service, _, blocked = seeded_native_failure(tmp_path)
    host = object.__new__(TeamHost)
    host._operator_principal = LocalOperatorPrincipal.trusted_local()
    monkeypatch.setattr(host, "_resolve_project_id", lambda project_id, delivery_id: "project_test")
    monkeypatch.setattr(host, "_runtime", lambda project_id: SimpleNamespace(requirements=service))

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "native Task recovery must not intercept an unstarted Design correction"
        )

    monkeypatch.setattr(host, "_resume_controller", forbidden)
    monkeypatch.setattr(service, "_advance", lambda cp: cp)
    result = host.resume_delivery(
        ResumeProjectDelivery(delivery_id=blocked.delivery_id), project_id="project_test"
    )
    assert result.checkpoint.stage is JointStage.DESIGNING
    assert result.checkpoint.approval == blocked.approval


@pytest.mark.parametrize("entry", ["host", "console"])
def test_public_host_missing_baseline_does_not_recreate_its_own_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    from types import SimpleNamespace

    from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
    from ai_software_engineer.manager.production_host import TeamHost
    from ai_software_engineer.web_console import (
        ConsoleCommandRejected,
        ContinueDeliveryIntent,
        ManagerConsoleAdapter,
    )

    service, backend, blocked = seeded_native_failure(tmp_path)
    unit = blocked.scope.units[0]
    baseline = next(
        (
            Path(service.team.manifest.platform_root)
            / "worktrees/requirements"
            / blocked.delivery_id
            / unit.id
        ).rglob("reviewer-attempt-01")
    )
    _git("worktree", "remove", str(baseline), cwd=Path(unit.root))
    before = inventory(Path(service.team.manifest.platform_root))
    git_before = (
        _git_output("worktree", "list", "--porcelain", cwd=Path(unit.root)),
        _git_output("show-ref", cwd=Path(unit.root)),
    )
    host = object.__new__(TeamHost)
    host._operator_principal = LocalOperatorPrincipal.trusted_local()
    monkeypatch.setattr(host, "_resolve_project_id", lambda project_id, delivery_id: "project_test")
    monkeypatch.setattr(host, "_runtime", lambda project_id: SimpleNamespace(requirements=service))
    monkeypatch.setattr(host, "requirement_entry", lambda project_id: service)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "No reconcile, writer factory or model may create missing proof inputs"
        )

    monkeypatch.setattr(backend, "reconcile", forbidden)
    monkeypatch.setattr(backend, "factory", forbidden)
    with pytest.raises(
        (UnstartedDesignCorrectionRejected, ConsoleCommandRejected), match="冻结源码工作区缺失"
    ):
        if entry == "host":
            host.resume_delivery(
                ResumeProjectDelivery(delivery_id=blocked.delivery_id), project_id="project_test"
            )
        else:
            ManagerConsoleAdapter(host).execute(
                ContinueDeliveryIntent(
                    project_id="project_test",
                    delivery_id=blocked.delivery_id,
                    expected_checkpoint_sha256=blocked.checkpoint_sha256,
                )
            )
    assert not baseline.exists()
    assert inventory(Path(service.team.manifest.platform_root)) == before
    assert (
        _git_output("worktree", "list", "--porcelain", cwd=Path(unit.root)),
        _git_output("show-ref", cwd=Path(unit.root)),
    ) == git_before
