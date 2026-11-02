"""A never-invoked route claim has no failed Run or failed Context."""

import json
from copy import deepcopy
from pathlib import Path
from runpy import run_path
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.route_transition_source import (
    RouteTransitionRecoverySourceReader,
    require_route_transition_capture,
)
from tests.recovery.test_authorization import make_plan


def _route_plan(root: Path) -> RecoveryPlan:
    ordinary = make_plan(root)
    wire = ordinary.to_wire()
    wire.pop("plan_sha256")
    source = wire["source"]
    source["historical_progress_context_id"] = source.pop("failed_context_id")
    source["historical_progress_run_id"] = source.pop("failed_run_id")
    source["route_transition_settlement_sha256"] = "d" * 64
    source["execution_baseline_sha256"] = "e" * 64
    source["execution_base_revision"] = ordinary.source.base_revision
    wire["input_mode"] = "coder_reapply"
    return RecoveryPlan.create(**wire)


@pytest.mark.parametrize("generated", [False, True])
def test_route_transition_source_is_exclusive_and_requires_reapply(
    tmp_path: Path, generated: bool
) -> None:
    root = Path(__file__).resolve().parents[2]
    schema = (
        RecoveryPlan.model_json_schema()
        if generated
        else json.loads((root / "schemas/delivery-recovery.schema.json").read_text())
    )
    validator = Draft202012Validator(schema)
    route = _route_plan(tmp_path / "route")
    validator.validate(route.to_wire())
    assert route.source.failed_run_id is None
    assert route.source.failed_context_id is None
    assert route.source.historical_progress_context_id is not None
    assert route.source.historical_progress_run_id is not None
    for field, value in (
        ("failed_run_id", "run_invented"),
        ("failed_context_id", route.source.historical_progress_context_id),
        ("historical_progress_context_id", None),
        ("historical_progress_run_id", None),
        ("context_capacity_receipt_sha256", "c" * 64),
        ("stopped_unknown_settlement_sha256", "c" * 64),
    ):
        changed = deepcopy(route.to_wire())
        changed["source"][field] = value
        assert not validator.is_valid(changed), (generated, field)
        with pytest.raises(ValidationError):
            RecoveryPlan.model_validate(changed)
    changed = deepcopy(route.to_wire())
    changed["input_mode"] = None
    assert not validator.is_valid(changed)
    with pytest.raises(ValidationError):
        RecoveryPlan.model_validate(changed)


def test_capacity_schema_sync_preserves_route_guard_idempotently() -> None:
    root = Path(__file__).resolve().parents[2]
    synchronize = run_path(str(root / "scripts/sync-capacity-recovery-schema.py"))["synchronize"]
    current = json.loads((root / "schemas/delivery-recovery.schema.json").read_text())
    assert synchronize(current, RecoveryPlan.model_json_schema()) == current


def test_route_source_uses_exact_reader_and_retained_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _route_plan(tmp_path / "route")
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    verifier = NativeRecoveryFactsVerifier(config, {})
    original = Mock(
        source=plan.source,
        denied_paths=plan.denied_paths,
        route_transition_capture=plan.capture,
    )
    exact = Mock(return_value=original)
    monkeypatch.setattr(RouteTransitionRecoverySourceReader, "inspect", exact)
    monkeypatch.setattr(
        verifier._source,
        "inspect",
        Mock(side_effect=AssertionError("route transition used failed-Run reader")),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.inherited_input.read_inherited_reapply_inputs",
        Mock(return_value=None),
    )
    assert verifier._read_source(plan) is original
    exact.assert_called_once_with(plan.source.scope, "d" * 64)
    require_route_transition_capture(original, plan.capture, plan.capture)
    with pytest.raises(RecoveryRejected):
        require_route_transition_capture(
            original,
            plan.capture,
            plan.capture.model_copy(update={"capture_sha256": "0" * 64}),
        )
    assert not Path(config.platform_root).exists()


def test_route_reader_missing_evidence_is_read_only(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    scope = _route_plan(tmp_path / "route").source.scope
    reader = RouteTransitionRecoverySourceReader(config, {})
    with pytest.raises(RecoveryRejected):
        reader.discover(scope)
    with pytest.raises(RecoveryRejected):
        reader.inspect(scope, "d" * 64)
    assert not Path(config.platform_root).exists()
