"""A missing planned test entry is a Git fact, not a QA result."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain import (
    AgentRole,
    ImplementationReportArtifact,
    PlanArtifact,
    Task,
    TaskStatus,
)
from ai_software_engineer.domain.execution_window import PlannedVerificationRequirement
from ai_software_engineer.manager.candidate_test_entry_absence import (
    CandidateTestEntryAbsenceObservation,
    observe_accepted_candidate_test_entry_absence,
    observe_candidate_test_entry_absence,
)
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from tests.domain.factories import (
    make_implementation_artifact,
    make_plan_artifact,
    make_task,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    ).stdout.strip()


def _sources(root: Path, candidate: str) -> tuple[Task, PlanArtifact, ImplementationReportArtifact]:
    row = PlannedVerificationRequirement(
        id="verify_browser",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        argv=("node", "--test", "tests/browser/fixture.test.cjs"),
        verification_levels=("e2e",),
        planned_new_files=("tests/browser/fixture.test.cjs",),
    )
    task = make_task().model_copy(
        update={"repository": str(root), "status": TaskStatus.QA, "attempts": 1}
    )
    plan = make_plan_artifact()
    plan = plan.model_copy(
        update={"content": plan.content.model_copy(update={"verification_requirements": (row,)})}
    )
    implementation = make_implementation_artifact()
    implementation = implementation.model_copy(
        update={
            "source_revision": candidate,
            "content": implementation.content.model_copy(update={"commit_sha": candidate}),
        }
    )
    return task, plan, implementation


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "candidate"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("candidate\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "base")
    return root


def test_missing_planned_test_entry_is_bound_to_exact_candidate_and_row(
    repository: Path,
) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    proof = observe_candidate_test_entry_absence(
        repository_root=repository, task=task, plan=plan, implementation=implementation
    )
    assert proof.candidate_revision == candidate
    assert [(entry.requirement.id, entry.path) for entry in proof.missing] == [
        ("verify_browser", "tests/browser/fixture.test.cjs")
    ]
    proof.validate_integrity()
    assert CandidateTestEntryAbsenceObservation.model_validate(proof.to_wire()) == proof
    changed = proof.model_copy(update={"candidate_revision": "f" * 40})
    with pytest.raises(ValueError, match="changed"):
        changed.validate_integrity()


def test_accepted_candidate_absence_requires_both_exact_artifact_receipts(
    repository: Path, tmp_path: Path
) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    store = FileArtifactStore(tmp_path / "artifacts")
    plan = plan.model_copy(update={"context_manifest_id": "ctx_" + "a" * 64})
    implementation = implementation.model_copy(update={"context_manifest_id": "ctx_" + "b" * 64})
    plan = cast(PlanArtifact, seal_artifact(plan, validated_at=task.updated_at))
    implementation = cast(
        ImplementationReportArtifact, seal_artifact(implementation, validated_at=task.updated_at)
    )
    store.put(plan)
    store.put(implementation)

    def accepted(artifact: PlanArtifact | ImplementationReportArtifact) -> AcceptedRoleArtifact:
        return AcceptedRoleArtifact(
            task_id=task.id,
            work_item_id="work_" + artifact.artifact_id,
            lease_id="lease_" + artifact.artifact_id,
            dispatch_sequence=0,
            checkpoint_sequence=0,
            run_id=artifact.producer.run_id,
            context_manifest_id=artifact.context_manifest_id,
            source_revision=artifact.source_revision,
            receipt=QueueArtifactReceipt(
                artifact_id=artifact.artifact_id, sha256=artifact.integrity.sha256
            ),
        )

    receipts = (accepted(plan), accepted(implementation))
    observed = observe_accepted_candidate_test_entry_absence(
        repository_root=repository,
        task=task,
        source_revision=candidate,
        accepted=receipts,
        artifacts=store,
    )
    assert observed.candidate_revision == candidate
    assert observed.missing[0].path == "tests/browser/fixture.test.cjs"
    with pytest.raises(ValueError, match="accepted Plan"):
        observe_accepted_candidate_test_entry_absence(
            repository_root=repository,
            task=task,
            source_revision=candidate,
            accepted=(receipts[1],),
            artifacts=store,
        )
    changed = receipts[1].model_copy(
        update={
            "receipt": QueueArtifactReceipt(artifact_id=implementation.artifact_id, sha256="f" * 64)
        }
    )
    with pytest.raises(ValueError, match="accepted candidate"):
        observe_accepted_candidate_test_entry_absence(
            repository_root=repository,
            task=task,
            source_revision=candidate,
            accepted=(receipts[0], changed),
            artifacts=store,
        )


def test_frozen_python_module_pytest_nodeid_binds_missing_source_file(
    repository: Path,
) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    path = "tests/learning_collection/test_live_a_to_b.py"
    row = PlannedVerificationRequirement(
        id="verify_live_a_to_b",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        argv=("python", "-m", "pytest", f"{path}::test_production_a_to_b_live"),
        verification_levels=("e2e",),
        planned_new_files=(path,),
    )
    plan = plan.model_copy(
        update={"content": plan.content.model_copy(update={"verification_requirements": (row,)})}
    )

    observation = observe_candidate_test_entry_absence(
        repository_root=repository, task=task, plan=plan, implementation=implementation
    )

    assert len(observation.missing) == 1
    assert observation.missing[0].path == path
    assert observation.missing[0].requirement.argv == row.argv


def test_present_test_entry_cannot_be_reported_missing(repository: Path) -> None:
    entry = repository / "tests/browser/fixture.test.cjs"
    entry.parent.mkdir(parents=True)
    entry.write_text("test('works', () => {});\n")
    _git(repository, "add", "tests/browser/fixture.test.cjs")
    _git(repository, "commit", "-qm", "test entry")
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    with pytest.raises(ValueError, match="every planned test entry"):
        observe_candidate_test_entry_absence(
            repository_root=repository, task=task, plan=plan, implementation=implementation
        )


def test_symlink_ancestor_is_not_interpreted_as_absence(repository: Path) -> None:
    (repository / "tests").symlink_to("elsewhere")
    _git(repository, "add", "tests")
    _git(repository, "commit", "-qm", "symlink ancestor")
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    with pytest.raises(ValueError, match="non-directory ancestor"):
        observe_candidate_test_entry_absence(
            repository_root=repository, task=task, plan=plan, implementation=implementation
        )


def test_symlink_test_file_leaf_is_not_interpreted_as_absence(repository: Path) -> None:
    entry = repository / "tests/browser/fixture.test.cjs"
    entry.parent.mkdir(parents=True)
    entry.symlink_to("../../README.md")
    _git(repository, "add", "tests/browser/fixture.test.cjs")
    _git(repository, "commit", "-qm", "symlink test entry")
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)

    with pytest.raises(ValueError, match="not a regular file"):
        observe_candidate_test_entry_absence(
            repository_root=repository, task=task, plan=plan, implementation=implementation
        )


def test_unplanned_or_unreferenced_path_cannot_enter_observation(repository: Path) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    assert plan.content.verification_requirements is not None
    row = plan.content.verification_requirements[0]
    changed = row.model_copy(update={"planned_new_files": ("tests/browser/other.test.cjs",)})
    plan = plan.model_copy(
        update={
            "content": plan.content.model_copy(update={"verification_requirements": (changed,)})
        }
    )
    with pytest.raises(ValueError, match="exact frozen QA command row"):
        observe_candidate_test_entry_absence(
            repository_root=repository, task=task, plan=plan, implementation=implementation
        )


def test_checkout_change_does_not_replace_candidate_tree_observation(repository: Path) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    entry = repository / "tests/browser/fixture.test.cjs"
    entry.parent.mkdir(parents=True)
    entry.write_text("test('later', () => {});\n")
    _git(repository, "add", "tests/browser/fixture.test.cjs")
    _git(repository, "commit", "-qm", "later checkout")
    proof = observe_candidate_test_entry_absence(
        repository_root=repository, task=task, plan=plan, implementation=implementation
    )
    assert proof.candidate_revision == candidate
    assert len(proof.missing) == 1


def test_noncommit_or_wrong_repository_cannot_be_observed(repository: Path) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    wrong = task.model_copy(update={"repository": str(repository.parent)})
    with pytest.raises(ValueError, match="source facts"):
        observe_candidate_test_entry_absence(
            repository_root=repository, task=wrong, plan=plan, implementation=implementation
        )
    blob = _git(repository, "rev-parse", "HEAD:README.md")
    noncommit = implementation.model_copy(
        update={
            "source_revision": blob,
            "content": implementation.content.model_copy(update={"commit_sha": blob}),
        }
    )
    with pytest.raises(ValueError, match="not a commit"):
        observe_candidate_test_entry_absence(
            repository_root=repository, task=task, plan=plan, implementation=noncommit
        )


def test_changed_row_digest_is_not_accepted(repository: Path) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    proof = observe_candidate_test_entry_absence(
        repository_root=repository, task=task, plan=plan, implementation=implementation
    )
    row = proof.missing[0]
    changed = row.model_copy(update={"requirement_sha256": "f" * 64})
    with pytest.raises(ValueError, match="exact frozen QA command row"):
        type(row).model_validate(changed.to_wire())
