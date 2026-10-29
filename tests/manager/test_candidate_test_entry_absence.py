"""A missing planned test entry is a Git fact, not a QA result."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain import (
    AgentRole,
    CoderProgressArtifact,
    ImplementationReportArtifact,
    PlanArtifact,
    Task,
    TaskStatus,
)
from ai_software_engineer.domain.execution_window import PlannedVerificationRequirement
from ai_software_engineer.domain.native_verification import role_verification_digest
from ai_software_engineer.manager import candidate_test_entry_absence
from ai_software_engineer.manager.candidate_test_entry_absence import (
    CandidateTestEntryAbsenceObservation,
    MissingPlannedTestEntry,
    observe_accepted_candidate_test_entry_absence,
    observe_candidate_test_entry_absence,
)
from ai_software_engineer.manager.delivery_wait import _reobserve_sealed_static_qa_absence
from ai_software_engineer.store.ports import TaskRepository
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from tests.domain.factories import (
    make_coder_progress_artifact,
    make_implementation_artifact,
    make_plan_artifact,
    make_state_event,
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


def _python_sources(
    root: Path, candidate: str
) -> tuple[Task, PlanArtifact, ImplementationReportArtifact]:
    task, plan, implementation = _sources(root, candidate)
    path = "tests/learning_collection/test_live_a_to_b.py"
    row = PlannedVerificationRequirement(
        id="verify_live_a_to_b",
        role=AgentRole.QA,
        criterion_ids=("ac_live_01",),
        argv=("python", "-m", "pytest", "-q", path + "::test_production_a_to_b_live"),
        verification_levels=("e2e",),
        planned_new_files=(path,),
    )
    return (
        task,
        plan.model_copy(
            update={
                "content": plan.content.model_copy(update={"verification_requirements": (row,)})
            }
        ),
        implementation,
    )


def _commit_python_test(repository: Path, source: str) -> str:
    path = repository / "tests/learning_collection/test_live_a_to_b.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    _git(repository, "add", "--", "tests/learning_collection/test_live_a_to_b.py")
    _git(repository, "commit", "-qm", "candidate test")
    return _git(repository, "rev-parse", "HEAD")


def _mixed_python_and_missing_file_sources(
    root: Path, candidate: str
) -> tuple[Task, PlanArtifact, ImplementationReportArtifact]:
    task, plan, implementation = _python_sources(root, candidate)
    assert plan.content.verification_requirements is not None
    missing_file = PlannedVerificationRequirement(
        id="verify_browser",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        argv=("node", "--test", "tests/browser/fixture.test.cjs"),
        verification_levels=("e2e",),
        planned_new_files=("tests/browser/fixture.test.cjs",),
    )
    return (
        task,
        plan.model_copy(
            update={
                "content": plan.content.model_copy(
                    update={
                        "verification_requirements": (
                            missing_file,
                            *plan.content.verification_requirements,
                        )
                    }
                )
            }
        ),
        implementation,
    )


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


def test_import_only_candidate_has_no_direct_frozen_pytest_node(repository: Path) -> None:
    candidate = _commit_python_test(
        repository,
        '"""A collected observation remains pending."""\n'
        "from tests.specs.test_project_observations import (\n"
        "    test_requirement_a_discovery_needs_approval_before_requirement_b_can_retrieve,\n"
        ")\n",
    )
    task, plan, implementation = _python_sources(repository, candidate)
    proof = observe_candidate_test_entry_absence(
        repository_root=repository, task=task, plan=plan, implementation=implementation
    )
    assert [(entry.path, entry.node_id) for entry in proof.missing] == [
        (
            "tests/learning_collection/test_live_a_to_b.py",
            "tests/learning_collection/test_live_a_to_b.py::test_production_a_to_b_live",
        )
    ]
    assert proof.model_dump(mode="json", exclude_none=True)["missing"][0]["node_id"] == (
        proof.missing[0].node_id
    )
    proof.validate_integrity()


@pytest.mark.parametrize(
    "source",
    [
        "def test_production_a_to_b_live():\n    assert True\n",
        "from tests.specs.test_project_observations import helper as test_production_a_to_b_live\n",
        "from tests.specs.test_project_observations import *\n",
        "globals()['test_production_a_to_b_live'] = object()\n",
        "def other_test():\n    pass\n",
    ],
)
def test_present_or_dynamic_pytest_node_has_no_static_absence_proof(
    repository: Path, source: str
) -> None:
    candidate = _commit_python_test(repository, source)
    task, plan, implementation = _python_sources(repository, candidate)
    with pytest.raises(ValueError, match="candidate contains every planned test entry"):
        observe_candidate_test_entry_absence(
            repository_root=repository, task=task, plan=plan, implementation=implementation
        )


def test_old_missing_file_observation_wire_and_hash_remain_stable(repository: Path) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    proof = observe_candidate_test_entry_absence(
        repository_root=repository, task=task, plan=plan, implementation=implementation
    )
    assert proof.missing[0].node_id is None
    assert "node_id" not in proof.model_dump(mode="json", exclude_none=True)["missing"][0]
    row = plan.content.verification_requirements[0]
    legacy = CandidateTestEntryAbsenceObservation.create(
        task_id="task_1",
        task_intent_sha256="a" * 64,
        candidate_revision="b" * 40,
        plan_artifact_id="art_plan_1",
        plan_artifact_sha256="c" * 64,
        plan_requirements_sha256=role_verification_digest([row.to_wire()]),
        implementation_artifact_id="art_impl_1",
        implementation_artifact_sha256="d" * 64,
        missing=(
            MissingPlannedTestEntry(
                requirement=row,
                requirement_sha256=role_verification_digest(row.to_wire()),
                path="tests/browser/fixture.test.cjs",
            ),
        ),
    )
    assert legacy.observation_sha256 == (
        "37a5aa28ba283673d81d67c1779b2480fcc4fe3f33ea4123868bc3671a4a8847"
    )


def test_legacy_missing_file_observation_rechecks_under_original_semantics(
    repository: Path,
) -> None:
    candidate = _commit_python_test(
        repository,
        '"""No selected function is directly bound."""\n'
        "from tests.specs.test_project_observations import helper\n",
    )
    task, plan, implementation = _mixed_python_and_missing_file_sources(repository, candidate)
    historical = observe_candidate_test_entry_absence(
        repository_root=repository,
        task=task,
        plan=plan,
        implementation=implementation,
        include_named_nodes=False,
    )
    current = observe_candidate_test_entry_absence(
        repository_root=repository, task=task, plan=plan, implementation=implementation
    )
    assert [(entry.path, entry.node_id) for entry in historical.missing] == [
        ("tests/browser/fixture.test.cjs", None)
    ]
    assert len(current.missing) == 2
    assert current != historical
    restored = CandidateTestEntryAbsenceObservation.model_validate(historical.to_wire())
    restored.validate_integrity()
    rechecked = observe_candidate_test_entry_absence(
        repository_root=repository,
        task=task,
        plan=plan,
        implementation=implementation,
        include_named_nodes=any(entry.node_id is not None for entry in restored.missing),
    )
    assert rechecked == restored
    assert rechecked.observation_sha256 == historical.observation_sha256


def test_oversized_python_source_does_not_hide_independent_missing_file(
    repository: Path,
) -> None:
    candidate = _commit_python_test(repository, "# " + "x" * 64_001 + "\n")
    task, plan, implementation = _mixed_python_and_missing_file_sources(repository, candidate)
    observation = observe_candidate_test_entry_absence(
        repository_root=repository, task=task, plan=plan, implementation=implementation
    )
    assert [(entry.path, entry.node_id) for entry in observation.missing] == [
        ("tests/browser/fixture.test.cjs", None)
    ]
    observation.validate_integrity()


def test_changed_python_blob_refuses_even_with_independent_missing_file(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _commit_python_test(repository, "# frozen source\n")
    task, plan, implementation = _mixed_python_and_missing_file_sources(repository, candidate)
    original_git = candidate_test_entry_absence._git

    def changed_blob(root: Path, *arguments: str, limit: int = 4096) -> bytes:
        if arguments[:2] == ("cat-file", "blob"):
            return b""
        return original_git(root, *arguments, limit=limit)

    monkeypatch.setattr(candidate_test_entry_absence, "_git", changed_blob)
    with pytest.raises(ValueError, match="changed during inspection"):
        observe_candidate_test_entry_absence(
            repository_root=repository, task=task, plan=plan, implementation=implementation
        )


def test_accepted_legacy_mixed_plan_uses_files_only_recheck(
    repository: Path, tmp_path: Path
) -> None:
    candidate = _commit_python_test(
        repository,
        '"""The frozen function has no direct binding."""\n'
        "from tests.specs.test_project_observations import helper\n",
    )
    task, plan, implementation = _mixed_python_and_missing_file_sources(repository, candidate)
    store = FileArtifactStore(tmp_path / "artifacts")
    plan = cast(PlanArtifact, seal_artifact(plan, validated_at=task.updated_at))
    task = task.model_copy(update={"base_ref": plan.source_revision})
    implementation = implementation.model_copy(update={"context_manifest_id": "ctx_" + "b" * 64})
    implementation = cast(
        ImplementationReportArtifact, seal_artifact(implementation, validated_at=task.updated_at)
    )
    store.put(plan)
    store.put(implementation)
    accepted = AcceptedRoleArtifact(
        task_id=task.id,
        work_item_id="work_" + implementation.artifact_id,
        lease_id="lease_" + implementation.artifact_id,
        dispatch_sequence=0,
        checkpoint_sequence=0,
        run_id=implementation.producer.run_id,
        context_manifest_id=implementation.context_manifest_id,
        source_revision=implementation.source_revision,
        receipt=QueueArtifactReceipt(
            artifact_id=implementation.artifact_id, sha256=implementation.integrity.sha256
        ),
    )
    plan_event = make_state_event(
        task_id=task.id,
        from_status=TaskStatus.PLANNING,
        to_status=TaskStatus.IMPLEMENTING,
    ).model_copy(
        update={
            "reason": "plan_validated",
            "artifact_ids": (plan.artifact_id,),
            "source_revision": plan.source_revision,
        }
    )
    durable = MagicMock(spec=TaskRepository)
    durable.list_events.return_value = (plan_event,)
    queue = MagicMock()
    queue.accepted.return_value = (accepted,)
    historical = observe_candidate_test_entry_absence(
        repository_root=repository,
        task=task,
        plan=plan,
        implementation=implementation,
        include_named_nodes=False,
    )
    assert (
        len(
            observe_accepted_candidate_test_entry_absence(
                repository_root=repository,
                task=task,
                repository=durable,
                source_revision=candidate,
                accepted=(accepted,),
                artifacts=store,
            ).missing
        )
        == 2
    )
    rechecked = _reobserve_sealed_static_qa_absence(
        original=CandidateTestEntryAbsenceObservation.model_validate(historical.to_wire()),
        task=task,
        repository=durable,
        source_revision=candidate,
        queue=queue,
        artifacts=store,
    )
    assert rechecked == historical
    queue.accepted.assert_called_once_with(task.id)


def test_accepted_candidate_absence_requires_candidate_receipt_and_durable_plan_event(
    repository: Path, tmp_path: Path
) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    store = FileArtifactStore(tmp_path / "artifacts")
    plan = plan.model_copy(update={"context_manifest_id": "ctx_" + "a" * 64})
    implementation = implementation.model_copy(update={"context_manifest_id": "ctx_" + "b" * 64})
    plan = cast(PlanArtifact, seal_artifact(plan, validated_at=task.updated_at))
    task = task.model_copy(update={"base_ref": plan.source_revision})
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

    receipt = accepted(implementation)
    event = make_state_event(
        task_id=task.id,
        from_status=TaskStatus.PLANNING,
        to_status=TaskStatus.IMPLEMENTING,
    ).model_copy(
        update={
            "reason": "plan_validated",
            "artifact_ids": (plan.artifact_id,),
            "source_revision": plan.source_revision,
        }
    )
    durable = MagicMock(spec=TaskRepository)
    durable.list_events.return_value = (event,)
    observed = observe_accepted_candidate_test_entry_absence(
        repository_root=repository,
        task=task,
        repository=durable,
        source_revision=candidate,
        accepted=(receipt,),
        artifacts=store,
    )
    assert observed.candidate_revision == candidate
    assert observed.missing[0].path == "tests/browser/fixture.test.cjs"
    durable.list_events.return_value = ()
    with pytest.raises(ValueError, match="durable accepted Plan event"):
        observe_accepted_candidate_test_entry_absence(
            repository_root=repository,
            task=task,
            repository=durable,
            source_revision=candidate,
            accepted=(receipt,),
            artifacts=store,
        )
    durable.list_events.return_value = (event,)
    changed = receipt.model_copy(
        update={
            "receipt": QueueArtifactReceipt(artifact_id=implementation.artifact_id, sha256="f" * 64)
        }
    )
    with pytest.raises(ValueError, match="accepted candidate"):
        observe_accepted_candidate_test_entry_absence(
            repository_root=repository,
            task=task,
            repository=durable,
            source_revision=candidate,
            accepted=(changed,),
            artifacts=store,
        )


def test_accepted_candidate_with_k1_style_plan_and_progress_parents(
    repository: Path, tmp_path: Path
) -> None:
    candidate = _git(repository, "rev-parse", "HEAD")
    task, plan, implementation = _sources(repository, candidate)
    store = FileArtifactStore(tmp_path / "artifacts")
    plan = cast(PlanArtifact, seal_artifact(plan, validated_at=task.updated_at))
    task = task.model_copy(update={"base_ref": plan.source_revision})
    progress = make_coder_progress_artifact().model_copy(
        update={"source_revision": task.base_ref, "context_manifest_id": "ctx_" + "a" * 64}
    )
    progress = cast(CoderProgressArtifact, seal_artifact(progress, validated_at=task.updated_at))
    implementation = implementation.model_copy(
        update={
            "parent_artifact_ids": (plan.artifact_id, progress.artifact_id),
            "context_manifest_id": "ctx_" + "b" * 64,
        }
    )
    implementation = cast(
        ImplementationReportArtifact, seal_artifact(implementation, validated_at=task.updated_at)
    )
    for artifact in (plan, progress, implementation):
        store.put(artifact)

    def receipt(
        artifact: CoderProgressArtifact | ImplementationReportArtifact,
    ) -> AcceptedRoleArtifact:
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

    durable = MagicMock(spec=TaskRepository)
    durable.list_events.return_value = (
        make_state_event(
            task_id=task.id,
            from_status=TaskStatus.PLANNING,
            to_status=TaskStatus.IMPLEMENTING,
        ).model_copy(
            update={
                "reason": "plan_validated",
                "artifact_ids": (plan.artifact_id,),
                "source_revision": plan.source_revision,
            }
        ),
    )
    observed = observe_accepted_candidate_test_entry_absence(
        repository_root=repository,
        task=task,
        repository=durable,
        source_revision=candidate,
        accepted=(receipt(progress), receipt(implementation)),
        artifacts=store,
    )
    assert observed.missing[0].path == "tests/browser/fixture.test.cjs"
    with pytest.raises(ValueError, match="candidate parent is not an accepted"):
        observe_accepted_candidate_test_entry_absence(
            repository_root=repository,
            task=task,
            repository=durable,
            source_revision=candidate,
            accepted=(receipt(implementation),),
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
