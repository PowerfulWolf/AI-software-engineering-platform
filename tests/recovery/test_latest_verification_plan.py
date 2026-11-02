"""Candidate verification plan lookup must bound expensive historical checks."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.recovery import verification_entry as entry_module
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.verification_native import NativeCandidateSourceReader
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationInputs,
    CandidateVerificationPlan,
)
from tests.orchestration.test_runner import _definitions


def _plan(
    scope: RecoveryScope,
    *,
    candidate: str,
    execution_task_id: str,
    created_at: datetime,
) -> CandidateVerificationPlan:
    inputs = CandidateVerificationInputs(
        task_id="task_delivery",
        task_revision=1,
        task_sha256="a" * 64,
        plan_id="art_plan",
        plan_sha256="b" * 64,
        implementation_id="art_implementation",
        implementation_sha256="c" * 64,
        candidate_revision=candidate,
    )
    return CandidateVerificationPlan.create(
        scope=scope,
        inputs=inputs,
        execution_task_id=execution_task_id,
        native_checkpoint_sha256="1" * 64,
        dispatch_sha256="2" * 64,
        approved_stage_chain_sha256="3" * 64,
        current_policy_sha256="4" * 64,
        definitions=tuple(_definitions().values()),
        created_at=created_at,
    )


def test_latest_project_filters_old_candidate_before_native_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = RecoveryScope(
        team_id="team_test",
        repository_id="repository_test",
        delivery_id="delivery_test",
        repository_root=str(tmp_path / "project"),
    )
    current_candidate = "a" * 40
    old_candidate = "b" * 40
    now = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
    old_plan = _plan(
        scope,
        candidate=old_candidate,
        execution_task_id="task_verify_old",
        created_at=now,
    )
    current_plan = _plan(
        scope,
        candidate=current_candidate,
        execution_task_id="task_verify_current",
        created_at=now + timedelta(minutes=1),
    )
    root = tmp_path / "verification"
    root.mkdir()
    paths = {
        old_plan.plan_sha256: root / f"verification-plan-{old_plan.plan_sha256}.json",
        current_plan.plan_sha256: root / f"verification-plan-{current_plan.plan_sha256}.json",
    }
    for path in paths.values():
        path.write_text("{}")

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def get_verification_plan(self, plan_sha256: str) -> CandidateVerificationPlan:
            return {
                old_plan.plan_sha256: old_plan,
                current_plan.plan_sha256: current_plan,
            }[plan_sha256]

    source = SimpleNamespace(
        scope=scope,
        inputs=SimpleNamespace(candidate_revision=current_candidate),
    )
    backend = Mock(_delivery_route_adapters=Mock())
    backend.prepare.return_value.preparation = SimpleNamespace(
        repository_id=scope.repository_id,
        repository_root=scope.repository_root,
    )
    entry = entry_module.CandidateVerificationEntry(
        ProductionConfig.default().model_copy(
            update={
                "platform_root": str(tmp_path / "platform"),
                "team_id": scope.team_id,
            }
        ),
        {},
        backend,
    )
    validated: list[str] = []

    monkeypatch.setattr(entry_module, "FileRecoveryStore", Store)
    monkeypatch.setattr(entry_module, "verification_store_root", lambda _source: root)
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)
    monkeypatch.setattr(
        entry_module.NativeVerificationFacts,
        "validate",
        lambda _self, plan: validated.append(plan.execution_task_id),
    )

    result = entry.latest_project(
        repository_root=scope.repository_root,
        delivery_id=scope.delivery_id,
    )

    assert result is not None
    _store, selected, selected_path = result
    assert selected == current_plan
    assert selected_path == paths[current_plan.plan_sha256]
    assert validated == [current_plan.execution_task_id]


def test_latest_project_does_not_resurface_older_plan_when_newest_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = RecoveryScope(
        team_id="team_test",
        repository_id="repository_test",
        delivery_id="delivery_test",
        repository_root=str(tmp_path / "project"),
    )
    now = datetime(2026, 11, 2, 2, 0, tzinfo=UTC)
    older = _plan(scope, candidate="a" * 40, execution_task_id="task_verify_older", created_at=now)
    newest = _plan(
        scope,
        candidate="a" * 40,
        execution_task_id="task_verify_newest",
        created_at=now + timedelta(minutes=1),
    )
    root = tmp_path / "verification"
    root.mkdir()
    for plan in (older, newest):
        (root / f"verification-plan-{plan.plan_sha256}.json").write_text("{}")

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def get_verification_plan(self, plan_sha256: str) -> CandidateVerificationPlan:
            return {older.plan_sha256: older, newest.plan_sha256: newest}[plan_sha256]

    backend = Mock(_delivery_route_adapters=Mock())
    backend.prepare.return_value.preparation = SimpleNamespace(
        repository_id=scope.repository_id,
        repository_root=scope.repository_root,
    )
    entry = entry_module.CandidateVerificationEntry(
        ProductionConfig.default().model_copy(
            update={"platform_root": str(tmp_path / "platform"), "team_id": scope.team_id}
        ),
        {},
        backend,
    )
    source = SimpleNamespace(scope=scope, inputs=SimpleNamespace(candidate_revision="a" * 40))
    checked: list[str] = []

    def validate(_self: object, plan: CandidateVerificationPlan) -> None:
        checked.append(plan.execution_task_id)
        if plan == newest:
            raise RecoveryRejected("verification executor capability changed; repropose")

    monkeypatch.setattr(entry_module, "FileRecoveryStore", Store)
    monkeypatch.setattr(entry_module, "verification_store_root", lambda _source: root)
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)
    monkeypatch.setattr(entry_module.NativeVerificationFacts, "validate", validate)

    assert (
        entry.latest_project(
            repository_root=scope.repository_root,
            delivery_id=scope.delivery_id,
        )
        is None
    )
    assert checked == [newest.execution_task_id]
