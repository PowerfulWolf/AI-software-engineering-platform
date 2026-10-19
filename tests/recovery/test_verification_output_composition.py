"""Offline production composition checks for trusted verifier output provenance."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.openai_compatible import RequestPromptBuilder
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.artifacts.store import ArtifactNotFound
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, PlanArtifact, Task
from ai_software_engineer.domain.native_verification import NativeVerificationWaiting
from ai_software_engineer.manager.production_delivery import ConfiguredDeliveryRouteAdapterFactory
from ai_software_engineer.recovery import verification_entry as entry_module
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.python_mysql_execution import (
    BoundPythonMysqlVerificationEvidence,
)
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification_execution import (
    BoundSwiftVerificationEvidence,
    VerificationEvidence,
    VerificationEvidencePromptBuilder,
)
from ai_software_engineer.recovery.verification_native import NativeCandidateSourceReader
from ai_software_engineer.recovery.verification_output import VerificationOutputInputs
from ai_software_engineer.recovery.verification_records import CandidateVerificationPlan
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from tests.manager.test_native_verification import _fake_ports, _fixture
from tests.manager.test_python_verification import capability as python_capability
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions
from tests.recovery.test_candidate_verification import Admission, setup_verification
from tests.recovery.test_verification_environment import capability as swift_capability


class _SetupProbe(RuntimeError):
    """Stop before constructing any SQL repository or running a model."""


def _entry_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    python: bool,
) -> tuple[
    entry_module.CandidateVerificationEntry,
    CandidateVerificationPlan,
    Task,
    PlanArtifact,
    Mock,
]:
    inputs, repository, _ = setup_verification(tmp_path, ScriptedAdapter(), Admission())
    task = repository.get(inputs.task_id)
    repository.close()
    artifact = FileArtifactStore(tmp_path / "artifacts").get(inputs.plan_id)
    assert isinstance(artifact, PlanArtifact)
    plan = CandidateVerificationPlan.create(
        scope=RecoveryScope(
            team_id="team_test",
            repository_id="repository_test",
            delivery_id="delivery_test",
            repository_root=str(tmp_path / "project"),
        ),
        inputs=inputs,
        native_checkpoint_sha256="1" * 64,
        dispatch_sha256="2" * 64,
        approved_stage_chain_sha256="3" * 64,
        current_policy_sha256="4" * 64,
        definitions=tuple(_definitions().values()),
        executor_capability=python_capability(tmp_path) if python else swift_capability(),
        created_at=_clock(),
    )
    source = SimpleNamespace(
        runtime=SimpleNamespace(task=task),
        stages=SimpleNamespace(
            preparation=SimpleNamespace(repository_workspace_root=str(tmp_path))
        ),
    )
    store = Mock(spec=FileRecoveryStore)
    store.get_verification_completion.side_effect = RecoveryRecordMissing()
    store.get_verification_invocation.side_effect = RecoveryRecordMissing()
    authority = Mock()
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="fixture", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    entry = entry_module.CandidateVerificationEntry(
        config, {}, Mock(_delivery_route_adapters=ConfiguredDeliveryRouteAdapterFactory())
    )
    monkeypatch.setattr(entry, "open", lambda _: (store, plan))
    monkeypatch.setattr(entry, "_admission", lambda *_: Mock())
    monkeypatch.setattr(entry, "_authority", lambda _: authority)
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)

    def forbid_sql(*_: object) -> None:
        raise AssertionError("composition test must not construct a production SQL repository")

    monkeypatch.setattr(entry_module, "MySqlTaskRepository", forbid_sql)
    return entry, plan, task, artifact, authority


@pytest.mark.parametrize("python", [False, True], ids=["swift", "python-mysql"])
def test_production_entry_supplies_exact_typed_output_inputs_before_capacity_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, python: bool
) -> None:
    entry, plan, task, artifact, authority = _entry_fixture(tmp_path, monkeypatch, python=python)
    captured: list[VerificationOutputInputs] = []

    def adapter(*, route_adapters: ConfiguredDeliveryRouteAdapterFactory, **_: object) -> None:
        provider = route_adapters._verification_evidence
        assert isinstance(
            provider,
            BoundPythonMysqlVerificationEvidence if python else BoundSwiftVerificationEvidence,
        )
        assert provider._output_inputs is not None
        captured.append(provider._output_inputs)
        raise _SetupProbe()

    monkeypatch.setattr(entry_module, "DispatchDeliveryAgentAdapter", adapter)
    with pytest.raises(_SetupProbe):
        entry.execute(tmp_path / "unused-plan.json")

    assert captured == [VerificationOutputInputs(task=task, plan_artifact=artifact)]
    captured[0].validate_plan(plan)
    authority.reserve_verification.assert_called_once()


@pytest.mark.parametrize("change", ["missing-plan", "task-digest", "plan-digest"])
def test_bad_standalone_output_inputs_do_not_reserve_verifier_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    entry, plan, task, artifact, authority = _entry_fixture(tmp_path, monkeypatch, python=False)
    original_get = FileArtifactStore.get

    def get(store: FileArtifactStore, artifact_id: str) -> object:
        if artifact_id == plan.inputs.plan_id:
            if change == "missing-plan":
                raise ArtifactNotFound("offline missing Plan")
            if change == "plan-digest":
                return artifact.model_copy(update={"source_revision": "e" * 40})
        return original_get(store, artifact_id)

    monkeypatch.setattr(FileArtifactStore, "get", get)
    if change == "task-digest":
        source = SimpleNamespace(
            runtime=SimpleNamespace(
                task=task.model_copy(update={"title": "changed frozen intent"})
            ),
            stages=SimpleNamespace(
                preparation=SimpleNamespace(repository_workspace_root=str(tmp_path))
            ),
        )
        monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)
    with pytest.raises((ArtifactNotFound, RecoveryRejected)):
        entry.execute(tmp_path / "unused-plan.json")
    authority.reserve_verification.assert_not_called()
    authority.complete_verification.assert_not_called()


def test_all_factory_clones_keep_the_same_explicit_receipt_provider(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    class SourceOnly:
        # Clone-only transport identity; no verification discovery or execution.
        def evidence_for(
            self,
            request: AgentRequest,
            workspace_root: Path,
            execution_guard: ExecutionGuard | None = None,
        ) -> VerificationEvidence:
            raise AssertionError("cloning must not prepare or execute verification")

    evidence = SourceOnly()
    base = ConfiguredDeliveryRouteAdapterFactory()
    current = base.with_verification_evidence(evidence)
    clones = [current]
    current = current.with_execution_guard(fixture.guard)
    clones.append(current)
    current = current.with_initial_workspace_admission(Mock())
    clones.append(current)
    current = current.wrap_initial_workspace_admission(lambda prior: prior or Mock())
    clones.append(current)
    current = current.with_interruption_control(Mock())
    clones.append(current)
    current = current.with_registered_verifier(fixture.registry)
    clones.append(current)
    current = current.with_baseline_verifier(Mock())
    clones.append(current)
    current = current.with_candidate_commit_factory(Mock())
    clones.append(current)
    assert base._verification_evidence is None
    assert all(clone._verification_evidence is evidence for clone in clones)


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
def test_registered_receipt_metadata_is_internal_and_fresh_at_output_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: AgentRole
) -> None:
    fixture = _fixture(tmp_path, role)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    fixture.registry.prepare_verifier(
        request=fixture.request, workspace_root=fixture.root, guard=fixture.guard
    )
    provider = fixture.registry.provider_for(
        workspace_root=fixture.root, guard=fixture.guard, require_prepared=True
    )
    builder = VerificationEvidencePromptBuilder(
        RequestPromptBuilder(), provider, fixture.root, fixture.guard
    )
    payload = builder.build(fixture.request)
    contract = payload.verification_output_contract
    assert contract is not None
    assert contract.role is role
    assert contract.claim_sha256 is not None
    assert "verification_output_contract" not in payload.to_wire()
    assert "verification_output_contract" not in payload.model_dump_json()
    assert all("verification_output_contract" not in message for message in payload.to_messages())
    evidence = provider.evidence_for(fixture.request, fixture.root, fixture.guard)
    assert "output_contract" not in evidence.to_wire()
    assert "output_contract" not in evidence.model_dump_json()
    before_reads = fixture.facts.reads
    builder.validate_output_current(fixture.request, fixture.root, fixture.guard, contract)
    assert fixture.facts.reads > before_reads
    fixture.facts.context = "ctx_" + "f" * 64
    with pytest.raises(NativeVerificationWaiting):
        builder.validate_output_current(fixture.request, fixture.root, fixture.guard, contract)
    fixture.facts.context = fixture.request.context_manifest_id
    fixture.guard.active = False
    with pytest.raises(QueueLeaseLost):
        builder.validate_output_current(fixture.request, fixture.root, fixture.guard, contract)
    assert len(resources) == len(executions) == 1
