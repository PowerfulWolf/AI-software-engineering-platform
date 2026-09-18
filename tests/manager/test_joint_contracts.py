"""Joint artifact coverage, authorization, and exported Schema regression tests."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import ProjectPreparation
from ai_software_engineer.execution import (
    CommandExecutionError,
    CommandResult,
    CommandTimedOut,
    SubprocessCommandExecutor,
)
from ai_software_engineer.manager.preparation import PrepareProjectResult, PrepareProjectStatus
from ai_software_engineer.manager.production_agents import ProductDraft
from ai_software_engineer.multi_directory.integration_commands import is_test_command
from ai_software_engineer.multi_directory.models import (
    Candidate,
    DialogueMessage,
    IntegrationCommandError,
    IntegrationEvidence,
    JointApproval,
    JointCheckpoint,
    JointExecutionPlan,
    JointProductSpec,
    JointStage,
    JointTechnicalDesign,
    PreparedUnit,
    digest,
)
from ai_software_engineer.multi_directory.production import (
    DerivedStageInputs,
    _execute_integration_command,
    _integration_permissions,
    _python_integration_environment,
    _require_nonempty_test_run,
    _validate_pytest_paths,
)
from ai_software_engineer.multi_directory.retirement import RequirementRetirement
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.multi_directory.store import JointJournal
from tests.e2e.test_joint_delivery import JointModels
from tests.manager.test_production_backend import _git, _git_output


def checkpoint(tmp_path: Path) -> JointCheckpoint:
    now = datetime.now(UTC)
    scope = DirectoryScope(
        units=tuple(
            DirectoryUnit(
                id="unit_" + c * 16,
                root=str(tmp_path / c),
                selected_paths=(".",),
                base_revision=c * 40,
            )
            for c in ("a", "b")
        )
    )
    models = JointModels()
    draft = ProductDraft.model_validate(
        models.complete(
            instructions="",
            input_payload={},
            output_schema=ProductDraft.model_json_schema(),
            timeout_seconds=1,
        ).payload
    )
    product = JointProductSpec(scope_sha256=digest(scope), version=1, product=draft)
    design = JointTechnicalDesign.model_validate(
        models.complete(
            instructions="",
            input_payload={"scope": scope.to_wire(), "product_spec_sha256": digest(product)},
            output_schema=JointTechnicalDesign.model_json_schema(),
            timeout_seconds=1,
        ).payload
    )
    plan = JointExecutionPlan.model_validate(
        models.complete(
            instructions="",
            input_payload={"scope": scope.to_wire(), "design_sha256": digest(design)},
            output_schema=JointExecutionPlan.model_json_schema(),
            timeout_seconds=1,
        ).payload
    )
    preparations = tuple(
        PreparedUnit(
            unit_id=unit.id,
            result=PrepareProjectResult(
                status=PrepareProjectStatus.PREPARED,
                repository_id=f"repository_contract_{index}",
                baseline_compilation_sha256=str(index) * 64,
                preparation=ProjectPreparation.create(
                    team_id="team_test",
                    project_id="project_test",
                    project_manifest_sha256="1" * 64,
                    repository_id=f"repository_contract_{index}",
                    repository_root=unit.root,
                    repository_workspace_root=str(tmp_path / f"sidecar-{index}"),
                    team_root=str(tmp_path / f"team-{index}"),
                    repository_profile_sha256="2" * 64,
                    runtime_binding_sha256="3" * 64,
                    baseline_spec_sha256="4" * 64,
                    prepared_at=now,
                ),
            ),
        )
        for index, unit in enumerate(scope.units, 1)
    )
    return JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_contract",
            "team_id": "team_test",
            "team_manifest_sha256": "0" * 64,
            "project_id": "project_test",
            "project_manifest_sha256": "1" * 64,
            "sequence": 1,
            "scope": scope,
            "preparations": preparations,
            "title": "Test",
            "submitted_at": now,
            "stage": JointStage.DELIVERING,
            "product_spec": product,
            "approval": JointApproval(
                product_spec_sha256=digest(product),
                checkpoint_sha256="0" * 64,
                reference="approved",
                approved_at=now,
            ),
            "design": design,
            "plan": plan,
            "next_action": "Deliver exact projected units",
        }
    )


def test_joint_design_rejects_write_escape_and_duplicate_mapping(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.design and cp.product_spec
    unit = cp.design.units[0]
    component = unit.design.components[0].model_copy(update={"affected_paths": ("../escape",)})
    changed = unit.model_copy(
        update={"design": unit.design.model_copy(update={"components": (component,)})}
    )
    with pytest.raises(ValueError, match="selected directories"):
        cp.design.model_copy(update={"units": (changed, cp.design.units[1])}).validate_for(
            cp.scope, cp.product_spec
        )
    duplicate = unit.design.model_copy(
        update={"requirement_mappings": unit.design.requirement_mappings * 2}
    )
    with pytest.raises(ValueError, match="unique"):
        cp.design.model_copy(
            update={"units": (unit.model_copy(update={"design": duplicate}), cp.design.units[1])}
        ).validate_for(cp.scope, cp.product_spec)


def test_dependency_order_and_done_require_joint_evidence(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.plan and cp.product_spec and cp.design
    with pytest.raises(ValueError, match="dependency"):
        cp.plan.model_copy(update={"units": tuple(reversed(cp.plan.units))}).validate_for(
            cp.scope, cp.product_spec, cp.design
        )
    with pytest.raises(ValueError, match="integration evidence"):
        JointCheckpoint.seal({**cp.to_wire(), "stage": JointStage.DONE})
    with pytest.raises(ValueError, match="approved joint"):
        DerivedStageInputs(
            JointCheckpoint.seal({**cp.to_wire(), "plan": None}), cp.scope.units[0].id
        )


def test_projection_is_deterministic_and_requires_exact_root(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    unit = cp.scope.units[0]
    first = DerivedStageInputs(cp, unit.id)
    second = DerivedStageInputs(cp, unit.id)
    assert first.product == second.product
    assert first.requirement == second.requirement
    assert first.design.requirement_mappings[0].requirement_id == "req_001"
    with pytest.raises(ValueError, match="another repository"):
        first.for_project(tmp_path / "foreign")
    with pytest.raises(ValueError, match="prepared Git source baseline"):
        DerivedStageInputs(
            JointCheckpoint.seal({**cp.to_wire(), "preparations": []}),
            unit.id,
        )


@pytest.mark.parametrize(
    "argv",
    [
        ("git", "status"),
        ("python", "-c", "print(1)"),
        ("npm", "install"),
        ("sh", "test.sh"),
        ("echo", "PASS"),
        ("pytest", "--collect-only"),
        ("python3", "-m", "unittest", "--help"),
        ("mvn", "test", "-DskipTests=true"),
        ("npm", "test", "--", "--passWithNoTests"),
    ],
)
def test_integration_rejects_non_test_commands(argv: tuple[str, ...]) -> None:
    assert not is_test_command(argv)


def test_integration_zero_test_success_is_not_a_pass(tmp_path: Path) -> None:
    result = CommandResult(
        argv=("python3", "-m", "unittest"),
        cwd=str(tmp_path),
        returncode=0,
        stdout="",
        stderr="Ran 0 tests in 0.001s\nOK",
        duration_ms=1,
    )
    with pytest.raises(ValueError, match="no executed tests"):
        _require_nonempty_test_run(result)
    _require_nonempty_test_run(result.model_copy(update={"stderr": "Ran 1 test in 0.1s\nOK"}))


@pytest.mark.parametrize(
    ("error", "returncode", "stderr"),
    [
        (
            CommandExecutionError("host path and secret must not escape"),
            127,
            "command could not start",
        ),
        (CommandTimedOut(("pytest",), 42), 124, "command timed out"),
    ],
)
def test_integration_command_failures_are_typed_and_redacted(
    tmp_path: Path,
    error: CommandExecutionError,
    returncode: int,
    stderr: str,
) -> None:
    class FailingExecutor:
        def run(
            self,
            arguments: tuple[str, ...],
            *,
            timeout_seconds: float | None = None,
        ) -> CommandResult:
            del arguments, timeout_seconds
            raise error

    result = _execute_integration_command(
        FailingExecutor(),
        ("pytest", "-q", "tests"),
        tmp_path,
        timeout_seconds=1,
    )
    assert result.returncode == returncode
    assert result.stderr == stderr
    assert "secret" not in result.stderr
    assert result.cwd == str(tmp_path)


def test_integration_zero_test_success_is_durable_failure() -> None:
    class EmptyExecutor:
        def run(
            self,
            arguments: tuple[str, ...],
            *,
            timeout_seconds: float | None = None,
        ) -> CommandResult:
            del timeout_seconds
            return CommandResult(
                argv=arguments,
                cwd="/tmp/candidate",
                returncode=0,
                stdout="Ran 0 tests in 0.001s\nOK",
                stderr="",
                duration_ms=3,
            )

    result = _execute_integration_command(
        EmptyExecutor(),
        ("python3", "-m", "unittest"),
        Path("/tmp/candidate"),
        timeout_seconds=1,
    )
    assert result.returncode == 1
    assert result.stderr == "integration reported no executed tests; cannot accept PASS"


def test_reference_only_unit_needs_no_native_delivery(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.design and cp.product_spec and cp.plan
    first, second = cp.scope.units
    design = cp.design.model_copy(
        update={"units": cp.design.units[:1], "reference_only": (second.id,)}
    )
    design.validate_for(cp.scope, cp.product_spec)
    check = cp.plan.integration_checks[0].model_copy(update={"unit_id": first.id})
    plan = cp.plan.model_copy(
        update={
            "design_sha256": digest(design),
            "units": cp.plan.units[:1],
            "integration_checks": (check,),
        }
    )
    plan.validate_for(cp.scope, cp.product_spec, design)


def test_integration_uses_project_tooling_and_imports_candidate_sources(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    binary = repository / ".venv" / "bin"
    binary.mkdir(parents=True)
    candidate = tmp_path / "candidate"
    sources = candidate / "src"
    sources.mkdir(parents=True)
    (sources / "candidate_value.py").write_text("VALUE = 'reviewed-candidate'\n")
    runner = binary / "pytest"
    runner.write_text(
        f"#!{sys.executable}\n"
        "import os\nfrom candidate_value import VALUE\n"
        "assert VALUE == 'reviewed-candidate'\n"
        "assert 'PRIVATE_TEST_SECRET' not in os.environ\n"
        "print('1 passed in 0.01s')\n"
    )
    runner.chmod(0o700)
    base = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    environment = _python_integration_environment(repository, candidate, base)
    executor = SubprocessCommandExecutor(
        candidate,
        _integration_permissions(("pytest",)),
        environment=environment,
        environment_allowlist=tuple(environment),
    )
    result = _execute_integration_command(executor, ("pytest",), candidate, timeout_seconds=10)
    assert result.returncode == 0
    assert "1 passed" in result.stdout
    assert result.cwd == str(candidate)
    assert base == {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    runner.unlink()
    binary.rmdir()
    (repository / ".venv").rmdir()
    (repository / ".venv").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="project-local"):
        _python_integration_environment(repository, candidate, base)


@pytest.mark.parametrize(
    "prefix", [("pytest",), ("python3", "-m", "pytest"), ("uv", "run", "pytest")]
)
def test_integration_pytest_paths_are_bound_to_candidate(
    tmp_path: Path, prefix: tuple[str, ...]
) -> None:
    _git("init", cwd=tmp_path)
    _git("config", "user.name", "Fixture", cwd=tmp_path)
    _git("config", "user.email", "fixture@example.invalid", cwd=tmp_path)
    (tmp_path / "test_candidate.py").write_text("def test_ok():\n    assert True\n")
    _git("add", "test_candidate.py", cwd=tmp_path)
    _git("commit", "-m", "candidate", cwd=tmp_path)
    candidate = _git_output("rev-parse", "HEAD", cwd=tmp_path)
    (tmp_path / "test_main_only.py").write_text("def test_ok():\n    assert True\n")
    _git("add", "test_main_only.py", cwd=tmp_path)
    _git("commit", "-m", "main advances", cwd=tmp_path)
    _validate_pytest_paths(tmp_path, candidate, (*prefix, "test_candidate.py::test_ok"), 1)
    _validate_pytest_paths(tmp_path, candidate, (*prefix, "./test_candidate.py"), 1)
    for path in ("test_main_only.py", "private-missing.py", "../test_candidate.py"):
        with pytest.raises(IntegrationCommandError, match="reviewed candidate") as error:
            _validate_pytest_paths(tmp_path, candidate, (*prefix, path), 1)
        assert path not in str(error.value)


def test_joint_schemas_are_in_sync_with_models() -> None:
    models: dict[str, type[DomainModel]] = {
        "requirement-create": CreateRequirement,
        "requirement-retirement": RequirementRetirement,
        "requirement-checkpoint": JointCheckpoint,
        "joint-product-spec": JointProductSpec,
        "joint-technical-design": JointTechnicalDesign,
        "joint-execution-plan": JointExecutionPlan,
    }
    for name, model in models.items():
        schema = json.loads(
            (Path(__file__).parents[2] / "schemas" / f"{name}.schema.json").read_text()
        )
        schema.pop("$id")
        schema.pop("$schema")
        assert schema == model.model_json_schema()


def test_product_dialogue_rejects_unknown_speaker() -> None:
    with pytest.raises(ValueError):
        DialogueMessage.model_validate({"speaker": "reviewer", "text": "Untrusted role"})


def test_joint_journal_only_allows_explicit_integration_replan(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.plan is not None
    failed = IntegrationEvidence(
        plan_sha256=digest(cp.plan),
        candidates=tuple(Candidate(unit_id=unit.id, revision="a" * 40) for unit in cp.scope.units),
        checks=(
            CommandResult(
                argv=cp.plan.integration_checks[0].argv,
                cwd=str(tmp_path),
                returncode=127,
                stdout="",
                stderr="command could not start",
                duration_ms=0,
            ),
        ),
    )
    blocked = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "stage": JointStage.BLOCKED,
            "integration": failed,
            "next_action": "Inspect joint integration evidence.",
        }
    )
    journal = JointJournal(tmp_path / "journal")
    journal.append(blocked, expected=None)
    replanning = JointCheckpoint.seal(
        {
            **blocked.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": blocked.checkpoint_sha256,
            "stage": JointStage.PLANNING,
            "plan": None,
            "next_action": "Produce a fresh complete integration plan.",
        }
    )
    journal.append(replanning, expected=blocked.checkpoint_sha256)

    changed_plan = cp.plan.model_copy(
        update={
            "integration_checks": (
                cp.plan.integration_checks[0].model_copy(update={"id": "fresh_check"}),
            )
        }
    )
    ordinary_mutation = JointCheckpoint.seal(
        {
            **blocked.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": blocked.checkpoint_sha256,
            "stage": JointStage.PLANNING,
            "plan": changed_plan,
            "next_action": "Attempt to replace the committed plan.",
        }
    )
    other_journal = JointJournal(tmp_path / "other-journal")
    other_journal.append(blocked, expected=None)
    with pytest.raises(ValueError, match="immutable"):
        other_journal.append(ordinary_mutation, expected=blocked.checkpoint_sha256)
