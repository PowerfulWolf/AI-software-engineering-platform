"""Recovery successors use exact newly approved authority and frozen source budgets."""

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import ProjectPreparation, TaskStatus
from ai_software_engineer.domain.continuation import InterruptionContinuationPolicy
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.project_delivery import derive_delivery_task
from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy, TransientRetryPolicy
from ai_software_engineer.manager.baseline import ProjectSpecBaseline
from ai_software_engineer.recovery.current import NativeRecoveryFacts, NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.models import (
    RecoveryPlan,
    RecoveryRejected,
    RecoveryTargetAuthorization,
    digest,
)
from ai_software_engineer.recovery.native import NativeRecoverySource
from ai_software_engineer.recovery.service import RecoveryAuthorizationService
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_contracts import stage_chain
from tests.recovery.test_authorization import Captures, Human, approval, make_plan


@dataclass(frozen=True)
class PolicyFixture:
    plan: RecoveryPlan
    original: NativeRecoverySource
    target: ProjectPreparation
    scope: EngineeringScope


def policy_fixture(tmp_path: Path, *, legacy_budget: bool = False) -> PolicyFixture:
    prepared, request, product, approved, design, execution = stage_chain(tmp_path)
    prototype = make_plan(Path(prepared.repository_root), repository_id=prepared.repository_id)
    retry = (
        None
        if legacy_budget
        else DeliveryRetryPolicy(
            max_work_attempts=4,
            coder=TransientRetryPolicy(max_transient_failures=2),
            qa=TransientRetryPolicy(max_transient_failures=1),
            reviewer=TransientRetryPolicy(max_transient_failures=3),
        )
    )
    task = derive_delivery_task(
        prepared,
        request,
        product,
        approved,
        design,
        execution,
        task_id=prototype.source.task_id,
        repository=prepared.repository_root,
        base_ref=prototype.source.base_revision,
        max_attempts=3 if retry is None else retry.execution_limit,
        retry_policy=retry,
        created_at=request.created_at,
    ).model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 1})
    source = prototype.source.model_copy(
        update={
            "scope": prototype.source.scope.model_copy(update={"team_id": prepared.team_id}),
            "task_sha256": digest(task.to_wire()),
            "preparation_sha256": prepared.preparation_sha256,
            "product_spec_sha256": product.product_spec_sha256,
            "approval_sha256": approved.approval_sha256,
            "technical_design_sha256": design.technical_design_sha256,
            "execution_plan_sha256": execution.execution_plan_sha256,
        }
    )
    plan = RecoveryPlan.create(
        **{
            **prototype.to_wire(),
            "source": source,
            "target_preparation_sha256": prepared.preparation_sha256,
        }
    )
    original = NativeRecoverySource(
        source,
        plan.permissions,
        plan.denied_paths,
        prepared,
        product,
        approved,
        design,
        execution,
        request,
        task,
        source.base_revision,
    )
    scope = EngineeringScope(
        team_id=prepared.team_id,
        project_id=prepared.project_id,
        repository_id=prepared.repository_id,
        repository_root=prepared.repository_root,
    )
    return PolicyFixture(plan, original, prepared, scope)


def authorized_plan(fixture: PolicyFixture) -> RecoveryPlan:
    authority = RecoveryTargetAuthorization.issue(
        source=fixture.original.source,
        task=fixture.original.task,
        scope=fixture.scope,
        principal=LocalOperatorPrincipal.trusted_local(),
    )
    return RecoveryPlan.create(**{**fixture.plan.to_wire(), "target_authorization": authority})


def test_new_authority_binds_frozen_budget_and_changes_only_new_plan(tmp_path: Path) -> None:
    fixture = policy_fixture(tmp_path)
    before = fixture.plan.model_dump_json()
    plan = authorized_plan(fixture)
    authority = plan.target_authorization
    assert authority is not None
    assert authority.source_task_sha256 == digest(fixture.original.task.to_wire())
    assert authority.source_retry_policy == fixture.original.task.retry_policy
    assert authority.source_max_attempts == 10
    assert authority.engineering_policy == EngineeringPolicy.bounded_local(
        scope=fixture.scope, principal=LocalOperatorPrincipal.trusted_local()
    )
    assert authority.interruption_continuation_policy == (
        InterruptionContinuationPolicy.for_retry_budget(
            max_work_attempts=4, max_coder_transient_failures=2
        )
    )
    assert plan.plan_sha256 != fixture.plan.plan_sha256
    assert fixture.plan.model_dump_json() == before
    plan.validate_integrity()


def test_legacy_none_omission_preserves_nested_bytes_and_digest(tmp_path: Path) -> None:
    fixture = policy_fixture(tmp_path, legacy_budget=True)

    class Envelope(BaseModel):
        plan: RecoveryPlan

    before = fixture.plan.model_dump(mode="json")
    assert "target_authorization" not in before
    assert "target_authorization" not in Envelope(plan=fixture.plan).model_dump()["plan"]
    replay = RecoveryPlan.model_validate({**before, "target_authorization": None})
    assert replay.model_dump_json() == fixture.plan.model_dump_json()
    assert replay.plan_sha256 == fixture.plan.plan_sha256
    plan = authorized_plan(fixture)
    authority = plan.target_authorization
    assert authority is not None
    assert authority.interruption_continuation_policy is None
    assert "source_retry_policy" not in authority.model_dump()
    assert "interruption_continuation_policy" not in plan.model_dump()["target_authorization"]


@pytest.mark.parametrize(
    "change",
    [
        "issuer",
        "grants",
        "total",
        "task",
        "sha",
        "team",
        "repository",
        "root",
        "max_attempts",
        "continuation",
        "budget",
    ],
)
def test_target_authorization_rejects_changed_authority_or_source(
    tmp_path: Path, change: str
) -> None:
    fixture = policy_fixture(tmp_path)
    plan = authorized_plan(fixture)
    wire = plan.to_wire()
    authority = wire["target_authorization"]
    assert isinstance(authority, dict)
    policy = authority["engineering_policy"]
    assert isinstance(policy, dict)
    scope = policy["scope"]
    assert isinstance(scope, dict)
    if change == "issuer":
        policy["issued_by"] = {
            "kind": "trusted_local_operator",
            "operator_id": "operator:product",
            "duties": ["PRODUCT"],
        }
    elif change == "grants":
        grants = policy["grants"]
        assert isinstance(grants, list) and isinstance(grants[0], dict)
        grants[0]["max_admissions"] = 4
    elif change == "total":
        policy["max_total_admissions"] = 13
    elif change == "task":
        authority["source_task_id"] = "task_wrong"
    elif change == "sha":
        authority["source_task_sha256"] = "f" * 64
    elif change in ("team", "repository", "root"):
        scope[
            {"team": "team_id", "repository": "repository_id", "root": "repository_root"}[change]
        ] = "/other/repository" if change == "root" else "wrong_identity"
    elif change == "max_attempts":
        authority["source_max_attempts"] = 11
    elif change == "continuation":
        authority["interruption_continuation_policy"] = InterruptionContinuationPolicy().to_wire()
    else:
        retry = authority["source_retry_policy"]
        assert isinstance(retry, dict)
        retry["max_work_attempts"] = 5
    with pytest.raises(ValidationError):
        RecoveryPlan.model_validate(wire)


@pytest.mark.parametrize("change", ["project", "task_bytes", "retry", "legacy_budget"])
def test_current_binding_checks_full_project_and_frozen_source(tmp_path: Path, change: str) -> None:
    fixture = policy_fixture(tmp_path)
    authority = authorized_plan(fixture).target_authorization
    assert authority is not None
    task, scope = fixture.original.task, fixture.scope
    if change == "project":
        scope = scope.model_copy(update={"project_id": "project_other"})
    elif change == "task_bytes":
        task = task.model_copy(update={"description": "Changed"})
    elif change == "retry":
        task = task.model_copy(update={"retry_policy": DeliveryRetryPolicy(), "max_attempts": 18})
    else:
        task = task.model_copy(update={"retry_policy": None, "max_attempts": 3})
    with pytest.raises(RecoveryRejected):
        authority.validate_current(source=fixture.original.source, task=task, scope=scope)


@pytest.mark.parametrize("project_matches", [False, True])
def test_native_current_gate_uses_registered_project_before_reading_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_matches: bool
) -> None:
    fixture = policy_fixture(tmp_path)
    plan = authorized_plan(fixture)
    verifier = NativeRecoveryFactsVerifier(
        ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            team_id=fixture.target.team_id,
            model_routes=(
                ProviderRouteConfig(
                    provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        {},
    )
    monkeypatch.setattr(verifier._source, "inspect", lambda *args, **kwargs: fixture.original)
    project = SimpleNamespace(
        manifest=SimpleNamespace(
            project_id=fixture.scope.project_id if project_matches else "project_other"
        )
    )
    repository = SimpleNamespace(
        root=tmp_path / "sidecar",
        manifest=SimpleNamespace(
            repository_id=fixture.scope.repository_id, repository_root=fixture.scope.repository_root
        ),
    )
    registry = SimpleNamespace(locate_repository=lambda _: (project, repository))
    team = SimpleNamespace(
        manifest=SimpleNamespace(team_id=fixture.scope.team_id), project_registry=lambda: registry
    )
    monkeypatch.setattr(TeamWorkspace, "initialize", lambda *args, **kwargs: team)
    target_reads = 0

    class TargetReadReached(Exception):
        pass

    def read_target(*args: object) -> None:
        nonlocal target_reads
        target_reads += 1
        raise TargetReadReached

    monkeypatch.setattr("ai_software_engineer.recovery.current._preparation", read_target)
    expected = TargetReadReached if project_matches else RecoveryRejected
    with pytest.raises(expected):
        verifier._inspect(plan)
    assert target_reads == int(project_matches)


@pytest.mark.parametrize(
    "principal",
    [None, LocalOperatorPrincipal(operator_id="operator:product", duties=(OperatorDuty.PRODUCT,))],
)
def test_entry_without_engineering_principal_cannot_add_authority(
    tmp_path: Path, principal: LocalOperatorPrincipal | None
) -> None:
    fixture = policy_fixture(tmp_path)
    entry = object.__new__(NativeRecoveryEntry)
    entry.operator_principal = principal
    assert (
        entry._target_authorization(
            fixture.original, fixture.target, project_id=fixture.scope.project_id
        )
        is None
    )


def test_entry_uses_registered_scope_and_source_budget(tmp_path: Path) -> None:
    fixture = policy_fixture(tmp_path)
    entry = object.__new__(NativeRecoveryEntry)
    entry.operator_principal = LocalOperatorPrincipal.trusted_local()
    authority = entry._target_authorization(
        fixture.original, fixture.target, project_id=fixture.scope.project_id
    )
    assert authority == authorized_plan(fixture).target_authorization


@pytest.mark.parametrize("change", ["missing_retry", "continuation", "project"])
def test_legacy_budget_cannot_receive_new_continuation_or_wrong_scope(
    tmp_path: Path, change: str
) -> None:
    fixture = policy_fixture(tmp_path, legacy_budget=True)
    authority = authorized_plan(fixture).target_authorization
    assert authority is not None
    if change == "project":
        entry = object.__new__(NativeRecoveryEntry)
        entry.operator_principal = LocalOperatorPrincipal.trusted_local()
        # A new plan can bind this value; actual registered ownership must still
        # match in current-facts admission before authorization or execution.
        changed = entry._target_authorization(
            fixture.original, fixture.target, project_id="project_other"
        )
        assert changed is not None
        with pytest.raises(RecoveryRejected):
            changed.validate_current(
                source=fixture.original.source, task=fixture.original.task, scope=fixture.scope
            )
    else:
        wire = authority.to_wire()
        wire["interruption_continuation_policy"] = (
            InterruptionContinuationPolicy.for_retry_budget(
                max_work_attempts=3, max_coder_transient_failures=5
            ).to_wire()
            if change == "missing_retry"
            else InterruptionContinuationPolicy().to_wire()
        )
        with pytest.raises(ValidationError, match="frozen source budget"):
            RecoveryTargetAuthorization.model_validate(wire)


@pytest.mark.parametrize("with_authority", [False, True])
def test_authorized_builder_copies_only_exact_plan_policies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_authority: bool
) -> None:
    fixture = policy_fixture(tmp_path)
    plan = authorized_plan(fixture) if with_authority else fixture.plan
    facts = NativeRecoveryFacts(
        fixture.original,
        fixture.target,
        cast(RepositoryProfile, object()),
        cast(ProjectSpecBaseline, object()),
    )
    verifier = NativeRecoveryFactsVerifier(
        ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            team_id=fixture.target.team_id,
            model_routes=(
                ProviderRouteConfig(
                    provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        {},
    )
    monkeypatch.setattr(verifier, "_inspect", lambda _: facts)
    store = FileRecoveryStore.initialize(tmp_path / "recovery", scope=plan.source.scope)
    authorization = RecoveryAuthorizationService(
        store, facts=verifier, captures=Captures(), human=Human()
    )
    authorization.propose(plan)
    authorization.authorize(approval(plan))
    before = fixture.original.task.model_dump_json()
    draft = AuthorizedRecoveryTaskBuilder(authorization, verifier).build(plan.plan_sha256)
    assert draft.task.retry_policy == fixture.original.task.retry_policy
    assert draft.task.max_attempts == fixture.original.task.max_attempts
    assert fixture.original.task.model_dump_json() == before
    authority = plan.target_authorization
    assert draft.task.engineering_policy == (authority.engineering_policy if authority else None)
    assert draft.task.interruption_continuation_policy == (
        authority.interruption_continuation_policy if authority else None
    )


def test_new_authorization_matches_delivery_recovery_schema(tmp_path: Path) -> None:
    plan = authorized_plan(policy_fixture(tmp_path))
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    validator = Draft202012Validator(schema)
    validator.validate(plan.to_wire())


@pytest.mark.parametrize(
    "change", ["null", "v1", "missing_retry", "null_retry", "empty", "missing_version"]
)
def test_schema_rejects_continuation_without_exact_retry_version(
    tmp_path: Path, change: str
) -> None:
    plan = authorized_plan(policy_fixture(tmp_path))
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    wire = plan.to_wire()
    authority = wire["target_authorization"]
    assert isinstance(authority, dict)
    if change == "null":
        authority["interruption_continuation_policy"] = None
    elif change == "v1":
        authority["interruption_continuation_policy"] = InterruptionContinuationPolicy().to_wire()
    elif change == "missing_retry":
        del authority["source_retry_policy"]
    elif change == "empty":
        authority["interruption_continuation_policy"] = {}
    elif change == "missing_version":
        continuation = InterruptionContinuationPolicy().to_wire()
        del continuation["schema_version"]
        authority["interruption_continuation_policy"] = continuation
    else:
        authority["source_retry_policy"] = None
    with pytest.raises(ValidationError):
        RecoveryPlan.model_validate(wire)
    assert not Draft202012Validator(schema).is_valid(wire)
