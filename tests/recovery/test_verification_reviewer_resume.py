"""A fresh approval resumes an interrupted standalone verification at Reviewer."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.artifacts.store import ArtifactCorruption
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import ContextBundle
from ai_software_engineer.context.ports import ContextBudgetExceeded
from ai_software_engineer.domain import AgentDefinition, AgentRole, Artifact, Task
from ai_software_engineer.execution import CommandResult, SubprocessCommandExecutor
from ai_software_engineer.manager.native_ui import NativeUiNode, NativeUiOutput, NativeUiResult
from ai_software_engineer.manager.production_delivery import ConfiguredDeliveryRouteAdapterFactory
from ai_software_engineer.orchestration import AgentRunFailed
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from ai_software_engineer.recovery import verification_entry as entry_module
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification_admission import CandidateVerificationAdmission
from ai_software_engineer.recovery.verification_execution import BoundSwiftVerificationEvidence
from ai_software_engineer.recovery.verification_native import NativeCandidateSourceReader
from ai_software_engineer.recovery.verification_qa import (
    select_retained_qa,
    validate_retained_qa_artifacts,
)
from ai_software_engineer.recovery.verification_records import CandidateVerificationPlan
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _definitions
from tests.recovery.test_candidate_verification import (
    Admission,
    RejectedReviewAdapter,
    ReviewerProviderFailureAdapter,
    setup_verification,
)
from tests.recovery.test_native_ui import scenario
from tests.recovery.test_verification_environment import capability


class UniqueAdapter(ScriptedAdapter):
    def _artifact(self, request: AgentRequest) -> Artifact:
        return (
            super()._artifact(request).model_copy(update={"artifact_id": f"art_{request.run_id}"})
        )


class InterruptedAdapter(ReviewerProviderFailureAdapter, UniqueAdapter):
    pass


class RejectedAdapter(RejectedReviewAdapter, UniqueAdapter):
    pass


@pytest.mark.parametrize(
    ("before_admission", "repeat", "superseding", "controlled"),
    [
        (False, 0, None, False),
        (False, 2, None, False),
        (True, 0, None, False),
        (True, 2, None, False),
        (False, 0, "qa_fail", False),
        (False, 0, "review_reject", False),
        (False, 0, "review_approve", False),
        (False, 2, None, True),
        (True, 0, None, True),
        (False, 1, None, "python"),
    ],
)
def test_fresh_production_proposal_resumes_only_reviewer_after_standalone_qa_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repeat: int,
    before_admission: bool,
    superseding: str | None,
    controlled: bool | Literal["python"],
) -> None:
    from ai_software_engineer.manager.python_verification import PytestSelection
    from ai_software_engineer.recovery.python_mysql_execution import (
        BoundPythonMysqlVerificationEvidence,
    )
    from ai_software_engineer.recovery.python_mysql_records import MysqlResourceRecord
    from tests.manager.test_python_verification import capability as python_capability

    failing = InterruptedAdapter()
    inputs, repository, _ = setup_verification(tmp_path, failing, Admission())
    before = repository.get(inputs.task_id), repository.list_events(inputs.task_id)
    scope = RecoveryScope(
        team_id="team_test",
        repository_id="repository_test",
        delivery_id="delivery_test",
        repository_root=str(tmp_path / "project"),
    )
    source = SimpleNamespace(
        scope=scope,
        inputs=inputs,
        checkpoint=SimpleNamespace(checkpoint_sha256="1" * 64),
        parent_delivery_id=None,
        parent_checkpoint_sha256=None,
        stages=SimpleNamespace(
            preparation=SimpleNamespace(repository_workspace_root=str(tmp_path))
        ),
        runtime=SimpleNamespace(
            task=repository.get(inputs.task_id),
            events=repository.list_events(inputs.task_id),
            dispatch=SimpleNamespace(dispatch_sha256="2" * 64),
        ),
    )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        team_id="team_test",
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="fixture", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    py_cap = python_capability(tmp_path).model_copy(
        update={
            "selections": (
                PytestSelection(
                    node_id="tests/test_fixture.py::test_exact",
                    criterion_ids=tuple(c.id for c in source.runtime.task.acceptance_criteria),
                ),
            )
        }
    )
    monkeypatch.setattr(entry_module, "discover_python_mysql_capability", lambda *a, **k: py_cap)
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)
    monkeypatch.setattr(entry_module.NativeVerificationFacts, "validate", lambda *_: None)
    monkeypatch.setattr(
        entry_module, "verification_store_root", lambda _: tmp_path / "verification"
    )
    monkeypatch.setattr(entry_module, "_verification_allocation", lambda *_, **__: Mock())
    monkeypatch.setattr(entry_module, "_definitions", lambda *_: _definitions())
    monkeypatch.setattr(entry_module, "_stage_sha", lambda *_: "3" * 64)
    monkeypatch.setattr(entry_module, "_policy_sha", lambda *_: "4" * 64)
    monkeypatch.setattr(
        entry_module, "_executor_capability", lambda *_: capability() if controlled else None
    )
    monkeypatch.setattr(ProductionConfig, "require_mysql_dsn", lambda *_: "offline-fixture")
    connection = Mock(wraps=repository)
    connection.close = Mock()
    monkeypatch.setattr(entry_module, "MySqlTaskRepository", lambda *_: connection)
    selected: list[ScriptedAdapter] = [failing]
    execution_roles: list[AgentRole] = []

    def adapter_factory(
        *, route_adapters: ConfiguredDeliveryRouteAdapterFactory, **_: object
    ) -> Mock:
        def run(request: AgentRequest) -> AgentResult:
            provider = route_adapters._verification_evidence
            if provider is not None:
                assert isinstance(
                    provider,
                    BoundPythonMysqlVerificationEvidence
                    if controlled == "python"
                    else BoundSwiftVerificationEvidence,
                )
                worktree = (
                    Path(config.platform_root)
                    / "worktrees"
                    / scope.repository_id
                    / provider._plan.execution_task_id
                    / f"{request.role.value}-attempt-01"
                )
                worktree.mkdir(parents=True)
                provider.evidence_for(request, worktree)
                execution_roles.append(request.role)
            return selected[0].run(request)

        return Mock(run=run)

    monkeypatch.setattr(entry_module, "DispatchDeliveryAgentAdapter", adapter_factory)
    commands = Mock(
        side_effect=lambda executor, argv, **_: CommandResult(
            argv=argv,
            cwd=str(executor._workspace_root),
            returncode=0,
            stdout="fixture check passed",
            stderr="",
            duration_ms=1,
        )
    )
    monkeypatch.setattr(
        SubprocessCommandExecutor, "run", lambda self, argv, **kw: commands(self, argv, **kw)
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.discover_swift_sandbox_capability",
        lambda _: capability(),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution._require_clean_candidate",
        lambda *_: None,
    )
    py_prefix = "ai_software_engineer.recovery.python_mysql_execution."
    monkeypatch.setattr(py_prefix + "discover_python_mysql_capability", lambda *a, **k: py_cap)
    monkeypatch.setattr(py_prefix + "_require_clean_candidate", lambda *a: None)

    class Resource:
        password = "0123456789abcdef" * 3
        secrets = (password,)

        def __init__(self, intent, publish, clock):
            self.intent, self.publish, self.clock = intent, publish, clock

        def start(self, guard):
            guard()
            self.publish(
                MysqlResourceRecord.create(
                    phase="INTENT", intent=self.intent, recorded_at=self.clock()
                )
            )

        def verify_principal(self, endpoint):
            pass

        def close(self):
            self.publish(
                MysqlResourceRecord.create(
                    phase="CLEANED", intent=self.intent, recorded_at=self.clock()
                )
            )

    monkeypatch.setattr(py_prefix + "IsolatedMysqlResource", Resource)
    monkeypatch.setattr(py_prefix + "MysqlUnixProxy", Mock())
    ui_calls = Mock(
        side_effect=lambda current, *_: tuple(
            NativeUiResult(
                step=step,
                output=NativeUiOutput(
                    pid=123,
                    action=step.action,
                    nodes=(NativeUiNode(path="0", attributes={"AXRole": "AXWindow"}),),
                ),
            )
            for step in current.scenario.steps
        )
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.run_native_ui", ui_calls
    )

    def entry() -> entry_module.CandidateVerificationEntry:
        value = entry_module.CandidateVerificationEntry(
            config, {}, Mock(_delivery_route_adapters=ConfiguredDeliveryRouteAdapterFactory())
        )
        monkeypatch.setattr(value, "_authority", lambda *_: Mock())
        return value

    first = entry()
    plan, path = first.propose(
        scope,
        native_ui_scenario=scenario() if controlled is True else None,
        python_mysql_tests=py_cap.selections if controlled == "python" else None,
    )
    first.approve(path, confirmed_plan=plan.plan_sha256, reference="fixture-original-approval")
    try:
        original_build = FileRunContextBuilder.build

        def interrupted_context(
            self: FileRunContextBuilder,
            task: Task,
            agent: AgentDefinition,
            *,
            attempt: int,
            candidate_revision: str | None = None,
            input_artifacts: tuple[Artifact, ...] = (),
        ) -> ContextBundle:
            if agent.role is AgentRole.REVIEWER:
                raise ContextBudgetExceeded("fixture Reviewer context unavailable")
            return original_build(
                self,
                task,
                agent,
                attempt=attempt,
                candidate_revision=candidate_revision,
                input_artifacts=input_artifacts,
            )

        with monkeypatch.context() as patch:
            if before_admission:
                patch.setattr(FileRunContextBuilder, "build", interrupted_context)
            with pytest.raises(ContextBudgetExceeded if before_admission else AgentRunFailed):
                first.execute(path)
        assert [r.role for r in failing.requests] == (
            [AgentRole.QA] if before_admission else [AgentRole.QA, AgentRole.REVIEWER]
        )
        store = FileRecoveryStore(tmp_path / "verification", scope=scope)
        with pytest.raises(RecoveryRecordMissing):
            store.get_verification_completion(plan.plan_sha256)
        original_bytes = path.read_bytes()
        for index in range(repeat):
            selected[0] = InterruptedAdapter()
            retry = entry()
            retry_plan, retry_path = retry.propose(scope)
            retry.approve(
                retry_path, confirmed_plan=retry_plan.plan_sha256, reference=f"retry-{index}"
            )
            with pytest.raises(AgentRunFailed):
                retry.execute(retry_path)
            assert [r.role for r in selected[0].requests] == [AgentRole.REVIEWER]
            assert retry_plan.retained_qa is not None
            assert retry_plan.retained_qa.plan_sha256 == plan.plan_sha256
        # Restart composition: only durable source invocation and sealed QA may authorize reuse.
        selected[0] = UniqueAdapter()
        fresh = entry()
        next_plan, next_path = fresh.propose(scope)
        assert next_plan.retained_qa is not None
        assert (next_plan.retained_qa.reviewer_invocation_sha256 is None) == before_admission
        assert fresh.coordinate(next_plan) is None
        assert next_plan.reused_qa is not None
        assert next_plan.inputs.accepted_qa is None  # No forged native event.
        if superseding is not None:
            # A newer fully approved verification supersedes this reusable checkpoint even
            # when its QA FAIL / Review verdict is sealed just before a process interruption.
            newer = CandidateVerificationPlan.create(
                **{
                    **{k: v for k, v in plan.to_wire().items() if k != "plan_sha256"},
                    "execution_task_id": "task_verify_newer",
                    "created_at": datetime.now(UTC),
                }
            )
            store.put_verification_plan(newer)
            newer_path = tmp_path / "verification" / f"verification-plan-{newer.plan_sha256}.json"
            fresh.approve(newer_path, confirmed_plan=newer.plan_sha256, reference="newer-full")
            selected[0] = (
                RejectedAdapter()
                if superseding == "review_reject"
                else UniqueAdapter(
                    qa_failures=tuple(range(1, 101)) if superseding == "qa_fail" else ()
                )
            )
            with monkeypatch.context() as patch:
                patch.setattr(
                    CandidateVerificationAdmission,
                    "complete",
                    Mock(side_effect=RuntimeError("fixture process lost before completion")),
                )
                with pytest.raises(RuntimeError, match="fixture process lost"):
                    fresh.execute(newer_path)
            artifacts = FileArtifactStore(tmp_path / "artifacts")
            assert select_retained_qa(store, inputs, artifacts) is None
            with pytest.raises(RecoveryRejected, match="latest interrupted"):
                validate_retained_qa_artifacts(store, next_plan, artifacts)
            after, _ = fresh.propose(scope)
            assert after.retained_qa is None
            assert (
                repository.get(inputs.task_id),
                repository.list_events(inputs.task_id),
            ) == before
            return
        with pytest.raises(RecoveryRecordMissing):
            fresh.execute(next_path)
        assert selected[0].requests == []
        values = {k: v for k, v in next_plan.to_wire().items() if k != "plan_sha256"}
        for field in ("qa_invocation_sha256", "reviewer_invocation_sha256", "plan_sha256"):
            forged = CandidateVerificationPlan.create(
                **{
                    **values,
                    "retained_qa": next_plan.retained_qa.model_copy(update={field: "f" * 64}),
                }
            )
            with pytest.raises(RecoveryRejected):
                store.put_verification_plan(forged)
        for field in ("candidate_revision", "task_sha256", "implementation_sha256"):
            forged = CandidateVerificationPlan.create(
                **{
                    **values,
                    "inputs": next_plan.inputs.model_copy(
                        update={field: "f" * (40 if field == "candidate_revision" else 64)}
                    ),
                }
            )
            with pytest.raises(RecoveryRejected):
                store.put_verification_plan(forged)
        artifacts = FileArtifactStore(tmp_path / "artifacts")
        assert (
            validate_retained_qa_artifacts(store, next_plan, artifacts) == next_plan.retained_qa.qa
        )
        artifact_path = tmp_path / "artifacts" / f"{next_plan.retained_qa.qa.artifact_id}.json"
        saved = artifact_path.read_bytes()
        artifact_path.write_text("{}")
        with pytest.raises(ArtifactCorruption):
            validate_retained_qa_artifacts(store, next_plan, artifacts)
        artifact_path.write_bytes(saved)
        fresh.approve(
            next_path, confirmed_plan=next_plan.plan_sha256, reference="fixture-fresh-approval"
        )
        completion = fresh.execute(next_path)
        assert [r.role for r in selected[0].requests] == [AgentRole.REVIEWER]
        assert completion.qa.producer.run_id == failing.requests[0].run_id
        assert completion.verified
        assert completion.qa_invocation_sha256 is None
        with pytest.raises(RecoveryRecordMissing):
            store.get_verification_invocation(next_plan.plan_sha256, AgentRole.QA)
        assert (repository.get(inputs.task_id), repository.list_events(inputs.task_id)) == before
        assert (
            FileArtifactStore(tmp_path / "artifacts").get(completion.qa.artifact_id)
            == completion.qa
        )
        assert path.read_bytes() == original_bytes
        assert "retained_qa" not in plan.to_wire()
        if controlled:
            expected = [AgentRole.QA] + [AgentRole.REVIEWER] * (
                repeat + (1 if before_admission else 2)
            )
            assert execution_roles == expected
            assert commands.call_count == (1 if controlled == "python" else 2) * len(expected)
            assert ui_calls.call_count == (0 if controlled == "python" else len(expected))
            assert next_plan.native_ui == plan.native_ui
            if controlled == "python":
                assert next_plan.executor_capability == py_cap
            assert (
                store.get_verification_execution(
                    plan.plan_sha256, AgentRole.QA, completed=True
                ).phase
                == "COMPLETED"
            )
            with pytest.raises(RecoveryRecordMissing):
                store.get_verification_execution(
                    next_plan.plan_sha256, AgentRole.QA, completed=True
                )
        # A later completed verification prevents resurrection of the interrupted older PASS.
        after, _ = entry().propose(scope)
        assert after.retained_qa is None
    finally:
        repository.close()
