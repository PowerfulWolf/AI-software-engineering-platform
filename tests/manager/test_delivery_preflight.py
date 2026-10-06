"""Read-only preflight observations through real Git and real tool files.

No planned test executable is launched here. Controlled-discovery facts are
unit-level inputs; registered provider/public claim wiring needs independent
production-factory tests and actual executor boundary coverage.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Never, cast

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentDefinition, AgentRole, ArtifactKind, Task, TaskStatus
from ai_software_engineer.domain.execution_window import (
    PlannedVerificationInspection,
    PlannedVerificationRequirement,
)
from ai_software_engineer.domain.native_verification import (
    NativeVerificationCapabilityDetail,
    NativeVerificationWaitReason,
)
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightObservation,
    DeliveryPreflightReceipt,
    DeliveryPreflightScope,
    DiscoveredControlledCapability,
    inspect_delivery_prerequisites,
)
from ai_software_engineer.manager.production_backend import (
    ProductionProjectDeliveryBackend,
    _ProjectFacts,
)
from ai_software_engineer.manager.python_verification_discovery import PythonMysqlDiscoveryError
from tests.domain.factories import NOW, make_agent, make_task
from tests.manager.test_native_verification import _fixture

_SCOPE = DeliveryPreflightScope(
    team_id="team_preflight",
    project_id="project_preflight",
    repository_id="repo_preflight",
    requirement_id="delivery_preflight",
)
_CAPABILITY = "codex_sandbox_pytest_mysql_v1"
_SECRET_SENTINEL = "PRECHECK_MUST_NEVER_CAPTURE_THIS_PROVIDER_TOKEN"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("/usr/bin/git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
    ).stdout.strip()


def _prepare(tmp_path: Path) -> tuple[Task, dict[AgentRole, AgentDefinition], dict[str, str], Path]:
    root = (tmp_path / "repository").resolve()
    root.mkdir()
    (root / "tests").mkdir()
    # The source body would fail if accidentally executed during preflight.
    (root / "tests" / "test_present.py").write_text(
        "raise AssertionError('preflight executed candidate')\n"
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Preflight Test")
    _git(root, "config", "user.email", "preflight@example.invalid")
    _git(root, "add", "tests/test_present.py")
    _git(root, "commit", "-qm", "tracked verification entry")
    base = make_task()
    task = Task.model_validate(
        {
            **base.to_wire(),
            "repository": str(root),
            "base_ref": _git(root, "rev-parse", "HEAD"),
            "status": TaskStatus.IMPLEMENTING.value,
            "attempts": 1,
        }
    )
    coder = make_agent().model_copy(
        update={
            "permissions": make_agent().permissions.model_copy(
                update={"read_paths": ("**",), "write_paths": ("tests/**", "src/**")}
            ),
        }
    )
    qa = AgentDefinition.model_validate(
        {
            **coder.to_wire(),
            "id": "agent_qa_preflight",
            "role": AgentRole.QA.value,
            "input_artifacts": [ArtifactKind.PLAN.value, ArtifactKind.IMPLEMENTATION_REPORT.value],
            "output_artifacts": [ArtifactKind.QA_REPORT.value],
            "permissions": {
                **coder.permissions.to_wire(),
                "write_paths": [],
                "commands": ["pytest", "python", "python3", "uv"],
            },
        }
    )
    tools = (tmp_path / "tools").resolve()
    tools.mkdir()
    sentinel = tmp_path / "tool_was_executed"
    executable = tools / "pytest"
    executable.write_text(
        "#!/bin/sh\nprintf '" + _SECRET_SENTINEL + "'\ntouch '" + str(sentinel) + "'\n"
    )
    executable.chmod(0o755)
    # Unknown-module/-c rejection must not be disguised as binary-not-found.
    for name in ("python", "python3", "uv"):
        (tools / name).write_bytes(executable.read_bytes())
        (tools / name).chmod(0o755)
    return (
        task,
        {AgentRole.CODER: coder, AgentRole.QA: qa},
        {"PATH": str(tools), "API_KEY": _SECRET_SENTINEL},
        sentinel,
    )


def _requirement(
    argv: tuple[str, ...] = ("pytest", "tests/test_present.py", "-q"),
    *,
    planned: tuple[str, ...] = (),
    capability: str | None = None,
) -> PlannedVerificationRequirement:
    return PlannedVerificationRequirement(
        id="verify_focused",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        argv=argv,
        planned_new_files=planned,
        controlled_capability_kind=capability,
    )


def _inspect(
    task: Task,
    definitions: Mapping[AgentRole, AgentDefinition],
    environment: Mapping[str, str],
    *,
    requirement: PlannedVerificationRequirement | None = None,
    route: Literal["codex_cli", "responses"] = "responses",
    capabilities: tuple[DiscoveredControlledCapability, ...] = (),
    discovery_failure: NativeVerificationWaitReason | None = None,
    discovery_detail: NativeVerificationCapabilityDetail | None = None,
) -> DeliveryPreflightReceipt:
    return inspect_delivery_prerequisites(
        scope=_SCOPE,
        task=task,
        plan_sha256="b" * 64,
        requirements=(_requirement() if requirement is None else requirement,),
        definitions=definitions,
        route_kinds={AgentRole.QA: route},
        environment=environment,
        controlled_capabilities=capabilities,
        controlled_discovery_failure=discovery_failure,
        controlled_discovery_detail=discovery_detail,
        checked_at=NOW,
    )


def test_preflight_reads_current_tool_and_pinned_tree_without_running_candidate_or_tool(
    tmp_path: Path,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    receipt = _inspect(task, definitions, environment)
    assert receipt.status == "READY"
    receipt.validate_integrity()
    observation = receipt.observations[0]
    assert observation.reason_code == "AUTHORIZED_TOOL_PRESENT"
    assert observation.executable == str(Path(environment["PATH"]) / "pytest")
    assert (
        observation.executable_sha256
        == hashlib.sha256(Path(observation.executable).read_bytes()).hexdigest()
    )
    assert not sentinel.exists()
    assert _SECRET_SENTINEL not in json.dumps(receipt.to_wire())


def test_local_venv_does_not_prove_the_actual_executor_path_has_the_tool(tmp_path: Path) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    local = Path(task.repository) / ".venv" / "bin"
    local.mkdir(parents=True)
    (local / "pytest").write_bytes((Path(environment["PATH"]) / "pytest").read_bytes())
    (local / "pytest").chmod(0o755)
    missing = tmp_path / "empty_tools"
    missing.mkdir()
    receipt = _inspect(task, definitions, {"PATH": str(missing)})
    assert receipt.status == "WAIT_ENGINEERING"
    assert receipt.observations[0].reason_code == "VERIFICATION_EXECUTABLE_UNAVAILABLE"
    assert not sentinel.exists()


def test_codex_verifier_needs_registered_controlled_execution_not_only_a_pytest_binary(
    tmp_path: Path,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    receipt = _inspect(task, definitions, environment, route="codex_cli")
    assert receipt.status == "WAIT_ENGINEERING"
    assert receipt.observations[0].reason_code == "CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED"
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "reason",
    [
        NativeVerificationWaitReason.UNSUPPORTED_SWIFT_FILTER,
        NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT,
        NativeVerificationWaitReason.NATIVE_UI_PREREQUISITE,
        NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE,
    ],
)
def test_registered_discovery_failure_retains_typed_root_cause_without_executing_tools(
    tmp_path: Path,
    reason: NativeVerificationWaitReason,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    check = (
        _inspection("native_ui")
        if reason is NativeVerificationWaitReason.NATIVE_UI_PREREQUISITE
        else _requirement(capability=_CAPABILITY)
    )
    receipt = _inspect(
        task,
        definitions,
        environment,
        requirement=check,
        route="codex_cli",
        discovery_failure=reason,
    )
    receipt.validate_integrity()
    assert receipt.status == "WAIT_ENGINEERING"
    assert receipt.observations[0].reason_code == "CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED"
    assert receipt.observations[0].native_wait_reason is reason
    assert receipt.observations[0].to_wire()["native_wait_reason"] == reason.value
    assert not sentinel.exists()
    assert _SECRET_SENTINEL not in json.dumps(receipt.to_wire())
    with pytest.raises(ValueError, match="changed"):
        receipt.model_copy(
            update={
                "observations": (
                    receipt.observations[0].model_copy(
                        update={
                            "native_wait_reason": NativeVerificationWaitReason.FACTS_CHANGED,
                        }
                    ),
                ),
            }
        ).validate_integrity()


def test_registered_discovery_detail_is_safe_and_part_of_receipt_integrity(
    tmp_path: Path,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    receipt = _inspect(
        task,
        definitions,
        environment,
        route="codex_cli",
        requirement=_requirement(capability=_CAPABILITY),
        discovery_failure=NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE,
        discovery_detail=NativeVerificationCapabilityDetail.DOCKER_DAEMON_UNAVAILABLE,
    )
    observation = receipt.observations[0]
    assert (
        observation.native_wait_detail
        is NativeVerificationCapabilityDetail.DOCKER_DAEMON_UNAVAILABLE
    )
    assert "docker" in observation.native_wait_detail.value.lower()
    assert "stderr" not in json.dumps(receipt.to_wire()).lower()
    assert not sentinel.exists()
    tampered = receipt.model_copy(
        update={
            "observations": (
                observation.model_copy(
                    update={
                        "native_wait_detail": (
                            NativeVerificationCapabilityDetail.MYSQL_IMAGE_UNAVAILABLE
                        )
                    }
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="changed"):
        tampered.validate_integrity()


def test_unused_registered_discovery_failure_does_not_block_ordinary_responses_tools(
    tmp_path: Path,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    receipt = _inspect(
        task,
        definitions,
        environment,
        discovery_failure=NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT,
    )
    assert receipt.status == "READY"
    assert receipt.observations[0].native_wait_reason is None
    assert "native_wait_reason" not in receipt.observations[0].to_wire()
    assert not sentinel.exists()


def test_ready_controlled_capability_is_not_overridden_by_another_discovery_failure(
    tmp_path: Path,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    discovered = DiscoveredControlledCapability(
        kind=_CAPABILITY,
        role=AgentRole.QA,
        source_revision=task.base_ref,
        discovery_sha256="c" * 64,
        requirement_ids=("verify_focused",),
    )
    receipt = _inspect(
        task,
        definitions,
        environment,
        requirement=_requirement(capability=_CAPABILITY),
        route="codex_cli",
        capabilities=(discovered,),
        discovery_failure=NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT,
    )
    assert receipt.status == "READY"
    assert receipt.observations[0].native_wait_reason is None
    assert not sentinel.exists()


def test_optional_discovery_root_cause_preserves_legacy_receipt_digest(tmp_path: Path) -> None:
    task, definitions, environment, _ = _prepare(tmp_path)
    receipt = _inspect(task, definitions, environment, route="codex_cli")
    old_payload = receipt.model_dump(mode="json")
    observations = old_payload["observations"]
    assert all("native_wait_reason" not in item for item in observations)
    checksum = old_payload.pop("receipt_sha256")
    assert (
        checksum
        == hashlib.sha256(
            json.dumps(
                old_payload,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    restored = DeliveryPreflightReceipt.model_validate({**old_payload, "receipt_sha256": checksum})
    restored.validate_integrity()


@pytest.mark.parametrize(
    "change",
    [
        {"status": "READY"},
        {"reason_code": "VERIFICATION_SELECTED_FILE_MISSING"},
        {"native_wait_reason": "arbitrary provider response or secret"},
    ],
)
def test_native_discovery_root_cause_cannot_be_attached_to_success_or_free_text(
    change: dict[str, str],
) -> None:
    values = {
        "requirement_id": "verify_focused",
        "status": "WAIT_ENGINEERING",
        "reason_code": "CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED",
        "native_wait_reason": NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE.value,
    }
    with pytest.raises(ValueError):
        DeliveryPreflightObservation.model_validate({**values, **change})


@pytest.mark.parametrize(
    "reason",
    [
        NativeVerificationWaitReason.UNSUPPORTED_SWIFT_FILTER,
        NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT,
        NativeVerificationWaitReason.NATIVE_UI_PREREQUISITE,
        NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE,
    ],
)
def test_production_backend_preserves_actual_registered_discovery_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: NativeVerificationWaitReason,
) -> None:
    fixture = _fixture(tmp_path)
    assert fixture.plan.content.verification_requirements is not None
    check = fixture.plan.content.verification_requirements[0]
    if reason is NativeVerificationWaitReason.UNSUPPORTED_SWIFT_FILTER:
        check = check.model_copy(
            update={
                "argv": (
                    "swift",
                    "test",
                    "--disable-automatic-resolution",
                    "--skip-update",
                    "--filter",
                    "GreetingTests.testGreeting",
                ),
                "controlled_capability_kind": "macos_swift_sandbox_v1",
            }
        )
    elif reason is NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT:
        check = check.model_copy(update={"argv": ("pytest", "tests/test_case.py", "-q")})
    elif reason is NativeVerificationWaitReason.NATIVE_UI_PREREQUISITE:
        check = _inspection("native_ui")
    else:

        def unavailable(**kwargs: object) -> Never:
            raise PythonMysqlDiscoveryError(
                NativeVerificationCapabilityDetail.DOCKER_DAEMON_UNAVAILABLE
            )

        monkeypatch.setattr(
            "ai_software_engineer.manager.native_verification.discover_python_mysql_host_prerequisites",
            unavailable,
        )
    plan = fixture.plan.model_copy(
        update={
            "content": fixture.plan.content.model_copy(
                update={"verification_requirements": (check,)}
            ),
        }
    )
    coder = make_agent()
    qa = AgentDefinition.model_validate(
        {
            **coder.to_wire(),
            "id": "agent_qa_prerequisite",
            "role": AgentRole.QA.value,
            "input_artifacts": [ArtifactKind.PLAN.value, ArtifactKind.IMPLEMENTATION_REPORT.value],
            "output_artifacts": [ArtifactKind.QA_REPORT.value],
            "permissions": {
                **coder.permissions.to_wire(),
                "write_paths": [],
                "commands": ["pytest", "swift test"],
            },
        }
    )
    # The production method's only composition dependencies are current routes,
    # environment and clock. Real Git and the actual registered discovery run;
    # there is no Host/database/model or candidate execution in this unit.
    backend = cast(
        ProductionProjectDeliveryBackend,
        SimpleNamespace(
            _config=ProductionConfig(
                platform_root=str(tmp_path / "platform"),
                model_routes=(
                    ProviderRouteConfig(
                        provider="codex", model="fixture", kind=ModelProviderKind.CODEX_CLI
                    ),
                ),
            ),
            _environment={"PATH": "/usr/bin:/bin"},
            _clock=lambda: NOW,
        ),
    )
    receipt = ProductionProjectDeliveryBackend._inspect_native_prerequisites(
        backend,
        cast(_ProjectFacts, None),
        fixture.task,
        plan,
        {AgentRole.CODER: coder, AgentRole.QA: qa},
        fixture.registry,
        fixture.task.base_ref,
    )
    receipt.validate_integrity()
    assert receipt.status == "WAIT_ENGINEERING"
    assert receipt.observations[0].native_wait_reason is reason
    if reason is NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE:
        assert (
            receipt.observations[0].native_wait_detail
            is NativeVerificationCapabilityDetail.DOCKER_DAEMON_UNAVAILABLE
        )
    assert _SECRET_SENTINEL not in json.dumps(receipt.to_wire())
    assert not (tmp_path / "sidecar/native-role-verification").exists()


def test_controlled_discovery_must_match_kind_role_source_and_exact_requirement(
    tmp_path: Path,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    good = DiscoveredControlledCapability(
        kind=_CAPABILITY,
        role=AgentRole.QA,
        source_revision=task.base_ref,
        discovery_sha256="c" * 64,
        requirement_ids=("verify_focused",),
    )
    check = _requirement(capability=_CAPABILITY)
    ready = _inspect(
        task, definitions, environment, requirement=check, route="codex_cli", capabilities=(good,)
    )
    assert ready.status == "READY"
    assert ready.observations[0].controlled_discovery_sha256 == "c" * 64
    for update in (
        {"kind": "different_capability"},
        {"role": AgentRole.REVIEWER},
        {"source_revision": "d" * 40},
        {"requirement_ids": ("different_requirement",)},
    ):
        denied = _inspect(
            task,
            definitions,
            environment,
            requirement=check,
            route="codex_cli",
            capabilities=(good.model_copy(update=update),),
        )
        assert denied.status == "WAIT_ENGINEERING"
    assert not sentinel.exists()


def test_test_to_be_implemented_is_admitted_only_with_explicit_coder_write_scope(
    tmp_path: Path,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    check = _requirement(("pytest", "tests/test_new.py", "-q"), planned=("tests/test_new.py",))
    receipt = _inspect(task, definitions, environment, requirement=check)
    assert receipt.status == "READY"
    assert not (Path(task.repository) / "tests/test_new.py").exists()
    blocked_coder = definitions[AgentRole.CODER].model_copy(
        update={
            "permissions": definitions[AgentRole.CODER].permissions.model_copy(
                update={"write_paths": ("src/**",)}
            ),
        }
    )
    denied = _inspect(
        task, {**definitions, AgentRole.CODER: blocked_coder}, environment, requirement=check
    )
    assert denied.status == "WAIT_ENGINEERING"
    assert denied.observations[0].reason_code == "VERIFICATION_COMMAND_AUTHORIZATION_REQUIRED"
    assert not sentinel.exists()


@pytest.mark.parametrize("declared_new", [False, True])
def test_task_denied_paths_apply_to_existing_and_planned_test_files(
    tmp_path: Path, declared_new: bool
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    path = "tests/test_new.py" if declared_new else "tests/test_present.py"
    assert task.constraints is not None
    task = task.model_copy(
        update={"constraints": task.constraints.model_copy(update={"denied_paths": (path,)})}
    )
    check = _requirement(("pytest", path), planned=(path,) if declared_new else ())
    receipt = _inspect(task, definitions, environment, requirement=check)
    assert receipt.status == "WAIT_ENGINEERING"
    assert receipt.observations[0].reason_code == "VERIFICATION_COMMAND_AUTHORIZATION_REQUIRED"
    assert not sentinel.exists()


def test_untracked_current_checkout_test_is_not_a_pinned_source_test(tmp_path: Path) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    (Path(task.repository) / "tests/test_new.py").write_text("assert True\n")
    receipt = _inspect(
        task, definitions, environment, requirement=_requirement(("pytest", "tests/test_new.py"))
    )
    assert receipt.status == "WAIT_ENGINEERING"
    assert receipt.observations[0].reason_code == "VERIFICATION_SELECTED_FILE_MISSING"
    assert not sentinel.exists()


def test_empty_verification_list_cannot_satisfy_approved_acceptance(tmp_path: Path) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    receipt = inspect_delivery_prerequisites(
        scope=_SCOPE,
        task=task,
        plan_sha256="b" * 64,
        requirements=(),
        definitions=definitions,
        route_kinds={AgentRole.QA: "responses"},
        environment=environment,
        checked_at=NOW,
    )
    assert receipt.status == "WAIT_ENGINEERING"
    assert receipt.observations[0].reason_code == "VERIFICATION_ENTRYPOINTS_REQUIRED"
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ("python", "-c", "print('not a test')"),
        ("python", "-m", "unknown_module"),
        ("uv", "run", "python", "-c", "print('not a test')"),
        ("pytest",),
        ("pytest", "tests"),
        ("pytest", "tests/test_present.py", "tests"),
        ("pytest", "tests/test_present.py", "."),
        ("pytest", "tests/test_present.py", "--pyargs", "foreign_package"),
        ("pytest", "tests/test_present.py", "--override-ini", "testpaths=tests"),
        ("pytest", "tests/test_present.py", "--collect-only"),
        ("python", "-m", "unittest", "discover"),
    ],
)
def test_preflight_rejects_inline_unknown_modules_and_hidden_suite_scope_without_execution(
    tmp_path: Path,
    argv: tuple[str, ...],
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    receipt = _inspect(task, definitions, environment, requirement=_requirement(argv))
    assert receipt.status == "WAIT_ENGINEERING"
    assert receipt.observations[0].reason_code == "VERIFICATION_COMMAND_AUTHORIZATION_REQUIRED"
    assert not sentinel.exists()
    assert _SECRET_SENTINEL not in json.dumps(receipt.to_wire())


def test_receipt_rejects_mutation_and_binds_actual_role_policy(tmp_path: Path) -> None:
    task, definitions, environment, _ = _prepare(tmp_path)
    receipt = _inspect(task, definitions, environment)
    restored = DeliveryPreflightReceipt.model_validate_json(receipt.model_dump_json())
    restored.validate_integrity()
    with pytest.raises(ValueError, match="changed"):
        restored.model_copy(update={"plan_sha256": "f" * 64}).validate_integrity()
    changed = definitions[AgentRole.QA].model_copy(
        update={
            "permissions": definitions[AgentRole.QA].permissions.model_copy(
                update={"commands": ("pytest",)}
            ),
        }
    )
    other = _inspect(task, {**definitions, AgentRole.QA: changed}, environment)
    assert other.frozen_policy_sha256 != receipt.frozen_policy_sha256


def _inspection(
    kind: Literal["source", "document", "native_ui"] = "source",
) -> PlannedVerificationRequirement:
    return PlannedVerificationRequirement(
        id="verify_inspection",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        inspection=PlannedVerificationInspection(
            kind=kind,
            paths=() if kind == "native_ui" else ("tests/test_present.py",),
            checklist=("Inspect the exact approved acceptance target",),
            scenario_sha256="d" * 64 if kind == "native_ui" else None,
        ),
        verification_levels=(
            "ui"
            if kind == "native_ui"
            else "documentation"
            if kind == "document"
            else "inspection",
        ),
        controlled_capability_kind="macos_mock_ax_v1" if kind == "native_ui" else None,
    )


@pytest.mark.parametrize("kind", ["source", "document"])
def test_declared_noncommand_inspection_does_not_require_or_launch_a_test_tool(
    tmp_path: Path,
    kind: Literal["source", "document"],
) -> None:
    task, definitions, _environment, sentinel = _prepare(tmp_path)
    empty_tools = tmp_path / "missing_tools"
    empty_tools.mkdir()
    check = _inspection(kind)
    receipt = _inspect(
        task, definitions, {"PATH": str(empty_tools)}, requirement=check, route="codex_cli"
    )
    assert receipt.status == "READY"
    assert receipt.observations[0].reason_code == "AUTHORIZED_INSPECTION_TARGETS_PRESENT"
    assert receipt.observations[0].executable is None
    assert not sentinel.exists()


def test_source_inspection_cannot_read_denied_missing_or_unapproved_future_files(
    tmp_path: Path,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    check = _inspection()
    assert task.constraints is not None
    denied_task = task.model_copy(
        update={
            "constraints": task.constraints.model_copy(
                update={"denied_paths": ("tests/test_present.py",)}
            )
        }
    )
    denied = _inspect(denied_task, definitions, environment, requirement=check)
    assert denied.status == "WAIT_ENGINEERING"
    assert denied.observations[0].reason_code == "VERIFICATION_INSPECTION_AUTHORIZATION_REQUIRED"
    assert check.inspection is not None
    missing = PlannedVerificationRequirement.model_validate(
        {
            **check.to_wire(),
            "inspection": {**check.inspection.to_wire(), "paths": ["tests/test_new.py"]},
        }
    )
    absent = _inspect(task, definitions, environment, requirement=missing)
    assert absent.status == "WAIT_ENGINEERING"
    assert absent.observations[0].reason_code == "VERIFICATION_INSPECTION_FILE_MISSING"
    planned = missing.model_copy(update={"planned_new_files": ("tests/test_new.py",)})
    assert _inspect(task, definitions, environment, requirement=planned).status == "READY"
    coder = definitions[AgentRole.CODER]
    restricted = coder.model_copy(
        update={"permissions": coder.permissions.model_copy(update={"write_paths": ("src/**",)})}
    )
    assert (
        _inspect(
            task, {**definitions, AgentRole.CODER: restricted}, environment, requirement=planned
        ).status
        == "WAIT_ENGINEERING"
    )
    assert not sentinel.exists()


def test_native_ui_inspection_requires_registered_controlled_capability_on_every_route(
    tmp_path: Path,
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    check = _inspection("native_ui")
    for route in ("codex_cli", "responses"):
        assert (
            _inspect(task, definitions, environment, requirement=check, route=route).status
            == "WAIT_ENGINEERING"
        )
    discovery = DiscoveredControlledCapability(
        kind="macos_mock_ax_v1",
        role=AgentRole.QA,
        source_revision=task.base_ref,
        discovery_sha256="c" * 64,
        requirement_ids=(check.id,),
    )
    receipt = _inspect(task, definitions, environment, requirement=check, capabilities=(discovery,))
    assert receipt.status == "READY"
    assert receipt.observations[0].controlled_discovery_sha256 == discovery.discovery_sha256
    assert not sentinel.exists()


@pytest.mark.parametrize("level", ["unit", "integration", "e2e", "acceptance"])
def test_inspection_cannot_replace_an_approved_executable_test(level: str) -> None:
    from ai_software_engineer.domain.project_delivery import AcceptanceDesignMapping, PlanTestItem

    check = _inspection()
    with pytest.raises(ValueError, match="weaken"):
        PlannedVerificationRequirement.model_validate(
            {**check.to_wire(), "verification_levels": [level]}
        )
    assert check.inspection is not None
    with pytest.raises(ValueError, match="weaken"):
        AcceptanceDesignMapping(
            acceptance_criterion_id="ac_models_01",
            verification_strategy="Read source",
            test_levels=(level,),
            verification_inspection=check.inspection,
        )
    with pytest.raises(ValueError, match="weaken"):
        PlanTestItem(
            id="inspect",
            acceptance_criterion_ids=("ac_models_01",),
            level=level,
            verification="Read source",
            verification_inspection=check.inspection,
        )


def test_inspection_and_command_are_mutually_exclusive_and_ui_scenario_is_exact() -> None:
    check = _inspection()
    with pytest.raises(ValueError, match="exactly one"):
        PlannedVerificationRequirement.model_validate(
            {**check.to_wire(), "argv": ["pytest", "tests/test_present.py"]}
        )
    with pytest.raises(ValueError, match="exactly one"):
        PlannedVerificationRequirement.model_validate(
            {"id": "empty", "role": "qa", "criterion_ids": ["ac_models_01"]}
        )
    with pytest.raises(ValueError, match="exact registered scenario"):
        PlannedVerificationInspection(kind="native_ui", checklist=("Inspect UI",))
    ui = _inspection("native_ui")
    with pytest.raises(ValueError, match="registered executor"):
        PlannedVerificationRequirement.model_validate(
            {**ui.to_wire(), "controlled_capability_kind": None}
        )


@pytest.mark.parametrize("registered", [False, True])
def test_responses_explicit_controlled_capability_requires_the_registered_discovery(
    tmp_path: Path, registered: bool
) -> None:
    task, definitions, environment, sentinel = _prepare(tmp_path)
    discovered = DiscoveredControlledCapability(
        kind=_CAPABILITY,
        role=AgentRole.QA,
        source_revision=task.base_ref,
        discovery_sha256="c" * 64,
        requirement_ids=("verify_focused",),
    )
    receipt = _inspect(
        task,
        definitions,
        environment,
        route="responses",
        requirement=_requirement(capability=_CAPABILITY),
        capabilities=(discovered,) if registered else (),
    )
    assert receipt.status == ("READY" if registered else "WAIT_ENGINEERING")
    assert receipt.observations[0].reason_code == (
        "CONTROLLED_CAPABILITY_DISCOVERED"
        if registered
        else "CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED"
    )
    assert not sentinel.exists()
