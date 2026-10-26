"""Stopped unknown budget recovery is a separate source, never a failed route."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import RecoveryPlan, RecoverySource
from tests.recovery.test_authorization import make_plan


def stopped_plan(tmp_path: Path) -> RecoveryPlan:
    old = make_plan(tmp_path / "project")
    return RecoveryPlan.create(
        **{
            **old.to_wire(),
            "input_mode": "coder_reapply",
            "source": {
                **old.source.to_wire(),
                "stopped_unknown_settlement_sha256": "d" * 64,
            },
        }
    )


def test_stopped_unknown_source_keeps_the_real_run_and_ordinary_historical_wire(
    tmp_path: Path,
) -> None:
    old = make_plan(tmp_path / "old")
    assert "stopped_unknown_settlement_sha256" not in old.source.to_wire()
    assert RecoveryPlan.model_validate(old.to_wire()) == old
    plan = stopped_plan(tmp_path)
    assert plan.source.failed_run_id == old.source.failed_run_id
    assert plan.plan_sha256 != old.plan_sha256
    assert RecoveryPlan.model_validate(plan.to_wire()) == plan
    for changes in (
        {"failed_run_id": None},
        {"context_capacity_receipt_sha256": "e" * 64},
        {"stopped_unknown_settlement_sha256": "bad-digest"},
    ):
        with pytest.raises(ValidationError):
            RecoverySource.model_validate({**plan.source.to_wire(), **changes})


@pytest.mark.parametrize("change", ("mode", "snapshot", "scope"))
def test_stopped_unknown_plan_rejects_incompatible_recovery_modes(
    tmp_path: Path, change: str
) -> None:
    plan = stopped_plan(tmp_path)
    changes: dict[str, object] = {"input_mode": None}
    if change == "snapshot":
        # A stopped source has no invocation outcome; ordinary terminal snapshots
        # must never be created by casting a stop into an outcome.
        changes = {"context_capacity_input": {}}
    elif change == "scope":
        changes = {"scope_approval_reference": "unbound-scope-expansion"}
    with pytest.raises(ValidationError):
        RecoveryPlan.create(**{**plan.to_wire(), **changes})


def test_current_source_routes_stopped_unknown_to_its_exact_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.recovery.stopped_unknown import StoppedUnknownRecoverySourceReader

    plan = stopped_plan(tmp_path)
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    verifier = NativeRecoveryFactsVerifier(config, {})
    original = Mock(source=plan.source, denied_paths=plan.denied_paths)
    exact = Mock(return_value=original)
    monkeypatch.setattr(StoppedUnknownRecoverySourceReader, "inspect", exact)
    monkeypatch.setattr(
        verifier._source,
        "inspect",
        Mock(side_effect=AssertionError("stopped unknown used failed-route reader")),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.inherited_input.read_inherited_reapply_inputs",
        Mock(return_value=None),
    )
    assert verifier._read_source(plan) is original
    exact.assert_called_once_with(plan.source.scope, "d" * 64)
    assert not Path(config.platform_root).exists()


def test_stopped_unknown_reader_missing_environment_never_initializes_stores(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.recovery.models import RecoveryRejected
    from ai_software_engineer.recovery.stopped_unknown import StoppedUnknownRecoverySourceReader

    plan = stopped_plan(tmp_path)
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    reader = StoppedUnknownRecoverySourceReader(config, {})
    with pytest.raises(RecoveryRejected):
        reader.discover(plan.source.scope)
    with pytest.raises(RecoveryRejected):
        reader.inspect(plan.source.scope, "Bearer " + "x" * 30)
    assert not Path(config.platform_root).exists()


def test_stopped_unknown_authorization_uses_two_fresh_observations_around_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real authorization seam must not repeat an already doubled source scan."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    import ai_software_engineer.recovery.current as current_module
    from ai_software_engineer.domain import AgentPermissions
    from ai_software_engineer.git import WorktreeChangeCapture
    from ai_software_engineer.recovery.models import (
        RecoveryApprovalCommand,
        RecoveryRejected,
        VerifiedRecoveryDecision,
    )
    from ai_software_engineer.recovery.service import RecoveryAuthorizationService
    from ai_software_engineer.recovery.store import FileRecoveryStore
    from tests.recovery.test_authorization import Captures, Human, approval

    plan = stopped_plan(tmp_path)
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    verifier = NativeRecoveryFactsVerifier(config, {})
    observed: list[str] = []
    current_fact = ["same current facts"]
    manager = SimpleNamespace(
        capture_legacy_changes=Mock(return_value=plan.capture.to_capture()),
        verify_legacy_capture=Mock(),
    )

    def read_source(_plan: RecoveryPlan) -> object:
        observed.append("source")
        return SimpleNamespace(denied_paths=())

    monkeypatch.setattr(verifier, "_read_source", read_source)
    monkeypatch.setattr(
        verifier, "_target_preflight", lambda _plan, _original: SimpleNamespace(manager=manager)
    )
    monkeypatch.setattr(verifier, "_target_facts", lambda _plan, _target: current_fact[0])
    monkeypatch.setattr(current_module, "require_stopped_unknown_capture", Mock())

    class RecordingCaptures(Captures):
        def verify_capture(
            self,
            capture: WorktreeChangeCapture,
            permissions: AgentPermissions,
            *,
            denied_paths: tuple[str, ...] = (),
        ) -> None:
            observed.append("capture")
            super().verify_capture(capture, permissions, denied_paths=denied_paths)

    class RecordingHuman(Human):
        def verify(self, command: RecoveryApprovalCommand) -> VerifiedRecoveryDecision:
            observed.append("human")
            return super().verify(command)

    store = FileRecoveryStore.initialize(tmp_path / "recovery", scope=plan.source.scope)
    store.put_plan(plan)
    captures = RecordingCaptures()
    service = RecoveryAuthorizationService(
        store, facts=verifier, captures=captures, human=RecordingHuman()
    )
    assert service.authorize(approval(plan)).decision.approved
    assert observed == ["source", "capture", "source", "human", "source", "capture", "source"]
    observed.clear()
    assert service.inspect_current_authorization(plan.plan_sha256).plan == plan
    assert observed == ["source", "capture", "source"]
    original_verify = captures.verify_capture

    def change_during_capture(
        capture: WorktreeChangeCapture,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> None:
        original_verify(capture, permissions, denied_paths=denied_paths)
        current_fact[0] = "changed while verifying capture"

    monkeypatch.setattr(captures, "verify_capture", change_during_capture)
    with pytest.raises(RecoveryRejected, match="facts do not match"):
        service.require_current_authorization(plan.plan_sha256)
    current_fact[0] = "same current facts"
    monkeypatch.setattr(captures, "verify_capture", original_verify)
    captures.stale = True
    with pytest.raises(RecoveryRejected, match="capture changed"):
        service.require_current_authorization(plan.plan_sha256)


def test_stopped_unknown_custom_inspection_keeps_original_authorization_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.recovery.models import RecoveryRejected
    from ai_software_engineer.recovery.service import RecoveryAuthorizationService
    from ai_software_engineer.recovery.store import FileRecoveryStore
    from tests.recovery.test_authorization import Captures, Human

    plan = stopped_plan(tmp_path)
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    verifier = NativeRecoveryFactsVerifier(config, {})

    def stronger_inspect(_plan: RecoveryPlan) -> None:
        raise RecoveryRejected("stronger native inspection rejected")

    monkeypatch.setattr(verifier, "inspect", stronger_inspect)
    store = FileRecoveryStore.initialize(tmp_path / "recovery", scope=plan.source.scope)
    service = RecoveryAuthorizationService(
        store, facts=verifier, captures=Captures(), human=Human()
    )
    with pytest.raises(RecoveryRejected, match="stronger native inspection rejected"):
        service._require_current(plan)


def test_stopped_unknown_complete_recovery_capture_cannot_drop_or_change_draft(
    tmp_path: Path,
) -> None:
    from dataclasses import replace
    from types import SimpleNamespace
    from typing import cast

    from ai_software_engineer.git.capture import WorktreeChangeCapture
    from ai_software_engineer.git.mutation_capture import (
        FileMutationCapture,
        MutationTextBody,
        WorktreeMutationCapture,
    )
    from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
    from ai_software_engineer.recovery.models import CapturedChanges, RecoveryRejected
    from ai_software_engineer.recovery.native import NativeRecoverySource
    from ai_software_engineer.recovery.stopped_unknown import require_stopped_unknown_capture

    plan = stopped_plan(tmp_path)
    worktree = plan.capture.to_capture().worktree
    body = MutationTextBody("complete stopped work\n", 0o644)
    patch = b"diff --git a/src/app.py b/src/app.py\n+complete stopped work\n"
    mutation = CapturedMutations.from_capture(
        WorktreeMutationCapture(
            worktree=worktree,
            patch=patch,
            index_diff_sha256="a" * 64,
            mutations=(FileMutationCapture("src/app.py", None, body),),
        )
    )
    original = cast(
        NativeRecoverySource,
        SimpleNamespace(stopped_unknown_capture=mutation, source=plan.source),
    )
    captured = CapturedChanges.from_capture(
        WorktreeChangeCapture(
            worktree=worktree,
            patch=patch,
            index_diff_sha256="a" * 64,
            file_sha256s=(("src/app.py", body.sha256),),
            base_revision=plan.source.effective_base_revision,
        )
    )
    current = CapturedChanges.from_capture(replace(captured.to_capture(), base_revision=None))
    require_stopped_unknown_capture(original, captured, current)
    for changed in (
        replace(current.to_capture(), patch=b""),
        replace(current.to_capture(), file_sha256s=()),
        replace(current.to_capture(), index_diff_sha256="b" * 64),
        replace(
            current.to_capture(),
            worktree=replace(worktree, head_revision="c" * 40),
        ),
    ):
        with pytest.raises(RecoveryRejected):
            require_stopped_unknown_capture(
                original, captured, CapturedChanges.from_capture(changed)
            )
    for changed in (
        replace(captured.to_capture(), file_sha256s=()),
        replace(captured.to_capture(), base_revision="c" * 40),
    ):
        with pytest.raises(RecoveryRejected):
            require_stopped_unknown_capture(
                original, CapturedChanges.from_capture(changed), current
            )


@pytest.mark.parametrize("final_state", ("clean", "dirty", "restore_base"))
def test_stopped_unknown_keeps_committed_history_separate_from_final_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_state: str
) -> None:
    """Real Git: last UNKNOWN Run may be clean after earlier Coder commits."""
    import subprocess
    from dataclasses import replace
    from types import SimpleNamespace
    from typing import cast

    from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
    from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
    from ai_software_engineer.git.worktree import WorktreeCaptureRejected
    from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
    from ai_software_engineer.recovery.models import CapturedChanges, RecoveryRejected
    from ai_software_engineer.recovery.native import NativeRecoverySource
    from ai_software_engineer.recovery.stopped_unknown import require_stopped_unknown_capture

    def git(root: Path, *args: str) -> str:
        return subprocess.run(
            ("git", *args), cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "--initial-branch=main")
    git(repository, "config", "user.name", "Fixture")
    git(repository, "config", "user.email", "fixture@example.invalid")
    source = repository / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 'base'\n")
    git(repository, "add", "src/app.py")
    git(repository, "commit", "-m", "base")
    base_revision = git(repository, "rev-parse", "HEAD")
    manager = GitWorktreeManager(repository, tmp_path / "roles")
    worktree = manager.create(
        WorktreeSpec(
            task_id="task_stopped_unknown_capture",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=base_revision,
        )
    )
    permissions = AgentPermissions(
        read_paths=("src/**",),
        write_paths=("src/**",),
        commands=(),
        network=NetworkAccess.NONE,
    )
    (worktree.path / "src/app.py").write_text("value = 'committed'\n")
    git(worktree.path, "add", "src/app.py")
    git(worktree.path, "commit", "-m", "earlier Coder progress")
    worktree = replace(worktree, head_revision=git(worktree.path, "rev-parse", "HEAD"))
    if final_state == "dirty":
        (worktree.path / "src/app.py").write_text("value = 'last stopped draft'\n")
    elif final_state == "restore_base":
        (worktree.path / "src/app.py").write_text("value = 'base'\n")

    retained = CapturedMutations.from_capture(manager.capture_mutations(worktree, permissions))
    if final_state == "restore_base":
        # The net Task-base diff omits this file while the index still carries
        # an earlier committed version. The capture gate refuses to omit it.
        with pytest.raises(WorktreeCaptureRejected, match="index-only changes"):
            manager.capture_legacy_changes(worktree, permissions, base_revision=base_revision)
        return
    full = CapturedChanges.from_capture(
        manager.capture_legacy_changes(worktree, permissions, base_revision=base_revision)
    )
    current = CapturedChanges.from_capture(manager.capture_legacy_changes(worktree, permissions))
    original = cast(
        NativeRecoverySource,
        SimpleNamespace(
            source=SimpleNamespace(
                effective_base_revision=base_revision,
                stopped_unknown_settlement_sha256="d" * 64,
            ),
            stopped_unknown_capture=retained,
            denied_paths=(),
        ),
    )
    require_stopped_unknown_capture(original, full, current)
    assert full.patch != current.patch
    assert full.files
    if final_state == "dirty":
        assert current.files
    else:
        assert current.files == ()
    manager.verify_legacy_capture(full.to_capture(), permissions)
    manager.verify_legacy_capture(current.to_capture(), permissions)

    # Exercise the current-facts composition, not merely its capture helper:
    # it must observe final-Run dirt separately while verifying the complete
    # Task-base patch before an approval or execution may continue.
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    verifier = NativeRecoveryFactsVerifier(config, {})
    target = SimpleNamespace(manager=manager)
    facts = object()
    monkeypatch.setattr(verifier, "_read_source", lambda _plan: original)
    monkeypatch.setattr(verifier, "_target_preflight", lambda _plan, _original: target)
    monkeypatch.setattr(verifier, "_target_facts", lambda _plan, _target: facts)
    plan = cast(
        RecoveryPlan,
        SimpleNamespace(source=original.source, capture=full, permissions=permissions),
    )
    assert verifier._inspect(plan) is facts

    # A later writer cannot turn a settled UNKNOWN proof into another draft.
    (worktree.path / "src/app.py").write_text("value = 'later writer'\n")
    changed = CapturedChanges.from_capture(manager.capture_legacy_changes(worktree, permissions))
    with pytest.raises(RecoveryRejected, match="完整未知结果开发草稿"):
        require_stopped_unknown_capture(original, full, changed)
    with pytest.raises(RecoveryRejected, match="完整未知结果开发草稿"):
        verifier._inspect(plan)


@pytest.mark.parametrize("fault", ("none", "from", "to", "lease", "time", "item", "duplicate"))
def test_source_requires_exact_queue_settlement_shadow_columns_and_body(fault: str) -> None:
    import json
    from datetime import timedelta

    from ai_software_engineer.domain import WorkItemStatus
    from ai_software_engineer.recovery.stopped_unknown import _require_settlement_audit
    from tests.work_queue.test_dispatcher import NOW, item

    # This is the pure audit-row boundary; real stopped native execution and SQL
    # settlement provenance are independently covered by the public fixture.
    original = item().model_copy(update={"status": WorkItemStatus.WAITING_DEPENDENCY})
    closed = original.model_copy(update={"status": WorkItemStatus.CLOSED})
    settlement = Mock(
        work_item=original,
        event=Mock(occurred_at=NOW),
        settlement_sha256="a" * 64,
        expected_item_sha256="b" * 64,
    )
    payload = {
        "work_item": closed.to_wire(),
        "detail": {
            "settlement_sha256": "a" * 64,
            "previous_work_item_sha256": "b" * 64,
            "budget_refund": False,
        },
    }
    row: dict[str, object] = {
        "work_item_id": closed.id,
        "event_type": "STOPPED_BUDGET_SETTLED",
        "from_status": original.status.value,
        "to_status": closed.status.value,
        "lease_id": None,
        "payload_json": json.dumps(payload),
        "occurred_at": NOW.isoformat(),
    }
    if fault == "from":
        row["from_status"] = "RUNNING"
    elif fault == "to":
        row["to_status"] = "READY"
    elif fault == "lease":
        row["lease_id"] = "lease_foreign"
    elif fault == "time":
        row["occurred_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif fault == "item":
        row["payload_json"] = "{}"
    rows = (row, row) if fault == "duplicate" else (row,)
    if fault == "none":
        _require_settlement_audit(rows, settlement, closed)
    else:
        with pytest.raises(ValueError):
            _require_settlement_audit(rows, settlement, closed)
