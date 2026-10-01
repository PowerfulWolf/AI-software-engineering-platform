"""Recovery model/wire parity and explicit lineage/integrity checks."""

import json
from pathlib import Path
from typing import Annotated

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, TypeAdapter, ValidationError

from ai_software_engineer.domain import NetworkAccess
from ai_software_engineer.recovery import (
    CapturedChanges,
    RecoveryAuthorization,
    RecoveryPathRebinding,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScopeSupplement,
)
from ai_software_engineer.recovery.models import digest
from tests.recovery.test_authorization import Human, approval, make_plan

ADAPTER: TypeAdapter[RecoveryPlan | RecoveryAuthorization] = TypeAdapter(
    Annotated[RecoveryPlan | RecoveryAuthorization, Field(discriminator="kind")]
)
SCHEMA = json.loads(
    (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def test_wire_round_trip_and_schema(tmp_path: Path) -> None:
    plan = make_plan(tmp_path / "project")
    command = approval(plan)
    record = RecoveryAuthorization.create(command, Human().verify(command))
    for item in (plan, record):
        VALIDATOR.validate(item.to_wire())
        assert ADAPTER.validate_python(item.to_wire()) == item
        item.validate_integrity()


@pytest.mark.parametrize(
    "change", ["missing_kind", "extra", "status", "revision", "timestamp", "boolean", "privilege"]
)
def test_schema_and_python_reject_invalid_input(tmp_path: Path, change: str) -> None:
    wire = make_plan(tmp_path / "project").to_wire()
    # Decode for mutation in test code only; production accepts typed objects.
    payload = json.loads(json.dumps(wire))
    if change == "missing_kind":
        del payload["kind"]
    elif change == "extra":
        payload["verdict"] = "APPROVE"
    elif change == "status":
        payload["source"]["task_status"] = "NEW"
    elif change == "revision":
        payload["target_base_revision"] = "a" * 41
    elif change == "timestamp":
        payload["created_at"] = "2026-09-06T00:00:00"
    elif change == "boolean":
        payload["source"]["task_revision"] = True
    else:
        payload["permissions"]["can_merge"] = True
    assert list(VALIDATOR.iter_errors(payload))
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(payload)


def test_changed_baseline_has_new_plan_and_new_task_identity(tmp_path: Path) -> None:
    plan = make_plan(tmp_path / "project")
    changed = RecoveryPlan.create(**{**plan.to_wire(), "target_base_revision": "d" * 40})
    assert changed.plan_sha256 != plan.plan_sha256
    assert changed.new_task_id != plan.new_task_id
    with pytest.raises(RecoveryRejected):
        plan.model_copy(update={"target_base_revision": "d" * 40}).validate_integrity()


def test_historical_retry_plan_remains_readable_but_cannot_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
    from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
    from ai_software_engineer.recovery.native import NativeRecoverySourceReader

    original = make_plan(tmp_path / "project")
    plan = RecoveryPlan.create(
        **{
            **original.to_wire(),
            "retry_of_plan_sha256": "d" * 64,
            "retry_of_task_id": "task_old_retry",
            "retry_of_checkpoint_sha256": "e" * 64,
        }
    )
    VALIDATOR.validate(plan.to_wire())
    assert ADAPTER.validate_python(plan.to_wire()) == plan
    plan.validate_integrity()
    assert "retry_of_plan_sha256" not in original.to_wire()
    inspect = MagicMock(side_effect=AssertionError("legacy execution reached source inspection"))
    monkeypatch.setattr(NativeRecoverySourceReader, "inspect", inspect)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    with pytest.raises(RecoveryRejected, match="current recovery source"):
        NativeRecoveryFactsVerifier(config, {}).validate(plan)
    inspect.assert_not_called()
    original.require_execution_supported()
    with pytest.raises(RecoveryRejected, match="read-only"):
        plan.require_execution_supported()


def test_target_permissions_are_hash_bound_and_may_only_narrow_source(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "project")
    source = old.permissions.model_copy(update={"commands": ("git status", "git commit")})
    target = source.model_copy(update={"commands": ("git status",)})
    plan = RecoveryPlan.create(
        **{
            **old.to_wire(),
            "permissions": source,
            "target_permissions": target,
        }
    )
    VALIDATOR.validate(plan.to_wire())
    assert plan.effective_target_permissions == target
    assert plan.plan_sha256 != old.plan_sha256
    assert (
        RecoveryPlan.model_validate(old.to_wire()).effective_target_permissions == old.permissions
    )
    for expanded in (
        target.model_copy(update={"read_paths": (*source.read_paths, "docs/**")}),
        target.model_copy(update={"write_paths": (*source.write_paths, "tests/**")}),
        target.model_copy(update={"commands": (*source.commands, "git push")}),
        target.model_copy(update={"network": NetworkAccess.MODEL_ENDPOINT_ONLY}),
    ):
        with pytest.raises(ValidationError, match="may only narrow"):
            RecoveryPlan.create(
                **{
                    **old.to_wire(),
                    "permissions": source,
                    "target_permissions": expanded,
                }
            )


@pytest.mark.parametrize("requested", [False, True])
def test_scope_supplement_and_approval_are_hash_bound_into_the_plan(
    tmp_path: Path, requested: bool
) -> None:
    from ai_software_engineer.recovery.models import RecoveryRequestedFile, RecoveryScopeRequest

    old = make_plan(tmp_path / "project")
    supplement = RecoveryScopeSupplement.create(
        scope=old.source.scope,
        task_id=old.source.task_id,
        task_revision=old.source.task_revision,
        checkpoint_sha256=old.source.checkpoint_sha256,
        base_revision=old.source.base_revision,
        permissions_sha256=digest(old.permissions.to_wire()),
        denied_paths_sha256=digest(old.denied_paths),
        paths=("src/omitted.py",),
        request=RecoveryScopeRequest(
            progress_artifact_id="art_progress_001",
            progress_sha256="a" * 64,
            paths=("src/omitted.py",),
            reason="Necessary file for the approved criteria",
        )
        if requested
        else None,
        requested_files=(
            RecoveryRequestedFile(
                path="src/omitted.py",
                mode="100644",
                blob_id="a" * 40,
            ),
        )
        if requested
        else None,
    )
    if not requested:
        assert "request" not in supplement.to_wire()
        assert "requested_files" not in supplement.to_wire()
        assert supplement.supplement_sha256 == digest(
            {k: v for k, v in supplement.to_wire().items() if k != "supplement_sha256"}
        )
    expanded = old.permissions.model_copy(
        update={
            "read_paths": (*old.permissions.read_paths, *supplement.paths),
            "write_paths": (*old.permissions.write_paths, *supplement.paths),
        }
    )
    plan = RecoveryPlan.create(
        **{
            **old.to_wire(),
            "scope_supplement": supplement,
            "scope_approval_reference": "console-scope-approval",
            "permissions": expanded,
        }
    )

    VALIDATOR.validate(plan.to_wire())
    assert plan.plan_sha256 != old.plan_sha256
    assert RecoveryPlan.model_validate(plan.to_wire()) == plan
    if requested:
        from jsonschema.exceptions import ValidationError as SchemaValidationError

        for field in ("request", "requested_files"):
            for null in (False, True):
                wire = plan.to_wire()
                assert isinstance(wire["scope_supplement"], dict)
                if null:
                    wire["scope_supplement"][field] = None
                else:
                    del wire["scope_supplement"][field]
                with pytest.raises(SchemaValidationError):
                    VALIDATOR.validate(wire)
                with pytest.raises(ValidationError):
                    RecoveryPlan.model_validate(wire)
    for invalid in (
        {"scope_approval_reference": None},
        {"scope_supplement": None},
        {"permissions": old.permissions},
        {"scope_supplement": supplement.model_copy(update={"supplement_sha256": "0" * 64})},
    ):
        with pytest.raises((ValidationError, ValueError)):
            RecoveryPlan.create(**{**plan.to_wire(), **invalid})


def test_exact_path_rebinding_is_hash_bound_and_does_not_allow_ambient_expansion(
    tmp_path: Path,
) -> None:
    old = make_plan(tmp_path / "project")
    source = old.permissions.model_copy(
        update={
            "write_paths": (
                "src/ai_software_engineer/web_console/static/app.js",
                "tests/team_view/ui.test.cjs",
            )
        }
    )
    target = source.model_copy(
        update={
            "write_paths": (
                "src/ai_software_engineer/team_view/app.js",
                "tests/team_view/ui.test.cjs",
            )
        }
    )
    rebinding = RecoveryPathRebinding(
        source_path="src/ai_software_engineer/web_console/static/app.js",
        target_path="src/ai_software_engineer/team_view/app.js",
    )
    plan = RecoveryPlan.create(
        **{
            **old.to_wire(),
            "permissions": source,
            "target_permissions": target,
            "path_rebindings": (rebinding,),
        }
    )
    VALIDATOR.validate(plan.to_wire())
    assert plan.rebound_write_paths(source.write_paths) == target.write_paths
    assert plan.plan_sha256 != old.plan_sha256
    with pytest.raises(ValidationError, match="approved path rebindings"):
        RecoveryPlan.create(
            **{
                **old.to_wire(),
                "permissions": source,
                "target_permissions": target,
            }
        )
    with pytest.raises(ValidationError, match="approved path rebindings"):
        RecoveryPlan.create(
            **{
                **old.to_wire(),
                "permissions": source,
                "target_permissions": target.model_copy(
                    update={"write_paths": (*target.write_paths, "docs/**")}
                ),
                "path_rebindings": (rebinding,),
            }
        )


def test_capture_tamper_and_cross_task_are_rejected(tmp_path: Path) -> None:
    plan = make_plan(tmp_path / "project")
    wire = plan.capture.to_wire()
    wire["patch"] = "untrusted different content"
    with pytest.raises(ValidationError):
        CapturedChanges.model_validate(wire)
    source = plan.source.model_copy(update={"task_id": "task_another"})
    with pytest.raises(ValidationError):
        RecoveryPlan.create(**{**plan.to_wire(), "source": source})


def test_secret_reference_never_enters_authorization_record(tmp_path: Path) -> None:
    command = approval(make_plan(tmp_path / "project"))
    with pytest.raises(ValidationError):
        type(command).model_validate(
            {**command.to_wire(), "approval_reference": "Bearer " + "x" * 24}
        )


@pytest.mark.parametrize(
    "field", ["read_paths", "write_paths", "commands", "denied_paths", "repository_root"]
)
def test_secret_metadata_never_enters_plan(tmp_path: Path, field: str) -> None:
    wire = json.loads(json.dumps(make_plan(tmp_path / "project").to_wire()))
    sensitive = "Bearer " + "x" * 24
    if field == "repository_root":
        wire["source"]["scope"][field] = "/project/" + sensitive
    elif field == "denied_paths":
        wire[field] = [sensitive]
    else:
        wire["permissions"][field] = [sensitive]
    with pytest.raises(ValidationError):
        RecoveryPlan.create(**wire)
