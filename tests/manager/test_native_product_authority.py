"""Native Product writes enforce trusted duties before preparation or business facts."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import StructuredModelResult
from ai_software_engineer.domain.engineering_authority import (
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    DeliveryBackendFailure,
    ReplyToProduct,
    ResumeProjectDelivery,
    StartProjectDelivery,
    _delivery_id,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryFailureCode, DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from tests.manager.test_production_backend import _git
from tests.manager.test_team_host import _config, _ConnectivityStub, _RecordingFactory


class _ClarifyingFactory(_RecordingFactory):
    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        properties = output_schema.get("properties")
        if isinstance(properties, Mapping) and "action" in properties:
            self.payloads.append(input_payload)
            return StructuredModelResult(
                payload={
                    "action": "clarify",
                    "summary": "Confirm the requested greeting.",
                    "questions": ["What greeting should be used?"],
                },
                duration_ms=0,
            )
        return super().complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )


@pytest.fixture
def host_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlTaskRepository",
        _ConnectivityStub,
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlPersistentWorkQueue",
        _ConnectivityStub,
    )
    repository = tmp_path / "code"
    repository.mkdir()
    _git("init", cwd=repository)
    (repository / "hello.txt").write_text("hello\n")
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "base", cwd=repository)
    return tmp_path / "platform", repository


def _host(platform: Path, models: _RecordingFactory, *, duty: OperatorDuty) -> TeamHost:
    return TeamHost(
        config=_config(platform, "team_alpha"),
        environment={"ASE_MYSQL_DSN": "connectivity-only"},
        structured_clients=models,
        operator_principal=LocalOperatorPrincipal(
            operator_id=f"operator:{duty.value.lower()}", duties=(duty,)
        ),
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("reopened_backend", [False, True])
def test_public_native_start_denies_engineering_only_before_preparation(
    host_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, reopened_backend: bool
) -> None:
    platform, repository = host_root
    models = _RecordingFactory()
    host = _host(platform, models, duty=OperatorDuty.ENGINEERING)
    entry = host.project_entry()
    if reopened_backend:
        entry = entry.with_backend(entry._backend)
    before = _files(platform)

    def forbidden_prepare(root: str) -> None:
        raise AssertionError("unauthorized Product start reached preparation")

    monkeypatch.setattr(entry._backend, "prepare", forbidden_prepare)
    with pytest.raises(ValueError, match="PRODUCT"):
        entry.start(
            StartProjectDelivery(
                repository_root=str(repository), requirement="Change the greeting."
            )
        )

    assert _files(platform) == before
    assert not models.payloads and not models.project_roots
    assert not tuple((platform / "projects/project_alpha/repositories").iterdir())


@pytest.mark.parametrize("direct_backend", [False, True])
def test_native_reply_denies_engineering_only_before_reconcile_or_dialogue(
    host_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, direct_backend: bool
) -> None:
    platform, repository = host_root
    product_models = _ClarifyingFactory()
    product = _host(platform, product_models, duty=OperatorDuty.PRODUCT)
    started = product.project_entry().start(
        StartProjectDelivery(repository_root=str(repository), requirement="Change the greeting.")
    )
    assert started.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_REPLY
    engineer_models = _RecordingFactory()
    engineer = _host(platform, engineer_models, duty=OperatorDuty.ENGINEERING)
    entry = engineer.project_entry()
    assert entry.status(started.checkpoint.delivery_id).checkpoint == started.checkpoint
    command = ReplyToProduct(
        delivery_id=started.checkpoint.delivery_id,
        expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
        message="Use the greeting confirmed by the product owner.",
    )
    before = _files(platform)

    def forbidden_reconcile(checkpoint: object) -> None:
        raise AssertionError("unauthorized Product reply reached reconciliation")

    def forbidden_facts(checkpoint: object) -> None:
        raise AssertionError("unauthorized Product reply opened business facts")

    monkeypatch.setattr(entry._backend, "reconcile", forbidden_reconcile)
    monkeypatch.setattr(entry._backend, "_facts_for_checkpoint", forbidden_facts)
    with pytest.raises(ValueError, match="PRODUCT"):
        if direct_backend:
            entry._backend.reply_product(started.checkpoint, command)
        else:
            entry.reply(command)

    assert _files(platform) == before
    assert not engineer_models.payloads and not engineer_models.project_roots
    assert (
        product.project_entry().status(started.checkpoint.delivery_id).checkpoint
        == started.checkpoint
    )


def test_direct_native_start_denies_engineering_only_before_business_facts(
    host_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    platform, repository = host_root
    models = _RecordingFactory()
    engineer = _host(platform, models, duty=OperatorDuty.ENGINEERING)
    backend = engineer.project_entry()._backend
    command = StartProjectDelivery(
        repository_root=str(repository), requirement="Change the greeting."
    )
    preparation = backend.prepare(str(repository))
    before = _files(platform)

    def forbidden_facts(prepared: object) -> None:
        raise AssertionError("unauthorized direct Product start opened business facts")

    monkeypatch.setattr(backend, "_facts", forbidden_facts)
    with pytest.raises(ValueError, match="PRODUCT"):
        backend.start_product("delivery_direct_product", preparation, command)

    assert _files(platform) == before
    assert not models.payloads and not models.project_roots


def test_product_only_can_reply_without_engineering_duty(host_root: tuple[Path, Path]) -> None:
    platform, repository = host_root
    models = _ClarifyingFactory()
    product = _host(platform, models, duty=OperatorDuty.PRODUCT)
    entry = product.project_entry()
    started = entry.start(
        StartProjectDelivery(repository_root=str(repository), requirement="Change the greeting.")
    )
    assert started.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_REPLY
    reply = entry.reply(
        ReplyToProduct(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            message="Use the greeting confirmed by the product owner.",
        )
    )
    assert reply.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_REPLY
    assert reply.checkpoint.sequence == started.checkpoint.sequence + 1
    assert len(models.payloads) == 2
    assert reply.product is not None


def test_public_native_approval_denies_engineering_only_before_reconciliation(
    host_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    platform, repository = host_root
    product = _host(platform, _RecordingFactory(), duty=OperatorDuty.PRODUCT)
    started = product.project_entry().start(
        StartProjectDelivery(repository_root=str(repository), requirement="Change the greeting.")
    )
    assert started.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_APPROVAL
    models = _RecordingFactory()
    engineer = _host(platform, models, duty=OperatorDuty.ENGINEERING)
    entry = engineer.project_entry()
    before = _files(platform)

    def forbidden_reconcile(checkpoint: object) -> None:
        raise AssertionError("unauthorized Product approval reached reconciliation")

    monkeypatch.setattr(entry._backend, "reconcile", forbidden_reconcile)
    with pytest.raises(ValueError, match="PRODUCT"):
        entry.approve(
            ApproveProductSpec(
                delivery_id=started.checkpoint.delivery_id,
                expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
                approval_reference="engineering-cannot-approve-product",
            )
        )
    assert _files(platform) == before
    assert not models.payloads and not models.project_roots


@pytest.mark.parametrize("retry_failed_stage", [False, True])
def test_native_product_resume_denies_engineering_only_before_reconciliation_or_writes(
    host_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, retry_failed_stage: bool
) -> None:
    platform, repository = host_root
    product = _host(platform, _RecordingFactory(), duty=OperatorDuty.PRODUCT)
    product_entry = product.project_entry()

    class ProductInterrupted(BaseException):
        pass

    def interrupted_product(*args: object) -> None:
        if retry_failed_stage:
            raise DeliveryBackendFailure(
                DeliveryFailureCode.RESOURCE_UNAVAILABLE, "Fixture Product is unavailable."
            )
        raise ProductInterrupted()

    monkeypatch.setattr(product_entry._backend, "start_product", interrupted_product)
    start = StartProjectDelivery(
        repository_root=str(repository), requirement="Change the greeting."
    )
    if retry_failed_stage:
        current = product_entry.start(start).checkpoint
        assert current.stage is DeliveryStage.BLOCKED
        assert current.failed_stage is DeliveryStage.PRODUCT_DISCOVERY
    else:
        with pytest.raises(ProductInterrupted):
            product_entry.start(start)
        delivery_id = _delivery_id(str(repository), start.requirement, namespace="project_alpha")
        current = product_entry.status(delivery_id).checkpoint
        assert current.stage is DeliveryStage.PRODUCT_DISCOVERY
    models = _RecordingFactory()
    engineer = _host(platform, models, duty=OperatorDuty.ENGINEERING)
    entry = engineer.project_entry()
    before = _files(platform)

    def forbidden_reconcile(checkpoint: object) -> None:
        raise AssertionError("unauthorized Product resume reached reconciliation")

    monkeypatch.setattr(entry._backend, "reconcile", forbidden_reconcile)
    with pytest.raises(ValueError, match="PRODUCT"):
        if retry_failed_stage:
            entry.retry_interrupted_stage(ResumeProjectDelivery(delivery_id=current.delivery_id))
        else:
            entry.resume(ResumeProjectDelivery(delivery_id=current.delivery_id))
    assert _files(platform) == before
    assert not models.payloads and not models.project_roots
