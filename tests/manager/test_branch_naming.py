"""Approved semantic intent survives projection; old wire/hash facts stay unchanged."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain import (
    ProductSpec,
    StageContractMismatch,
    StageIntegrityError,
    Task,
    derive_delivery_task,
    require_product_approval,
)
from ai_software_engineer.domain.task import task_matches_dispatch
from ai_software_engineer.manager.production_agents import (
    ProductDraft,
    StructuredProductAgentAdapter,
)
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryPlan, RecoveryRejected
from tests.manager.test_contracts import (
    approval,
    execution_plan,
    preparation,
    product_spec,
    request,
    technical_design,
)
from tests.manager.test_production_agents import _StructuredClient
from tests.product.test_agents import _request
from tests.recovery.test_authorization import make_plan


@pytest.mark.parametrize("kind", ["feature", "bugfix"])
def test_approved_name_is_frozen_in_task_and_approval(tmp_path: Path, kind: str) -> None:
    prepared = preparation(tmp_path)
    req = request(prepared)
    name = f"ai/{kind}/project-switch"
    spec = product_spec(req, branch_name=name)
    approved = approval(spec)
    design = technical_design(spec, approved)
    plan = execution_plan(spec, design)
    task = derive_delivery_task(
        prepared,
        req,
        spec,
        approved,
        design,
        plan,
        task_id="task_named_001",
        repository=prepared.repository_root,
        base_ref="a" * 40,
        max_attempts=3,
        created_at=plan.created_at,
    )
    assert task.branch_name == name
    assert task_matches_dispatch(task.model_copy(update={"attempts": 2}), task)
    assert not task_matches_dispatch(task.model_copy(update={"branch_name": name + "-other"}), task)
    changed = spec.model_copy(update={"branch_name": name + "-other"})
    with pytest.raises(StageIntegrityError):
        changed.validate_integrity()
    revised = product_spec(req, branch_name=name + "-other")
    with pytest.raises(StageContractMismatch):
        require_product_approval(revised, approved)


def test_legacy_wire_omits_absent_new_fields_even_without_exclude_none(tmp_path: Path) -> None:
    spec = product_spec(request(preparation(tmp_path)))
    assert "branch_name" not in spec.model_dump(mode="json")
    assert (
        "branch_name"
        not in ProductDraft(
            action="clarify", summary="Need scope", questions=("Which scope?",)
        ).model_dump()
    )
    old = make_plan(tmp_path / "project")
    assert "target_branch_name" not in old.model_dump(mode="json")
    assert "branch_name" not in old.capture.model_dump(mode="json")
    assert RecoveryPlan.model_validate(old.to_wire()).plan_sha256 == old.plan_sha256
    old.validate_integrity()


def test_new_product_output_cannot_use_legacy_missing_name(tmp_path: Path) -> None:
    payload = {
        "action": "ready",
        "summary": "Greeting",
        "goals": ["Greeting"],
        "requirements": [
            {
                "statement": "Greet",
                "rationale": "Requested",
                "acceptance": [{"description": "Greets", "verification": "Test"}],
            }
        ],
    }
    result = StructuredProductAgentAdapter(_StructuredClient(payload)).run(_request(tmp_path))
    assert result.product_spec is None and result.error is not None
    # Reading old approved derived documents is an explicit trusted composition, not model fallback.
    result = StructuredProductAgentAdapter(
        _StructuredClient(payload), trusted_legacy_projection=True
    ).run(_request(tmp_path))
    assert result.product_spec is not None and result.product_spec.branch_name is None


def test_recovery_name_is_digest_bound_and_cannot_change_original_kind(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "project")
    capture = old.capture.to_capture()
    capture = replace(capture, worktree=replace(capture.worktree, branch="ai/feature/trends"))
    saved = CapturedChanges.from_capture(capture)
    plan = RecoveryPlan.create(
        **{**old.to_wire(), "capture": saved, "target_branch_name": "ai/feature/trends-recovery"}
    )
    plan.validate_integrity()
    for name in (None, "ai/bugfix/trends-recovery", "ai/feature/trends"):
        with pytest.raises(ValidationError):
            RecoveryPlan.create(**{**plan.to_wire(), "target_branch_name": name})
    changed = plan.model_copy(update={"target_branch_name": "ai/feature/trends-storage-recovery"})
    with pytest.raises(RecoveryRejected):
        changed.validate_integrity()
    fresh = RecoveryPlan.create(**changed.to_wire())
    assert fresh.plan_sha256 != plan.plan_sha256
    assert fresh.new_task_id != plan.new_task_id


def test_all_embedded_schema_branch_fields_match_domain() -> None:
    models = {
        model.__name__: model
        for model in (Task, ProductSpec, ProductDraft, CapturedChanges, RecoveryPlan)
    }
    for path in (Path(__file__).parents[2] / "schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text())
        nodes = dict(schema.get("$defs", {}))
        root_name = {"task.schema.json": "Task", "product-spec.schema.json": "ProductSpec"}.get(
            path.name, schema.get("title")
        )
        if root_name in models and "properties" in schema:
            nodes[root_name] = schema
        for name, node in nodes.items():
            if name not in models:
                continue
            field = "target_branch_name" if name == "RecoveryPlan" else "branch_name"
            assert (
                node["properties"][field] == models[name].model_json_schema()["properties"][field]
            ), path
