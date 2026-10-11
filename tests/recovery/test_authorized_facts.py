"""Synchronous authorized facts remove derivation work, never a freshness fence."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import MethodType
from typing import cast

import pytest

import ai_software_engineer.recovery.task as task_module
from ai_software_engineer.domain.project_delivery import derive_delivery_task
from ai_software_engineer.manager.baseline import ProjectSpecBaseline
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import (
    RecoveryAuthorization,
    RecoveryPlan,
    RecoveryRejected,
)
from ai_software_engineer.recovery.service import RecoveryAuthorizationService
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
from ai_software_engineer.repository_profile import RepositoryProfile
from tests.recovery.test_authorization import Captures, Human
from tests.recovery.test_preparation_inspection_scope import (
    OfflineAuthority,
    allocate,
    preparation_fixture,
)


def after_call[**P, R](invoke: Callable[P, R], mutate: Callable[[], None]) -> Callable[P, R]:
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        result = invoke(*args, **kwargs)
        mutate()
        return result

    return wrapped


def test_native_builder_removes_only_the_middle_full_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    draft = fixture.builder.build(fixture.plan.plan_sha256)
    assert draft.task.id == fixture.plan.new_task_id
    assert fixture.reads == {"facts": 8, "capture": 2}
    assert fixture.getters == {"plan": 6, "authorization": 2}


def test_typed_gate_returns_only_fresh_last_observation_and_keeps_legacy_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    service = f.builder._authorization
    current = service.inspect_current_authorization(f.plan.plan_sha256)
    assert current.plan == f.plan
    assert current.facts.original.source == f.plan.source
    assert f.reads == {"facts": 4, "capture": 1}
    assert service.require_current_authorization(f.plan.plan_sha256) == current.plan
    assert f.reads == {"facts": 8, "capture": 2}
    assert f.store.get_authorization(f.plan.plan_sha256).decision.approved
    assert not tuple(f.store._root.glob("task-*.json"))


def test_native_draft_wire_matches_existing_deterministic_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    # Drive the compatibility path with an equivalent independent native port;
    # it retains the old require -> inspect -> require call graph and wire output.
    original = f.builder._facts
    independent = NativeRecoveryFactsVerifier(original._config, original._environment)
    monkeypatch.setattr(independent, "_inspect", original._inspect)
    old_path = AuthorizedRecoveryTaskBuilder(f.builder._authorization, independent)
    expected = old_path.build(f.plan.plan_sha256)
    assert f.reads == {"facts": 10, "capture": 2}
    f.reads.clear()
    actual = f.builder.build(f.plan.plan_sha256)
    assert f.reads == {"facts": 8, "capture": 2}
    assert actual.task.to_wire() == expected.task.to_wire()
    assert actual.rebound_request.to_wire() == expected.rebound_request.to_wire()
    assert actual.facts == expected.facts


@pytest.mark.parametrize("field", ["original", "target", "profile", "baseline"])
def test_final_complete_facts_reject_drift_during_pure_derivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    sealed = f.sealing.seal(f.plan.plan_sha256)
    receipt = f.store.get_authorization(f.plan.plan_sha256)
    verifier = f.builder._facts
    original_inspect = verifier._inspect
    original_derive = derive_delivery_task

    def mutate() -> None:
        facts = original_inspect(f.plan)
        if field == "original":
            newer = replace(facts, original=replace(facts.original, worktree_revision="d" * 40))
        elif field == "target":
            newer = replace(
                facts,
                target=facts.target.model_copy(update={"repository_root": str(tmp_path / "other")}),
            )
        elif field == "profile":
            newer = replace(facts, profile=cast(RepositoryProfile, object()))
        else:
            newer = replace(facts, baseline=cast(ProjectSpecBaseline, object()))
        monkeypatch.setattr(verifier, "_inspect", lambda _: newer)

    monkeypatch.setattr(task_module, "derive_delivery_task", after_call(original_derive, mutate))
    with pytest.raises(RecoveryRejected, match="facts changed while building Task"):
        f.sealing.seal(f.plan.plan_sha256)
    assert f.store.get_task_record(f.plan.plan_sha256) == sealed
    assert f.store.get_authorization(f.plan.plan_sha256) == receipt


@pytest.mark.parametrize("drift", ["plan", "receipt", "directory", "body"])
def test_final_gate_rereads_authority_plan_directory_and_live_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    sealed = f.sealing.seal(f.plan.plan_sha256)
    original_derive = derive_delivery_task
    state_after_mutation: dict[Path, bytes] = {}

    def mutate() -> None:
        root = f.store._root
        if drift == "directory":
            root.rename(tmp_path / "previous-recovery")
            root.mkdir()
        elif drift == "body":
            f.body.write_text(f.body.read_text() + "CHANGED = 1\n")
        else:
            prefix = "plan-" if drift == "plan" else "authorization-"
            path = root / f"{prefix}{f.plan.plan_sha256}.json"
            payload = json.loads(path.read_text())
            payload["plan_sha256" if drift == "plan" else "authorization_sha256"] = "0" * 64
            path.write_text(json.dumps(payload))
        state_after_mutation.update({path: path.read_bytes() for path in root.glob("*.json")})

    monkeypatch.setattr(task_module, "derive_delivery_task", after_call(original_derive, mutate))
    with pytest.raises(RecoveryRejected):
        f.sealing.seal(f.plan.plan_sha256)
    assert {
        path: path.read_bytes() for path in f.store._root.glob("*.json")
    } == state_after_mutation
    if drift == "body":
        assert f.store.get_task_record(f.plan.plan_sha256) == sealed


def test_custom_stronger_validate_keeps_complete_compatibility_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    native = f.builder._facts

    class StrongerVerifier(NativeRecoveryFactsVerifier):
        reject = False
        validate_calls = 0

        def validate(self, plan: RecoveryPlan) -> None:
            self.validate_calls += 1
            super().validate(plan)
            if self.reject:
                raise RecoveryRejected("stronger custom validation rejected")

    stronger = StrongerVerifier(native._config, native._environment)
    monkeypatch.setattr(stronger, "_inspect", native._inspect)
    service = RecoveryAuthorizationService(
        f.store, facts=stronger, captures=Captures(), human=Human()
    )
    builder = AuthorizedRecoveryTaskBuilder(service, stronger)
    assert builder.build(f.plan.plan_sha256).task.id == f.plan.new_task_id
    assert stronger.validate_calls == 4 and f.reads["facts"] == 10
    with pytest.raises(RecoveryRejected, match="cannot return verified native facts"):
        service.inspect_current_authorization(f.plan.plan_sha256)
    stronger.reject = True
    with pytest.raises(RecoveryRejected, match="stronger custom validation rejected"):
        builder.build(f.plan.plan_sha256)


def test_instance_stronger_validate_preserves_original_calls_and_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    native = f.builder._facts
    original = native.validate
    calls = 0
    reject = False

    def stronger(_: NativeRecoveryFactsVerifier, plan: RecoveryPlan) -> None:
        nonlocal calls
        calls += 1
        original(plan)
        if reject:
            raise RecoveryRejected("instance validation rejected")

    monkeypatch.setattr(native, "validate", MethodType(stronger, native))
    f.builder.build(f.plan.plan_sha256)
    assert calls == 4 and f.reads == {"facts": 10, "capture": 2}
    calls = 0
    f.reads.clear()

    def mutate() -> None:
        nonlocal reject
        reject = True

    monkeypatch.setattr(
        task_module, "derive_delivery_task", after_call(derive_delivery_task, mutate)
    )
    with pytest.raises(RecoveryRejected, match="instance validation rejected"):
        f.builder.build(f.plan.plan_sha256)
    assert calls == 3 and f.reads == {"facts": 8, "capture": 1}


@pytest.mark.parametrize(
    "extension",
    ["instance-public", "instance-protected", "subclass-public", "class-public", "class-protected"],
)
def test_service_extension_keeps_original_authorization_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extension: str
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    service = f.builder._authorization
    require_authorization = RecoveryAuthorizationService.require_current_authorization
    require_current = RecoveryAuthorizationService._require_current
    calls = 0

    def stronger_authorization(owner: RecoveryAuthorizationService, sha: str) -> RecoveryPlan:
        nonlocal calls
        calls += 1
        require_authorization(owner, sha)
        raise RecoveryRejected("stronger service authorization rejected")

    def stronger_current(owner: RecoveryAuthorizationService, plan: RecoveryPlan) -> None:
        nonlocal calls
        calls += 1
        require_current(owner, plan)
        raise RecoveryRejected("stronger service authorization rejected")

    if extension == "instance-public":
        monkeypatch.setattr(
            service, "require_current_authorization", MethodType(stronger_authorization, service)
        )
    elif extension == "instance-protected":
        monkeypatch.setattr(service, "_require_current", MethodType(stronger_current, service))
    elif extension == "subclass-public":

        class StrongerService(RecoveryAuthorizationService):
            def require_current_authorization(self, plan_sha256: str) -> RecoveryPlan:
                return stronger_authorization(self, plan_sha256)

        service = StrongerService(
            f.store, facts=f.builder._facts, captures=service._captures, human=service._human
        )
    elif extension == "class-public":
        monkeypatch.setattr(
            RecoveryAuthorizationService, "require_current_authorization", stronger_authorization
        )
    else:
        assert extension == "class-protected"
        monkeypatch.setattr(RecoveryAuthorizationService, "_require_current", stronger_current)

    builder = AuthorizedRecoveryTaskBuilder(service, f.builder._facts)
    before = {path.name: path.read_bytes() for path in f.store._root.glob("*.json")}
    with pytest.raises(RecoveryRejected, match="stronger service authorization rejected"):
        builder.build(f.plan.plan_sha256)
    assert calls == 1
    with pytest.raises(RecoveryRejected, match="stronger service authorization rejected"):
        service.require_current_authorization(f.plan.plan_sha256)
    assert calls == 2
    assert {path.name: path.read_bytes() for path in f.store._root.glob("*.json")} == before


def test_class_stronger_native_validate_keeps_original_authorization_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    original = NativeRecoveryFactsVerifier.validate
    calls = 0

    def stronger(owner: NativeRecoveryFactsVerifier, plan: RecoveryPlan) -> None:
        nonlocal calls
        calls += 1
        original(owner, plan)
        raise RecoveryRejected("stronger class native validation rejected")

    monkeypatch.setattr(NativeRecoveryFactsVerifier, "validate", stronger)
    with pytest.raises(RecoveryRejected, match="stronger class native validation rejected"):
        f.builder.build(f.plan.plan_sha256)
    assert calls == 1
    with pytest.raises(RecoveryRejected, match="stronger class native validation rejected"):
        f.builder._authorization.require_current_authorization(f.plan.plan_sha256)
    assert calls == 2


def test_capture_mutation_is_rejected_by_the_same_gate_facts_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    sealed = f.sealing.seal(f.plan.plan_sha256)
    captures = f.builder._authorization._captures
    original = captures.verify_capture
    f.reads.clear()

    def mutate() -> None:
        f.body.write_text(f.body.read_text() + "CHANGED = 1\n")

    monkeypatch.setattr(captures, "verify_capture", after_call(original, mutate))
    with pytest.raises(RecoveryRejected):
        f.builder._authorization.inspect_current_authorization(f.plan.plan_sha256)
    assert f.reads == {"facts": 3, "capture": 1}
    assert f.store.get_task_record(f.plan.plan_sha256) == sealed


@pytest.mark.parametrize("decision", ["missing", "rejected", "corrupt"])
def test_typed_gate_cannot_supply_authority_or_task_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    store = FileRecoveryStore.initialize(tmp_path / "unapproved", scope=f.plan.source.scope)
    store.put_plan(f.plan)
    approved = f.store.get_authorization(f.plan.plan_sha256)
    if decision == "rejected":
        store.put_authorization(
            RecoveryAuthorization.create(
                approved.command, approved.decision.model_copy(update={"approved": False})
            )
        )
    elif decision == "corrupt":
        store.put_authorization(approved)
        path = store._root / f"authorization-{f.plan.plan_sha256}.json"
        payload = json.loads(path.read_text())
        payload["authorization_sha256"] = "0" * 64
        path.write_text(json.dumps(payload))
    service = RecoveryAuthorizationService(
        store, facts=f.builder._facts, captures=Captures(), human=Human()
    )
    builder = AuthorizedRecoveryTaskBuilder(service, f.builder._facts)
    before = {path.name: path.read_bytes() for path in store._root.glob("*.json")}
    with pytest.raises(RecoveryRejected):
        builder.build(f.plan.plan_sha256)
    assert {path.name: path.read_bytes() for path in store._root.glob("*.json")} == before
    assert not f.reads
    with pytest.raises(RecoveryRecordMissing):
        store.get_task_record(f.plan.plan_sha256)


@pytest.mark.parametrize("drift", [False, True])
def test_offline_authority_keeps_both_fences_and_all_builder_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: bool
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    authority = OfflineAuthority(f)
    authority.drift = drift
    if drift:
        with pytest.raises(RecoveryRejected):
            allocate(f, authority)
        assert authority.record is None
    else:
        record, _ = allocate(f, authority)
        assert authority.record == record
        assert f.reads["facts"] == 32 and f.reads["capture"] == 8
        assert f.getters == {"plan": 33, "authorization": 14}
    assert f.reads["fence_before"] == f.reads["fence_after"] == 1
