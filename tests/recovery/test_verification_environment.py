"""Manager-owned verification environment authority is never model permission."""

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.execution import CommandResult, CommandTimedOut, SubprocessCommandExecutor
from ai_software_engineer.git import WorkspacePolicy, WorkspacePolicyError
from ai_software_engineer.manager.native_ui import (
    NativeUiCapability,
    NativeUiNode,
    NativeUiOutput,
    NativeUiResult,
    NativeUiSessionUnavailable,
    native_ui_capability,
)
from ai_software_engineer.manager.verification_environment import (
    SwiftSandboxCapability,
    VerificationEnvironmentIncident,
    discover_swift_sandbox_capability,
    swift_sandbox_argv,
)
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryRejected,
    RecoveryScope,
    VerificationExecutionBlocked,
    digest,
)
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification import CandidateVerificationRunner
from ai_software_engineer.recovery.verification_admission import (
    CandidateVerificationAdmission,
    ExplicitVerificationHuman,
)
from ai_software_engineer.recovery.verification_execution import BoundSwiftVerificationEvidence
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationPlan,
)
from ai_software_engineer.swift_verification import SWIFT_VERIFICATION_COMMANDS
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions
from tests.recovery.test_candidate_verification import Admission, setup_verification
from tests.recovery.test_verification_admission import Facts


def capability() -> SwiftSandboxCapability:
    return SwiftSandboxCapability(
        sandbox_executable="/opt/trusted/codex",
        sandbox_executable_sha256="a" * 64,
        developer_directory="/Applications/Xcode.app/Contents/Developer",
        swift_version="Swift fixture 6.4",
    )


def test_model_permission_cannot_disable_inner_sandbox(tmp_path: Path) -> None:
    for role in (AgentRole.QA, AgentRole.REVIEWER):
        permissions = _definitions()[role].permissions.model_copy(
            update={"commands": SWIFT_VERIFICATION_COMMANDS}
        )
        policy = WorkspacePolicy(tmp_path, permissions)
        with pytest.raises(WorkspacePolicyError):
            policy.authorize_command((*SWIFT_VERIFICATION_COMMANDS[2].split(), "--disable-sandbox"))


def test_executor_argv_retains_outer_readonly_sandbox_and_only_private_scratch(
    tmp_path: Path,
) -> None:
    source, scratch = tmp_path / "source", tmp_path / "scratch"
    source.mkdir()
    scratch.mkdir()
    argv = swift_sandbox_argv(capability(), source, scratch, "test")
    assert argv[0] == "/opt/trusted/codex"
    assert "sandbox" in argv and "--include-managed-config" in argv
    assert 'extends=":read-only"' in argv[argv.index("-c") + 1]
    assert "enabled=false" in argv[argv.index("-c") + 1]
    assert '"' + str(scratch) + '"="write"' in argv[argv.index("-c") + 1]
    assert str(source) not in argv[argv.index("-c") + 1]
    assert argv[argv.index("--") + 1 : argv.index("--") + 4] == (
        "/usr/bin/swift",
        "test",
        "--disable-sandbox",
    )
    assert "--scratch-path" in argv and "--disable-automatic-resolution" in argv
    assert "--skip-update" in argv and "--disable-netrc" in argv
    assert "danger-full-access" not in " ".join(argv)


def test_executor_rejects_source_scratch_overlap_or_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    nested = source / "scratch"
    nested.mkdir()
    with pytest.raises(ValueError):
        swift_sandbox_argv(capability(), source, nested, "test")
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError):
        swift_sandbox_argv(capability(), source, alias, "test")


def test_legacy_plan_hash_unchanged_and_new_capability_requires_new_digest(tmp_path: Path) -> None:
    inputs, repository, _ = setup_verification(tmp_path, ScriptedAdapter(), Admission())
    repository.close()
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
        created_at=_clock(),
    )
    legacy = plan.to_wire()
    assert "executor_capability" not in legacy
    assert "prerequisite_incident_sha256" not in legacy
    assert CandidateVerificationPlan.model_validate(legacy).to_wire() == legacy
    assert (
        digest({key: value for key, value in legacy.items() if key != "plan_sha256"})
        == plan.plan_sha256
    )
    changed = CandidateVerificationPlan.create(
        **{key: value for key, value in legacy.items() if key != "plan_sha256"},
        executor_capability=capability(),
    )
    assert changed.plan_sha256 != plan.plan_sha256
    changed.validate_integrity()


def test_manager_incident_is_waiting_human_not_a_claimed_repair() -> None:
    incident = VerificationEnvironmentIncident.create(
        source_plan_sha256="a" * 64,
        completion_sha256="b" * 64,
        candidate_revision="c" * 40,
        qa_artifact_id="art_qa_fixture",
        delivery_id="delivery_fixture",
        repository_root="/repo/fixture",
        not_tested=2,
        errors=1,
    )
    assert incident.decision.disposition.value == "WAITING_HUMAN"
    assert incident.decision.capability_id is None
    assert incident.incident.kind.value == "ENVIRONMENT"
    assert incident.incident_sha256 == incident.recompute_sha256()
    assert VerificationEnvironmentIncident.model_validate(incident.to_wire()) == incident


def _admitted(
    tmp_path: Path,
    *,
    environment_error: bool = False,
    business_failure: bool = False,
    native_ui: NativeUiCapability | None = None,
    executor_capability=None,
) -> tuple[
    CandidateVerificationPlan,
    FileRecoveryStore,
    Facts,
    list[AgentRequest],
    CandidateVerificationCompletion,
]:
    adapter = ScriptedAdapter(
        qa_failures=tuple(range(1, 101)) if business_failure else (),
        qa_environment_errors=tuple(range(1, 101)) if environment_error else (),
    )
    inputs, repository, _ = setup_verification(tmp_path, adapter, Admission())
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
        created_at=_clock(),
        executor_capability=executor_capability or capability(),
        native_ui=native_ui,
    )
    store = FileRecoveryStore.initialize(tmp_path / "verification", scope=plan.scope)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    facts = Facts()
    admission = CandidateVerificationAdmission(
        store=store, plan_sha256=plan.plan_sha256, facts=facts, artifacts=artifacts, clock=_clock
    )
    admission.propose(plan)
    admission.approve(
        RecoveryApprovalCommand(
            operation_id="op_fixture_approval",
            plan_sha256=plan.plan_sha256,
            approval_reference="fixture-human",
            submitted_at=_clock(),
        ),
        human=ExplicitVerificationHuman(plan.plan_sha256),
    )
    runner = CandidateVerificationRunner(
        repository=repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=_definitions(),
        admission=admission,
        clock=_clock,
    )
    try:
        completion = admission.complete(runner.verify_candidate(inputs))
    finally:
        repository.close()
    return plan, store, facts, adapter.requests, completion


def test_manager_incident_reopens_binds_successor_and_rejects_cross_candidate(
    tmp_path: Path,
) -> None:
    plan, store, _, _, completion = _admitted(tmp_path, environment_error=True)
    incident = store.record_verification_incident(completion)
    reopened = FileRecoveryStore(tmp_path / "verification", scope=plan.scope)
    assert reopened.record_verification_incident(completion) == incident
    assert reopened.get_verification_incident(incident.incident_sha256) == incident
    successor = CandidateVerificationPlan.create(
        **{
            k: v
            for k, v in plan.to_wire().items()
            if k not in {"plan_sha256", "prerequisite_incident_sha256"}
        },
        prerequisite_incident_sha256=incident.incident_sha256,
    )
    assert store.put_verification_plan(successor) == successor
    changed = CandidateVerificationPlan.create(
        **{k: v for k, v in successor.to_wire().items() if k not in {"plan_sha256", "inputs"}},
        inputs=successor.inputs.model_copy(update={"candidate_revision": "f" * 40}),
    )
    with pytest.raises(RecoveryRejected, match="another candidate"):
        store.put_verification_plan(changed)
    incident_path = (
        tmp_path / "verification" / f"verification-incident-{incident.incident_sha256}.json"
    )
    incident_path.write_text("{}")
    with pytest.raises(RecoveryRejected):
        reopened.get_verification_plan(successor.plan_sha256)


def test_real_business_failure_is_not_a_manager_environment_repair(tmp_path: Path) -> None:
    _, store, _, _, completion = _admitted(tmp_path)
    with pytest.raises(RecoveryRejected, match="business failure"):
        store.record_verification_incident(completion)


@pytest.mark.parametrize("with_ui", [False, True])
@pytest.mark.parametrize("with_capture", [False, True])
def test_controlled_execution_independent_receipts_replay_and_denials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_ui: bool,
    with_capture: bool,
) -> None:
    from ai_software_engineer.manager.native_ui import NativeUiCapture, NativeUiStep
    from tests.domain.test_visual_evidence import png_evidence
    from tests.recovery.test_native_ui import scenario

    ui_scenario = scenario().model_copy(
        update={
            "steps": (NativeUiStep(name="initial", capture_window=True if with_capture else None),)
        }
    )
    ui = native_ui_capability(ui_scenario) if with_ui else None
    plan, store, facts, requests, _ = _admitted(tmp_path, native_ui=ui)
    root = tmp_path / "worktrees"
    service = BoundSwiftVerificationEvidence(
        store=store, plan=plan, facts=facts, worktree_root=root
    )
    calls: list[CommandResult] = []
    environments: list[dict[str, str]] = []

    def execute(
        executor: SubprocessCommandExecutor,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        del timeout_seconds
        environments.append(dict(executor._environment))
        result = CommandResult(
            argv=arguments,
            cwd=str(executor._workspace_root),
            returncode=0,
            stdout="Executed 2 tests, with 0 failures",
            stderr="",
            duration_ms=10,
        )
        calls.append(result)
        return result

    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.discover_swift_sandbox_capability",
        lambda _: capability(),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution._require_clean_candidate",
        lambda *_: None,
    )
    monkeypatch.setattr(SubprocessCommandExecutor, "run", execute)
    ui_execution = Mock(
        return_value=(
            NativeUiResult(
                step=ui_scenario.steps[0],
                output=NativeUiOutput(
                    pid=123,
                    action="snapshot",
                    nodes=(NativeUiNode(path="0", attributes={"AXRole": "AXWindow"}),),
                    capture=NativeUiCapture(window_id=42, image=png_evidence())
                    if with_capture
                    else None,
                ),
            ),
        )
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.run_native_ui", ui_execution
    )
    for request in requests:
        source = root / plan.execution_task_id / f"{request.role.value}-attempt-01"
        source.mkdir(parents=True)
        result = service.evidence_for(request, source)
        assert "not a QA or Review verdict" in result.text
        assert len(result.images) == (1 if with_ui and with_capture else 0)
        assert png_evidence().data_base64 not in result.text
        if result.images:
            assert result.images[0].image == png_evidence()
            assert request.role.value in result.images[0].label
            assert request.source_revision in result.images[0].label
            assert "initial" in result.images[0].label
        assert service.evidence_for(request, source) == result
        reopened = BoundSwiftVerificationEvidence(
            store=FileRecoveryStore(tmp_path / "verification", scope=plan.scope),
            plan=plan,
            facts=facts,
            worktree_root=root,
        )
        assert reopened.evidence_for(request, source) == result
        assert (
            store.get_verification_execution(plan.plan_sha256, request.role, completed=True).role
            is request.role
        )
    assert len(calls) == 4
    assert ui_execution.call_count == (2 if with_ui else 0)
    import json

    from jsonschema import Draft202012Validator

    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/candidate-verification.schema.json").read_text()
    )
    validator = Draft202012Validator(schema)
    validator.validate(plan.to_wire())
    for request in requests:
        validator.validate(
            store.get_verification_execution(
                plan.plan_sha256, request.role, completed=True
            ).to_wire()
        )
    assert calls[0].argv != calls[2].argv
    assert all(
        "HOME" not in env and "CODEX_HOME" not in env and len(env) == 7 for env in environments
    )
    request = requests[0]
    source = root / plan.execution_task_id / "qa-attempt-01"
    with pytest.raises(RecoveryRejected, match="not admitted"):
        service.evidence_for(request.model_copy(update={"source_revision": "f" * 40}), source)
    with pytest.raises(RecoveryRejected, match="role worktree"):
        service.evidence_for(request, root / plan.execution_task_id / "reviewer-attempt-01")
    with pytest.raises(RecoveryRejected, match="role"):
        service.evidence_for(request.model_copy(update={"role": AgentRole.CODER}), source)
    facts.stale = True
    with pytest.raises(RecoveryRejected, match=r"stale|changed"):
        service.evidence_for(request, source)
    assert len(calls) == 4


@pytest.mark.parametrize(
    "ui_error",
    [
        "WINDOW_UNAVAILABLE",
        "SESSION_LOCKED",
        "preflight_locked",
        "TARGET_UNAVAILABLE",
        "ACTION_FAILED",
        "UNKNOWN_ACTION",
        "FUTURE_DRIVER_ERROR",
    ],
)
def test_missing_native_window_is_durable_block_and_never_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ui_error: str,
) -> None:
    from tests.recovery.test_native_ui import scenario

    ui = native_ui_capability(scenario())
    plan, store, facts, requests, _ = _admitted(tmp_path, native_ui=ui)
    root = tmp_path / "worktrees"
    request = requests[0]
    source = root / plan.execution_task_id / f"{request.role.value}-attempt-01"
    source.mkdir(parents=True)
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.discover_swift_sandbox_capability",
        lambda _: capability(),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution._require_clean_candidate",
        lambda *_: None,
    )

    def execute(executor: SubprocessCommandExecutor, args: tuple[str, ...]) -> CommandResult:
        return CommandResult(
            argv=args,
            cwd=str(executor._workspace_root),
            returncode=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
        )

    monkeypatch.setattr(SubprocessCommandExecutor, "run", execute)
    blocked_ui = Mock(
        return_value=(
            NativeUiResult(
                step=ui.scenario.steps[0],
                output=NativeUiOutput(pid=123, action="snapshot", nodes=(), error=ui_error),
            ),
        )
    )
    if ui_error == "preflight_locked":
        blocked_ui.side_effect = NativeUiSessionUnavailable("SESSION_LOCKED")
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.run_native_ui", blocked_ui
    )
    service = BoundSwiftVerificationEvidence(
        store=store, plan=plan, facts=facts, worktree_root=root
    )
    for _ in range(2):
        expected = (
            "NATIVE_UI_SESSION_LOCKED"
            if ui_error in {"SESSION_LOCKED", "preflight_locked"}
            else "NATIVE_UI_UNAVAILABLE"
        )
        with pytest.raises(VerificationExecutionBlocked, match=expected) as caught:
            service.evidence_for(request, source)
        if "LOCKED" in expected:
            assert "请解锁运行 ASE 的 Mac" in caught.value.next_action
            assert "旧计划不能重放" in caught.value.next_action
            assert "未产生验收结论" in caught.value.next_action
    blocked_ui.assert_called_once()
    receipt = store.get_verification_execution(plan.plan_sha256, request.role, completed=True)
    assert receipt.phase == "BLOCKED"
    assert receipt.failure_code == expected
    if ui_error == "preflight_locked":
        assert receipt.ui_results is None
    else:
        assert receipt.ui_results is not None
        assert receipt.ui_results[0].output.error == ui_error


@pytest.mark.parametrize("mode", ["uncertain", "timeout", "drift"])
def test_uncertain_timeout_or_changed_executor_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    plan, store, facts, requests, _ = _admitted(tmp_path)
    root = tmp_path / "worktrees"
    source = root / plan.execution_task_id / "qa-attempt-01"
    source.mkdir(parents=True)
    service = BoundSwiftVerificationEvidence(
        store=store, plan=plan, facts=facts, worktree_root=root
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.discover_swift_sandbox_capability",
        lambda _: None if mode == "drift" else capability(),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution._require_clean_candidate",
        lambda *_: None,
    )
    failure = (
        CommandTimedOut(("swift", "test"), 100)
        if mode == "timeout"
        else RuntimeError("process lost")
    )
    execute = Mock(side_effect=failure)
    monkeypatch.setattr(SubprocessCommandExecutor, "run", execute)
    request = requests[0]
    if mode == "drift":
        with pytest.raises(RecoveryRejected, match="changed"):
            service.evidence_for(request, source)
        execute.assert_not_called()
        return
    if mode == "uncertain":
        with pytest.raises(RuntimeError, match="process lost"):
            service.evidence_for(request, source)
        with pytest.raises(RecoveryRejected, match="cannot be replayed"):
            service.evidence_for(request, source)
    else:
        for _ in range(2):
            with pytest.raises(VerificationExecutionBlocked, match="COMMAND_TIMEOUT"):
                service.evidence_for(request, source)
        receipt = store.get_verification_execution(plan.plan_sha256, AgentRole.QA, completed=True)
        assert receipt.phase == "BLOCKED" and receipt.results == ()
    execute.assert_called_once()


def test_prompt_receipt_preserves_request_and_is_used_on_both_route_kinds(tmp_path: Path) -> None:
    from ai_software_engineer.agents import (
        CodexCliAgentAdapter,
        ResponsesAgentAdapter,
        StoredContextResolver,
    )
    from ai_software_engineer.agents.openai_compatible import PromptMessage, PromptPayload
    from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
    from ai_software_engineer.manager.production_delivery import (
        ConfiguredDeliveryRouteAdapterFactory,
    )
    from ai_software_engineer.recovery.verification_execution import (
        VerificationEvidence,
        VerificationEvidencePromptBuilder,
    )
    from ai_software_engineer.role_workspace import RoleWorktreeBinding
    from tests.domain.test_visual_evidence import prompt_image

    _, _, _, requests, _ = _admitted(tmp_path)
    definition = _definitions()[AgentRole.QA]
    binding = Mock(spec=RoleWorktreeBinding, worktree=Mock(path=str(tmp_path)))
    provider = Mock()
    provider.evidence_for.return_value = VerificationEvidence(
        text="sealed receipt", images=(prompt_image(),)
    )
    factory = ConfiguredDeliveryRouteAdapterFactory(verification_evidence=provider)
    guard = Mock()
    factory = factory.with_execution_guard(guard)
    for kind in (ModelProviderKind.CODEX_CLI, ModelProviderKind.RESPONSES):
        route = ProviderRouteConfig(
            kind=kind,
            provider="fixture",
            model="fixture",
            endpoint="https://example.invalid/v1" if kind is ModelProviderKind.RESPONSES else None,
            api_key_env="FIXTURE_KEY" if kind is ModelProviderKind.RESPONSES else None,
        )
        adapter = factory.create(
            route=route,
            definition=definition,
            binding=binding,
            context_resolver=Mock(spec=StoredContextResolver),
            config=ProductionConfig(
                platform_root=str(tmp_path / "platform"), model_routes=(route,)
            ),
            environment={"FIXTURE_KEY": "fixture-not-a-secret"},
        )
        assert isinstance(adapter, (CodexCliAgentAdapter, ResponsesAgentAdapter))
        prompt = adapter._prompt_builder
        assert isinstance(prompt, VerificationEvidencePromptBuilder)
        original = PromptPayload(messages=(PromptMessage(role="user", content="original context"),))
        prompt._delegate = Mock(build=Mock(return_value=original))
        request = requests[0]
        before = request.to_wire()
        result = prompt.build(request)
        assert result.messages[:-1] == original.messages
        assert result.messages[-1].content == "sealed receipt"
        assert result.images == (prompt_image(),)
        assert request.to_wire() == before
        provider.evidence_for.assert_called_with(request, tmp_path, guard)


@pytest.mark.skipif(
    os.environ.get("ASE_RUN_SANDBOX_TESTS") != "1", reason="explicit local sandbox/toolchain opt-in"
)
@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
def test_real_swift_sandbox_keeps_source_readonly_and_network_denied(
    tmp_path: Path, role: AgentRole
) -> None:
    binary = os.environ.get("ASE_TEST_CODEX_EXECUTABLE", "codex")
    available = discover_swift_sandbox_capability(binary)
    assert available is not None, "opted-in sandbox probe requires installed Codex and Xcode"
    source, scratch = tmp_path / role.value, tmp_path / "scratch"
    shutil.copytree(Path(__file__).parents[1] / "fixtures/swift-sandbox", source)
    scratch.mkdir()
    for name in ("tmp", "clang", "swiftpm"):
        (scratch / name).mkdir()
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C",
        "LC_ALL": "C",
        "DEVELOPER_DIR": available.developer_directory,
        "TMPDIR": str(scratch / "tmp"),
        "CLANG_MODULE_CACHE_PATH": str(scratch / "clang"),
        "SWIFTPM_MODULECACHE_OVERRIDE": str(scratch / "swiftpm"),
    }
    argv = swift_sandbox_argv(available, source, scratch, "test")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        script = (
            "import socket; socket.create_connection(('127.0.0.1', "
            + str(listener.getsockname()[1])
            + "), timeout=2)"
        )
        probe = subprocess.run(
            (*argv[: argv.index("--") + 1], sys.executable, "-c", script),
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert probe.returncode != 0 and "Operation not permitted" in probe.stderr
    result = subprocess.run(argv, cwd=source, env=env, capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Executed 2 tests, with 0 failures" in result.stdout
    assert not (source / "forbidden-source-write.txt").exists()
    assert not (source / ".build").exists()
