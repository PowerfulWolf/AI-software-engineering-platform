"""An approved complete draft can extend the accepted progress retained by its plan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.artifact import CoderProgressArtifact, PlanArtifact
from ai_software_engineer.domain.execution_baseline import BaselinePurpose, ExecutionBaselineBinding
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.policy import WorkspacePolicyError
from ai_software_engineer.manager.baseline_admission import BaselineInitialWorkspaceAdmission
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard, WorkerLease
from tests.domain.factories import make_coder_progress_artifact, make_plan_artifact
from tests.manager.test_capacity_baseline_preserved_inputs import _capacity_setup, _pause
from tests.manager.test_execution_baseline import Setup
from tests.orchestration.test_runner import _definitions


class AdmissionGuard(WorkerExecutionGuard):
    """The admission unit seam has a fixed claimed identity and no database writes."""

    def __init__(self, task_id: str, attempt: int) -> None:
        super().__init__()
        self.checks = 0
        self.lease = cast(
            WorkerLease,
            SimpleNamespace(
                claim=SimpleNamespace(
                    work_item=SimpleNamespace(
                        task_id=task_id, role=AgentRole.CODER, attempt=attempt
                    )
                )
            ),
        )

    def check(self) -> None:
        self.checks += 1


@dataclass(frozen=True)
class PreservedFixture:
    source: Setup
    artifacts: FileArtifactStore
    progress: CoderProgressArtifact
    binding: ExecutionBaselineBinding
    admission: BaselineInitialWorkspaceAdmission
    request: AgentRequest


@pytest.fixture
def preserved(tmp_path: Path) -> PreservedFixture:
    return _preserved_fixture(tmp_path)


def _preserved_fixture(tmp_path: Path, *, state: Path | None = None) -> PreservedFixture:
    source = _capacity_setup(tmp_path)
    task = source.collector.facts.task
    if state is not None:
        source.service.store = FileExecutionBaselineStore(state / "execution-baselines" / task.id)
        source.collector.facts = source.collector.facts.model_copy(
            update={
                "scope": source.collector.facts.scope.model_copy(
                    update={"repository_id": "repository_baseline"}
                )
            }
        )
    revision = source.worktree.head_revision
    artifacts = FileArtifactStore(tmp_path / "accepted-artifacts")
    contexts = FileContextStore(state.parent / "contexts" if state else tmp_path / "contexts")
    plan_context = FileRunContextBuilder(source.repository, context_store=contexts).build(
        task, _definitions()[AgentRole.ORCHESTRATOR], attempt=1
    )
    plan = seal_artifact(
        make_plan_artifact().model_copy(
            update={
                "source_revision": task.base_ref,
                "context_manifest_id": plan_context.context_id,
            }
        ),
        validated_at=datetime.now(UTC),
    )
    assert isinstance(plan, PlanArtifact)
    artifacts.put(plan)
    template = make_coder_progress_artifact()
    progress = seal_artifact(
        template.model_copy(
            update={
                "source_revision": revision,
                "content": template.content.model_copy(
                    update={
                        "changed_files": (
                            template.content.changed_files[0].model_copy(
                                update={"path": "src/app.py"}
                            ),
                        ),
                        "completed_step_ids": ("step01", "step02"),
                        "remaining_step_ids": ("step03", "step04"),
                    }
                ),
            }
        ),
        validated_at=datetime.now(UTC),
    )
    assert isinstance(progress, CoderProgressArtifact)
    artifacts.put(progress)
    (source.worktree.path / "src/retained.py").write_text("RETAINED = 3\n")
    facts = source.collector.facts.model_copy(
        update={
            "source_artifact_ids": (plan.artifact_id, progress.artifact_id),
            "implementation_artifact_id": None,
            "progress_artifact_id": progress.artifact_id,
        }
    )
    source.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    approved = source.service.propose(None, purpose=BaselinePurpose.CONTEXT_CAPACITY_RESUME)
    binding = source.service.execute(approved.plan_sha256, authority=_pause(approved))
    assert binding.superseded_progress_artifact_id is None
    assert len(approved.complete_capture.mutations) == 2
    assert len(progress.content.changed_files) == 1
    admission = BaselineInitialWorkspaceAdmission(
        inputs=StoredCoderExecutionInputResolver(source.service.store),
        task_reader=lambda: task,
        artifacts=artifacts,
        git=source.manager,
        guard=AdmissionGuard(task.id, 2),
    )
    request = AgentRequest(
        task_id=task.id,
        run_id="run_preserved_progress_next",
        role=AgentRole.CODER,
        attempt=2,
        source_revision=revision,
        context_manifest_id="ctx_" + "a" * 64,
        permissions=facts.permissions,
        input_artifact_ids=(plan.artifact_id, progress.artifact_id),
        output_schema="schemas/coder-output.schema.json",
        continuation_checkpoint_id=progress.artifact_id,
        continuation_changed_paths=("src/app.py",),
        execution_baseline_sha256=binding.binding_sha256,
        execution_base_ref=binding.execution_base_ref,
        timeout_seconds=1800,
    )
    return PreservedFixture(source, artifacts, progress, binding, admission, request)


def test_complete_approved_draft_keeps_original_progress_steps_and_extra_paths(
    preserved: PreservedFixture,
) -> None:
    f = preserved
    before = capture_mutation_inventory(f.source.worktree.path)
    records = {p: p.read_bytes() for p in f.source.service.store.root.glob("*.json")}
    f.admission.authorize(f.request, f.source.worktree.path)
    assert capture_mutation_inventory(f.source.worktree.path) == before
    assert before.sha256 == f.binding.after_inventory_sha256
    assert f.artifacts.get(f.progress.artifact_id) == f.progress
    assert f.progress.content.completed_step_ids == ("step01", "step02")
    assert all(path.read_bytes() == body for path, body in records.items())
    assert cast(AdmissionGuard, f.admission.guard).checks == 2


@pytest.mark.parametrize(
    "change",
    [
        "extra_dirty",
        "approved_body",
        "ignored_dirty",
        "index",
        "mode",
        "removal",
        "progress_id",
        "paths",
        "source",
        "permissions",
        "claim",
    ],
)
def test_preserved_progress_never_authorizes_unapproved_workspace_or_request(
    preserved: PreservedFixture, change: str
) -> None:
    f = preserved
    request = f.request
    root = f.source.worktree.path
    if change == "extra_dirty":
        (root / "src/unapproved.py").write_text("UNAPPROVED = True\n")
    elif change == "approved_body":
        (root / "src/retained.py").write_text("RETAINED = 99\n")
    elif change == "ignored_dirty":
        (root / ".pytest_cache").mkdir()
        (root / ".pytest_cache/new").write_text("unapproved cache\n")
    elif change == "index":
        from tests.git.test_worktree import _git

        _git(root, "add", "src/retained.py")
    elif change == "mode":
        (root / "src/retained.py").chmod(0o755)
    elif change == "removal":
        (root / "src/retained.py").unlink()
    elif change == "claim":
        f.admission.guard.lease = None
    elif change == "progress_id":
        request = request.model_copy(update={"continuation_checkpoint_id": "art_foreign_progress"})
    elif change == "paths":
        request = request.model_copy(update={"continuation_changed_paths": ("src/retained.py",)})
    elif change == "source":
        request = request.model_copy(update={"source_revision": "f" * 40})
    elif change == "permissions":
        request = request.model_copy(
            update={"permissions": request.permissions.model_copy(update={"write_paths": ("**",)})}
        )
    with pytest.raises((ValueError, WorkspacePolicyError)):
        f.admission.authorize(request, root)


def test_new_accepted_progress_uses_its_exact_checkpoint_not_old_baseline_inventory(
    preserved: PreservedFixture,
) -> None:
    f = preserved
    root = f.source.worktree.path
    (root / "src/retained.py").write_text("RETAINED = 4\n")
    template = f.progress
    new = seal_artifact(
        template.model_copy(
            update={
                "artifact_id": "art_progress_after_baseline",
                "supersedes": template.artifact_id,
                "created_at": datetime.now(UTC) + timedelta(seconds=1),
                "parent_artifact_ids": (*template.parent_artifact_ids, template.artifact_id),
                "content": template.content.model_copy(
                    update={
                        "checkpoint_sequence": 2,
                        "changed_files": (
                            *template.content.changed_files,
                            template.content.changed_files[0].model_copy(
                                update={"path": "src/retained.py"}
                            ),
                        ),
                    }
                ),
            }
        ),
        validated_at=datetime.now(UTC),
    )
    assert isinstance(new, CoderProgressArtifact)
    f.artifacts.put(new)
    request = f.request.model_copy(
        update={
            "continuation_checkpoint_id": new.artifact_id,
            "continuation_changed_paths": ("src/app.py", "src/retained.py"),
        }
    )
    assert capture_mutation_inventory(root).sha256 != f.binding.after_inventory_sha256
    f.admission.authorize(request, root)
    (root / "src/unreported.py").write_text("EXTRA = 5\n")
    with pytest.raises(ValueError, match="checkpoint"):
        f.admission.authorize(request, root)
