"""Real Git same-branch source migration with exact operator decisions and restart."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess, Task, TaskStatus
from ai_software_engineer.domain.engineering_authority import (
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    ExecutionBaselineBinding,
)
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.baseline import (
    BaselineGitConflict,
    GitExecutionBaselineAdapter,
)
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.git.worktree import WorktreeCaptureRejected
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from ai_software_engineer.manager.legacy_containment import LegacyExecutionContainment
from ai_software_engineer.recovery.models import digest
from tests.domain.factories import make_task
from tests.git.test_worktree import _create_fixture_repository, _git


@dataclass
class Collector:
    facts: BaselineExecutionFacts
    worktree: WorktreeRef

    def collect(self, target_base_ref: str) -> BaselineExecutionFacts:
        del target_base_ref
        return self.facts

    def completed_task(self, binding: ExecutionBaselineBinding) -> Task:
        binding.require_task(self.facts.task)
        return self.facts.task

    def source_worktree(self, facts: BaselineExecutionFacts) -> WorktreeRef:
        assert facts == self.facts
        return self.worktree

    def execution_scope(self) -> nullcontext[None]:
        return nullcontext()

    def bind_legacy_observation(self, containment: LegacyExecutionContainment) -> None:
        assert self.facts.legacy_containment == containment


@dataclass(frozen=True)
class Setup:
    repository: Path
    manager: GitWorktreeManager
    worktree: WorktreeRef
    target: str
    collector: Collector
    service: ExecutionBaselineService


def setup(tmp_path: Path, *, conflict: bool = False) -> Setup:
    repository = _create_fixture_repository(tmp_path)
    base = _git(repository, "rev-parse", "HEAD")
    task = make_task().model_copy(
        update={
            "repository": str(repository),
            "base_ref": base,
            "branch_name": "ai/feature/greeting",
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
        }
    )
    manager = GitWorktreeManager(
        repository, tmp_path / "worktrees", branch_names={task.id: task.branch_name}
    )
    worktree = manager.create(
        WorktreeSpec(task_id=task.id, role=AgentRole.CODER, attempt=1, source_revision=base)
    )
    (worktree.path / "src/app.py").write_text("VALUE = 2\n")
    _git(worktree.path, "add", "src/app.py")
    _git(worktree.path, "commit", "-m", "old platform candidate")
    worktree = replace(worktree, head_revision=_git(worktree.path, "rev-parse", "HEAD"))
    (worktree.path / "src/app.py").write_text("VALUE = 2\nEXTRA = 3\n")
    if conflict:
        (repository / "src/app.py").write_text("VALUE = 9\n")
        _git(repository, "add", "src/app.py")
    else:
        (repository / "README.md").write_text("updated main prerequisite\n")
        _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "update target source baseline")
    target = _git(repository, "rev-parse", "HEAD")
    permissions = AgentPermissions(
        read_paths=("**",),
        write_paths=("src/**",),
        commands=("git diff", "git status"),
        network=NetworkAccess.NONE,
    )
    facts = BaselineExecutionFacts(
        task=task,
        scope=EngineeringScope(
            team_id="team_baseline",
            project_id="project_baseline",
            repository_id="repo_baseline",
            repository_root=str(repository),
        ),
        task_revision=2,
        work_item_id="work_baseline_wait",
        checkpoint_sequence=1,
        quiescence_proof_sha256="1" * 64,
        runtime_manifest_sha256="2" * 64,
        source_native_rules_sha256="3" * 64,
        target_native_rules_sha256="4" * 64,
        source_artifact_ids=("art_plan_001", "art_impl_old"),
        implementation_artifact_id="art_impl_old",
        resolved_interruption_receipt_sha256s=("5" * 64,),
        permissions=permissions,
        denied_paths=task.constraints.denied_paths if task.constraints is not None else (),
        facts_sha256="0" * 64,
    )
    facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    collector = Collector(facts, worktree)
    store = FileExecutionBaselineStore(tmp_path / "private-baselines")
    service = ExecutionBaselineService(
        store=store, git=GitExecutionBaselineAdapter(manager), facts=collector
    )
    return Setup(repository, manager, worktree, target, collector, service)


def authorize(plan: ExecutionBaselinePlan) -> BaselineOperatorAuthorization:
    return BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="isolated fixture exact engineering decision",
        submitted_at=datetime.now(UTC),
    )


def test_baseline_public_service_preserves_candidate_dirty_branch_and_immutable_approval(
    tmp_path: Path,
) -> None:
    f = setup(tmp_path)
    task_bytes = f.collector.facts.task.to_wire()
    inventory = capture_mutation_inventory(f.worktree.path)
    plan = f.service.propose(f.target)
    assert not plan.conflicted and plan.input_mode is BaselineInputMode.PRESERVE_DRAFT
    assert "VALUE = 2" in plan.complete_capture.patch and "EXTRA = 3" in plan.complete_capture.patch
    assert plan.prepared_source_revision not in (f.worktree.head_revision, f.target)
    assert capture_mutation_inventory(f.worktree.path) == inventory
    assert f.service.propose(f.target) == plan
    authorization = authorize(plan)
    binding = f.service.execute(plan.plan_sha256, authority=authorization)
    assert binding.branch_name == f.worktree.branch
    assert binding.worktree_path == str(f.worktree.path)
    assert binding.approved_base_ref == f.collector.facts.task.base_ref
    assert binding.execution_base_ref == f.target
    assert binding.resolved_interruption_receipt_sha256s == ("5" * 64,)
    assert _git(f.worktree.path, "branch", "--show-current") == f.worktree.branch
    assert _git(f.worktree.path, "show", "HEAD:src/app.py") == "VALUE = 2"
    assert (f.worktree.path / "src/app.py").read_text() == "VALUE = 2\nEXTRA = 3\n"
    assert (f.worktree.path / "README.md").read_text() == "updated main prerequisite\n"
    assert _git(f.repository, "rev-parse", "HEAD") == f.target
    assert _git(f.repository, "show", "HEAD:src/app.py") == "VALUE = 1"
    assert (
        _git(
            f.repository,
            "rev-parse",
            f"refs/ase/baselines/{f.worktree.task_id}/{plan.plan_sha256}/source",
        )
        == f.worktree.head_revision
    )
    assert f.collector.facts.task.to_wire() == task_bytes
    old_files = {path.name: path.read_bytes() for path in f.service.store.root.iterdir()}
    reopened = FileExecutionBaselineStore(f.service.store.root)
    fresh = ExecutionBaselineService(store=reopened, git=f.service.git, facts=f.collector)
    assert fresh.execute(plan.plan_sha256, authority=authorization) == binding
    assert reopened.bindings_for_task(f.worktree.task_id) == (binding,)
    assert "完整旧补丁" in reopened.required_context(binding)
    assert {path.name: path.read_bytes() for path in reopened.root.iterdir()} == old_files


def test_conflicted_preserve_plan_cannot_silently_switch_to_reapply(tmp_path: Path) -> None:
    f = setup(tmp_path, conflict=True)
    inventory = capture_mutation_inventory(f.worktree.path)
    preserve = f.service.propose(f.target)
    assert preserve.conflicted
    old_authorization = authorize(preserve)
    with pytest.raises(BaselineGitConflict):
        f.service.execute(preserve.plan_sha256, authority=old_authorization)
    assert capture_mutation_inventory(f.worktree.path) == inventory
    reapply = f.service.propose(f.target, input_mode=BaselineInputMode.CODER_REAPPLY)
    assert reapply.plan_sha256 != preserve.plan_sha256
    with pytest.raises(ValueError, match="exact new plan"):
        f.service.execute(reapply.plan_sha256, authority=old_authorization)
    binding = f.service.execute(reapply.plan_sha256, authority=authorize(reapply))
    assert binding.input_mode is BaselineInputMode.CODER_REAPPLY
    assert _git(f.worktree.path, "rev-parse", "HEAD") == f.target
    assert (f.worktree.path / "src/app.py").read_text() == "VALUE = 9\n"
    assert _git(f.worktree.path, "status", "--porcelain") == ""
    assert "VALUE = 2" in f.service.store.required_context(binding)
    assert "EXTRA = 3" in f.service.store.required_context(binding)
    assert _git(f.worktree.path, "branch", "--show-current") == f.worktree.branch


@pytest.mark.parametrize("crash_stage", ["update-ref", "read-tree", "apply"])
def test_baseline_admitted_mutation_replays_after_exact_crash_without_duplicate_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crash_stage: str
) -> None:
    f = setup(tmp_path)
    plan = f.service.propose(f.target)
    authority = authorize(plan)
    original_run, original_bytes = f.manager._run_git, f.manager._run_git_bytes
    fired = False

    def run(arguments: tuple[str, ...], *, cwd: Path) -> str:
        nonlocal fired
        outcome = original_run(arguments, cwd=cwd)
        if not fired and (
            (
                crash_stage == "update-ref"
                and arguments[0] == "update-ref"
                and arguments[1].startswith("refs/heads/")
            )
            or (crash_stage == "read-tree" and arguments[:3] == ("read-tree", "-m", "-u"))
        ):
            fired = True
            raise RuntimeError("simulated post-write restart")
        return outcome

    def run_bytes(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        input: bytes | None = None,
        index_file: Path | None = None,
    ) -> bytes:
        nonlocal fired
        outcome = original_bytes(arguments, cwd=cwd, input=input, index_file=index_file)
        if not fired and crash_stage == "apply" and arguments[:2] == ("apply", "--unidiff-zero"):
            fired = True
            raise RuntimeError("simulated post-write restart")
        return outcome

    monkeypatch.setattr(f.manager, "_run_git", run)
    monkeypatch.setattr(f.manager, "_run_git_bytes", run_bytes)
    with pytest.raises(RuntimeError, match="restart"):
        f.service.execute(plan.plan_sha256, authority=authority)
    assert fired and f.service.store.start(plan.plan_sha256) is not None
    monkeypatch.setattr(f.manager, "_run_git", original_run)
    monkeypatch.setattr(f.manager, "_run_git_bytes", original_bytes)
    reopened = FileExecutionBaselineStore(f.service.store.root)
    fresh = ExecutionBaselineService(store=reopened, git=f.service.git, facts=f.collector)
    binding = fresh.execute(plan.plan_sha256, authority=authority)
    assert reopened.bindings_for_task(f.worktree.task_id) == (binding,)
    assert (f.worktree.path / "src/app.py").read_text() == "VALUE = 2\nEXTRA = 3\n"
    assert fresh.execute(plan.plan_sha256, authority=authority) == binding


def test_drift_after_plan_refuses_without_discarding_new_draft(tmp_path: Path) -> None:
    f = setup(tmp_path)
    plan = f.service.propose(f.target)
    (f.worktree.path / "src/app.py").write_text("VALUE = 2\nEXTRA = 4\n")
    changed = capture_mutation_inventory(f.worktree.path)
    with pytest.raises(WorktreeCaptureRejected, match="no longer match capture"):
        f.service.execute(plan.plan_sha256, authority=authorize(plan))
    assert capture_mutation_inventory(f.worktree.path) == changed
    assert _git(f.worktree.path, "rev-parse", "HEAD") == f.worktree.head_revision
    assert f.service.store.bindings_for_task(f.worktree.task_id) == ()
