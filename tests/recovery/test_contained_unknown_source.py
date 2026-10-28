"""A contained start-only UNKNOWN is a separate, exact recovery source."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import RecoveryPlan, RecoverySource
from tests.recovery.test_authorization import make_plan


def contained_plan(tmp_path: Path) -> RecoveryPlan:
    old = make_plan(tmp_path / "project")
    return RecoveryPlan.create(
        **{
            **old.to_wire(),
            "input_mode": "coder_reapply",
            "source": {
                **old.source.to_wire(),
                "contained_unknown_settlement_sha256": "d" * 64,
            },
        }
    )


def test_contained_unknown_source_keeps_the_real_run_and_ordinary_historical_wire(
    tmp_path: Path,
) -> None:
    old = make_plan(tmp_path / "old")
    assert "contained_unknown_settlement_sha256" not in old.source.to_wire()
    assert RecoveryPlan.model_validate(old.to_wire()) == old
    plan = contained_plan(tmp_path)
    assert plan.source.failed_run_id == old.source.failed_run_id
    assert plan.plan_sha256 != old.plan_sha256
    assert RecoveryPlan.model_validate(plan.to_wire()) == plan
    for changes in (
        {"failed_run_id": None},
        {"context_capacity_receipt_sha256": "e" * 64},
        {"stopped_unknown_settlement_sha256": "e" * 64},
        {"contained_unknown_settlement_sha256": "bad-digest"},
    ):
        with pytest.raises(ValidationError):
            RecoverySource.model_validate({**plan.source.to_wire(), **changes})


@pytest.mark.parametrize("change", ("mode", "snapshot", "scope"))
def test_contained_unknown_plan_rejects_incompatible_recovery_modes(
    tmp_path: Path, change: str
) -> None:
    plan = contained_plan(tmp_path)
    changes: dict[str, object] = {"input_mode": None}
    if change == "snapshot":
        # Start-only execution has neither outcome nor stop, so an ordinary
        # terminal snapshot cannot be inferred from its containment.
        changes = {"context_capacity_input": {}}
    elif change == "scope":
        changes = {"scope_approval_reference": "unbound-scope-expansion"}
    with pytest.raises(ValidationError):
        RecoveryPlan.create(**{**plan.to_wire(), **changes})


def test_current_source_routes_contained_unknown_to_its_exact_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.recovery.contained_unknown import ContainedUnknownRecoverySourceReader

    plan = contained_plan(tmp_path)
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
    monkeypatch.setattr(ContainedUnknownRecoverySourceReader, "inspect", exact)
    monkeypatch.setattr(
        verifier._source,
        "inspect",
        Mock(side_effect=AssertionError("contained unknown used failed-route reader")),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.inherited_input.read_inherited_reapply_inputs",
        Mock(return_value=None),
    )
    assert verifier._read_source(plan) is original
    exact.assert_called_once_with(plan.source.scope, "d" * 64)
    assert not Path(config.platform_root).exists()


def test_contained_unknown_reader_missing_environment_never_initializes_stores(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.recovery.contained_unknown import ContainedUnknownRecoverySourceReader
    from ai_software_engineer.recovery.models import RecoveryRejected

    plan = contained_plan(tmp_path)
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    reader = ContainedUnknownRecoverySourceReader(config, {})
    with pytest.raises(RecoveryRejected):
        reader.discover(plan.source.scope)
    with pytest.raises(RecoveryRejected):
        reader.inspect(plan.source.scope, "Bearer " + "x" * 30)
    assert not Path(config.platform_root).exists()


def test_contained_unknown_complete_recovery_capture_cannot_drop_or_change_draft(
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
    from ai_software_engineer.recovery.contained_unknown import require_contained_unknown_capture
    from ai_software_engineer.recovery.models import CapturedChanges, RecoveryRejected
    from ai_software_engineer.recovery.native import NativeRecoverySource

    plan = contained_plan(tmp_path)
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
        SimpleNamespace(contained_unknown_capture=mutation, source=plan.source),
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
    require_contained_unknown_capture(original, captured, current)
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
            require_contained_unknown_capture(
                original, captured, CapturedChanges.from_capture(changed)
            )
    for changed in (
        replace(captured.to_capture(), file_sha256s=()),
        replace(captured.to_capture(), base_revision="c" * 40),
    ):
        with pytest.raises(RecoveryRejected):
            require_contained_unknown_capture(
                original, CapturedChanges.from_capture(changed), current
            )


@pytest.mark.parametrize("final_state", ("clean", "dirty", "restore_base"))
def test_contained_unknown_keeps_committed_history_separate_from_final_draft(
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
    from ai_software_engineer.recovery.contained_unknown import require_contained_unknown_capture
    from ai_software_engineer.recovery.models import CapturedChanges, RecoveryRejected
    from ai_software_engineer.recovery.native import NativeRecoverySource

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
            task_id="task_contained_unknown_capture",
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
                stopped_unknown_settlement_sha256=None,
                contained_unknown_settlement_sha256="d" * 64,
            ),
            contained_unknown_capture=retained,
            denied_paths=(),
        ),
    )
    require_contained_unknown_capture(original, full, current)
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
        require_contained_unknown_capture(original, full, changed)
    with pytest.raises(RecoveryRejected, match="完整未知结果开发草稿"):
        verifier._inspect(plan)
