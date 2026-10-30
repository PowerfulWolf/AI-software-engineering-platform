"""Automatic Python verifier capability selection stays exact and bounded."""

from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

from pytest import MonkeyPatch, mark, raises

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import AgentRole, PlanAcceptanceMapping
from ai_software_engineer.domain.artifact import PlanArtifact
from ai_software_engineer.domain.execution_window import PlannedVerificationRequirement
from ai_software_engineer.recovery import verification_entry
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.verification_native import NativeCandidateSource
from ai_software_engineer.repository_profile import BuildSystem
from tests.domain.factories import NOW, make_implementation_artifact, make_plan_artifact, make_task


def _source(root: Path) -> NativeCandidateSource:
    task = make_task()
    return cast(
        NativeCandidateSource,
        SimpleNamespace(
            stages=SimpleNamespace(
                preparation=SimpleNamespace(
                    repository_workspace_root=str(root),
                    repository_profile_sha256="a" * 64,
                )
            ),
            inputs=SimpleNamespace(plan_id="art_plan_001", implementation_id="art_impl_001"),
            runtime=SimpleNamespace(task=task),
        ),
    )


def test_automatic_python_selections_use_approved_exact_nodes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
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


def test_automatic_python_selections_refuse_uncovered_criteria(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    artifacts.put(seal_artifact(make_plan_artifact(), validated_at=NOW))
    artifacts.put(seal_artifact(make_implementation_artifact(), validated_at=NOW))
    monkeypatch.setattr(
        verification_entry,
        "load_repository_profile",
        lambda *_: SimpleNamespace(build_systems=(SimpleNamespace(system=BuildSystem.PYTHON),)),
    )

    assert verification_entry._automatic_python_mysql_tests(_source(tmp_path)) is None


def _typed_source(
    root: Path, monkeypatch: MonkeyPatch, rows: tuple[PlannedVerificationRequirement, ...]
) -> NativeCandidateSource:
    source = _source(root)
    plan = make_plan_artifact()
    plan = plan.model_copy(
        update={"content": plan.content.model_copy(update={"verification_requirements": rows})}
    )
    artifacts = FileArtifactStore(root / "artifacts")
    artifacts.put(seal_artifact(plan, validated_at=NOW))
    artifacts.put(seal_artifact(make_implementation_artifact(), validated_at=NOW))
    monkeypatch.setattr(
        verification_entry,
        "load_repository_profile",
        lambda *_: SimpleNamespace(build_systems=(SimpleNamespace(system=BuildSystem.PYTHON),)),
    )
    return source


def _row(
    identifier: str,
    argv: tuple[str, ...],
    *,
    role: Literal[AgentRole.QA, AgentRole.REVIEWER] = AgentRole.QA,
    capability: str | None = "codex_sandbox_pytest_mysql_v1",
) -> PlannedVerificationRequirement:
    return PlannedVerificationRequirement(
        id=identifier,
        role=role,
        criterion_ids=("ac_models_01",),
        argv=argv,
        controlled_capability_kind=capability,
    )


def test_automatic_python_selections_use_typed_plan_commands(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    node = "tests/specs/test_models.py::test_exact_binding"
    source = _typed_source(
        tmp_path,
        monkeypatch,
        (
            _row("contract", ("python", "-m", "pytest", "-q", node)),
            _row("integration", ("python", "-m", "pytest", "-q", node), capability=None),
        ),
    )

    selections = verification_entry._automatic_python_mysql_tests(source)

    assert selections is not None
    assert [(item.node_id, item.criterion_ids) for item in selections] == [
        (node, ("ac_models_01",))
    ]


@mark.parametrize(
    ("unsafe_argv", "capability"),
    [
        (("python", "-m", "pytest", "--maxfail=1", "tests/specs/test_models.py::test_bad"), None),
        (("python", "-m", "pytest", "tests/specs/test_models.py"), None),
        (("python", "-c", "import pytest"), None),
        (("pytest", "tests/specs/test_models.py::test_bad"), "foreign_capability"),
        (("node", "--test", "tests/specs/test_models.js"), "codex_sandbox_pytest_mysql_v1"),
    ],
)
def test_automatic_python_selections_reject_malformed_typed_command(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    unsafe_argv: tuple[str, ...],
    capability: str | None,
) -> None:
    node = "tests/specs/test_models.py::test_exact_binding"
    source = _typed_source(
        tmp_path,
        monkeypatch,
        (
            _row("valid", ("python", "-m", "pytest", "-q", node)),
            _row("unsafe", unsafe_argv, capability=capability),
        ),
    )

    with raises(RecoveryRejected, match="typed Python verification"):
        verification_entry._automatic_python_mysql_tests(source)


def test_automatic_python_selections_refuse_more_than_64_typed_nodes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    rows = tuple(
        _row(
            f"row_{index}",
            ("pytest", f"tests/specs/test_models.py::test_node_{index}"),
        )
        for index in range(65)
    )
    source = _typed_source(tmp_path, monkeypatch, rows)

    with raises(RecoveryRejected, match="typed Python verification"):
        verification_entry._automatic_python_mysql_tests(source)


def test_automatic_python_selections_do_not_use_reviewer_only_typed_command(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = _typed_source(
        tmp_path,
        monkeypatch,
        (
            _row(
                "review",
                ("pytest", "tests/specs/test_models.py::test_exact_binding"),
                role=AgentRole.REVIEWER,
            ),
        ),
    )

    assert verification_entry._automatic_python_mysql_tests(source) is None


def test_automatic_python_selections_leave_non_python_qa_plan_to_native_route(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = _typed_source(
        tmp_path,
        monkeypatch,
        (_row("browser", ("node", "--test", "tests/browser/test_console.js"), capability=None),),
    )

    assert verification_entry._automatic_python_mysql_tests(source) is None


def test_automatic_python_selections_refuse_incomplete_typed_coverage(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    node = "tests/specs/test_models.py::test_exact_binding"
    _typed_source(tmp_path, monkeypatch, (_row("partial", ("pytest", node)),))
    plan = FileArtifactStore(tmp_path / "artifacts", read_only=True).get("art_plan_001")
    assert isinstance(plan, PlanArtifact)

    with raises(RecoveryRejected, match="typed Python verification"):
        verification_entry._typed_python_mysql_tests(plan, {"ac_models_01", "ac_other_02"})


def test_invalid_typed_plan_stops_before_candidate_verification_plan_issuance(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = _typed_source(
        tmp_path,
        monkeypatch,
        (_row("invalid", ("python", "-m", "pytest", "tests/specs/test_models.py")),),
    )
    monkeypatch.setattr(
        verification_entry,
        "NativeCandidateSourceReader",
        lambda *_: SimpleNamespace(inspect=lambda *_: source),
    )

    def unexpected_authority(*_: object) -> None:
        raise AssertionError("invalid typed Plan issued a model-only verification plan")

    monkeypatch.setattr(
        verification_entry.CandidateVerificationEntry, "_authority", unexpected_authority
    )
    entry = object.__new__(verification_entry.CandidateVerificationEntry)
    entry.config = cast(ProductionConfig, None)
    entry.environment = {}

    with raises(RecoveryRejected, match="typed Python verification"):
        entry.propose(cast(RecoveryScope, None))
