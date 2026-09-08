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
    RecoveryPlan,
    RecoveryRejected,
)
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
    "field", ["read_paths", "write_paths", "commands", "denied_paths", "project_root"]
)
def test_secret_metadata_never_enters_plan(tmp_path: Path, field: str) -> None:
    wire = json.loads(json.dumps(make_plan(tmp_path / "project").to_wire()))
    sensitive = "Bearer " + "x" * 24
    if field == "project_root":
        wire["source"]["scope"][field] = "/project/" + sensitive
    elif field == "denied_paths":
        wire[field] = [sensitive]
    else:
        wire["permissions"][field] = [sensitive]
    with pytest.raises(ValidationError):
        RecoveryPlan.create(**wire)
