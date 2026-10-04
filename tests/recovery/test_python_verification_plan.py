"""Automatic Python verifier capability selection stays exact and bounded."""

from pathlib import Path
from types import SimpleNamespace

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain import PlanAcceptanceMapping
from ai_software_engineer.recovery import verification_entry
from ai_software_engineer.repository_profile import BuildSystem
from tests.domain.factories import NOW, make_implementation_artifact, make_plan_artifact, make_task


def _source(root: Path) -> SimpleNamespace:
    task = make_task()
    return SimpleNamespace(
        stages=SimpleNamespace(
            preparation=SimpleNamespace(
                repository_workspace_root=str(root),
                repository_profile_sha256="a" * 64,
            )
        ),
        inputs=SimpleNamespace(plan_id="art_plan_001", implementation_id="art_impl_001"),
        runtime=SimpleNamespace(task=task),
    )


def test_automatic_python_selections_use_approved_exact_nodes(tmp_path: Path, monkeypatch) -> None:
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    plan = make_plan_artifact().model_copy(
        update={
            "content": make_plan_artifact().content.model_copy(
                update={
                    "acceptance_mapping": (
                        PlanAcceptanceMapping(
                            criterion_id="ac_models_01",
                            step_ids=("step_models",),
                            test_strategy=(
                                "contract: tests/specs/test_models.py::test_exact_binding; "
                                "symbolic K1-T01"
                            ),
                        ),
                    )
                }
            )
        }
    )
    implementation = make_implementation_artifact().model_copy(
        update={
            "content": make_implementation_artifact().content.model_copy(
                update={
                    "acceptance_mapping": (
                        make_implementation_artifact()
                        .content.acceptance_mapping[0]
                        .model_copy(
                            update={
                                "tests": (
                                    "tests/specs/test_models.py::test_exact_binding",
                                    "K1-T01",
                                )
                            }
                        ),
                    )
                }
            )
        }
    )
    artifacts.put(seal_artifact(plan, validated_at=NOW))
    artifacts.put(seal_artifact(implementation, validated_at=NOW))
    monkeypatch.setattr(
        verification_entry,
        "load_repository_profile",
        lambda *_: SimpleNamespace(build_systems=(SimpleNamespace(system=BuildSystem.PYTHON),)),
    )

    selections = verification_entry._automatic_python_mysql_tests(_source(tmp_path))

    assert selections is not None
    assert tuple(selection.node_id for selection in selections) == (
        "tests/specs/test_models.py::test_exact_binding",
    )
    assert selections[0].criterion_ids == ("ac_models_01",)


def test_automatic_python_selections_refuse_uncovered_criteria(tmp_path: Path, monkeypatch) -> None:
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    artifacts.put(seal_artifact(make_plan_artifact(), validated_at=NOW))
    artifacts.put(seal_artifact(make_implementation_artifact(), validated_at=NOW))
    monkeypatch.setattr(
        verification_entry,
        "load_repository_profile",
        lambda *_: SimpleNamespace(build_systems=(SimpleNamespace(system=BuildSystem.PYTHON),)),
    )

    assert verification_entry._automatic_python_mysql_tests(_source(tmp_path)) is None
