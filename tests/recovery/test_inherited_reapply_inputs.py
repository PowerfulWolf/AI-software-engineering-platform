"""Complete historical reapply input survives a later partial-draft recovery."""

import hashlib
import json
import runpy
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from pymysql import OperationalError

from ai_software_engineer.agents import AgentRequest, AgentRunStatus, StoredContextResolver
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import ContextBudget, ContextBudgetExceeded, FileContextBuilder
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.git.capture import MAX_CAPTURE_BYTES
from ai_software_engineer.manager.production_delivery import DispatchDeliveryAgentAdapter
from ai_software_engineer.orchestration import ExecutionPlanAgentAdapter
from ai_software_engineer.recovery.admission import (
    RecoveryWorkspaceAdmissionRejected,
    reject_invalid_admission,
)
from ai_software_engineer.recovery.context import recovery_context_sources, validate_reapply_context
from ai_software_engineer.recovery.inherited_input import (
    InheritedInputRecords,
    reconstruct_inherited_reapply_inputs,
)
from ai_software_engineer.recovery.inherited_queue import (
    _original_claim,
    read_inherited_invocation_queue,
)
from ai_software_engineer.recovery.models import (
    InheritedReapplyInput,
    RecoveryPlan,
    RecoveryRejected,
    digest,
)
from ai_software_engineer.store import MySqlConnectionError
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
    DurableInvocationControl,
)
from tests.domain.factories import make_task
from tests.recovery.test_authorization import make_plan
from tests.recovery.test_preparation_inspection_scope import preparation_fixture, seed_fixture


def test_partial_new_draft_keeps_unadapted_original_patch_required(tmp_path: Path) -> None:
    old_patch = "diff --git a/remaining.py b/remaining.py\n+UNADAPTED_OLD_WORK = True\n"
    old_plan = make_plan(tmp_path / "project")
    # A strict seed contains only the work adapted so far. The original input
    # still includes work in another file which this draft has not recreated.
    wire = old_plan.to_wire()
    wire["inherited_reapply_inputs"] = [
        {
            "origin_plan_sha256": "d" * 64,
            "origin_task_id": "task_recovery_" + "d" * 32,
            "origin_context_manifest_id": "ctx_" + "e" * 64,
            "patch_uri": "recovery://" + "d" * 64 + "/patch/" + "f" * 64,
            "patch_sha256": hashlib.sha256(old_patch.encode()).hexdigest(),
            "patch_bytes": len(old_patch.encode()),
            "patch": old_patch,
        }
    ]
    successor = RecoveryPlan.create(**wire)
    sources = recovery_context_sources(successor)
    inherited = tuple(
        source for source in sources if "UNADAPTED_OLD_WORK" in (source.content or "")
    )
    assert len(inherited) == 1
    assert inherited[0].required and inherited[0].roles == (AgentRole.CODER,)
    assert inherited[0].content == old_patch
    assert successor.capture == old_plan.capture


def inherited_input(
    letter: str = "d", *, body: str = "complete unadapted work\n"
) -> InheritedReapplyInput:
    return InheritedReapplyInput(
        origin_plan_sha256=letter * 64,
        origin_task_id="task_recovery_" + letter * 32,
        origin_context_manifest_id="ctx_" + "e" * 64,
        patch_uri="recovery://" + letter * 64 + "/patch/" + "f" * 64,
        patch_sha256=hashlib.sha256(body.encode()).hexdigest(),
        patch_bytes=len(body.encode()),
        patch=body,
    )


@pytest.mark.parametrize("mode", [None, "coder_reapply"])
def test_inherited_context_is_complete_role_scoped_and_budgeted(
    tmp_path: Path, mode: str | None
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    old = make_plan(project)
    inherited = inherited_input()
    plan = RecoveryPlan.create(
        **{**old.to_wire(), "input_mode": mode, "inherited_reapply_inputs": (inherited,)}
    )
    # A Context Task only needs its real frozen identity here; independent native
    # entry tests establish the trusted store/approval/dispatch source of inputs.
    task = make_task().model_copy(update={"repository": str(project)})
    sources = recovery_context_sources(plan)
    builder = FileContextBuilder(project, plan.permissions, sources=sources)
    context = builder.build(task, AgentRole.CODER, attempt=1)
    validate_reapply_context(plan, context)
    name = "source:recovery.inherited_patch." + inherited.origin_plan_sha256
    section = next(s for s in context.sections if s.name == name)
    for update in (
        {"content": "lost old work"},
        {"uri": "recovery://wrong"},
        {"truncated": True},
        {"sha256": "0" * 64},
    ):
        altered = context.model_copy(
            update={
                "sections": tuple(
                    s.model_copy(update=update) if s.name == name else s for s in context.sections
                )
            }
        )
        with pytest.raises(RecoveryRejected):
            validate_reapply_context(plan, altered)
    missing = context.model_copy(
        update={"sections": tuple(s for s in context.sections if s.name != name)}
    )
    with pytest.raises(RecoveryRejected):
        validate_reapply_context(plan, missing)
    extra = context.model_copy(
        update={
            "sections": (*context.sections, section.model_copy(update={"name": name[:-1] + "0"}))
        }
    )
    with pytest.raises(RecoveryRejected):
        validate_reapply_context(plan, extra)
    for role in (AgentRole.QA, AgentRole.REVIEWER):
        assert all(
            "recovery.inherited_patch." not in s.name
            for s in builder.build(task, role, attempt=1).sections
        )
    budget = ContextBudget(
        max_input_tokens=context.budget.used_input_tokens - section.tokens, reserved_output_tokens=1
    )
    with pytest.raises(ContextBudgetExceeded):
        FileContextBuilder(project, plan.permissions, sources=sources, budget=budget).build(
            task, AgentRole.CODER, attempt=1
        )


def test_none_wire_and_schema_shape_keep_historical_plan_identity(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "project")
    assert "inherited_reapply_inputs" not in old.to_wire()
    assert "inherited_reapply_inputs" not in old.model_dump(mode="json")
    assert old.recompute_sha256() == digest(
        {k: v for k, v in old.to_wire().items() if k != "plan_sha256"}
    )
    assert RecoveryPlan.model_validate(old.to_wire()).to_wire() == old.to_wire()
    new = RecoveryPlan.create(**{**old.to_wire(), "inherited_reapply_inputs": (inherited_input(),)})
    assert new.new_task_id != old.new_task_id
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    generated = RecoveryPlan.model_json_schema()
    assert schema["$defs"]["InheritedReapplyInput"] == generated["$defs"]["InheritedReapplyInput"]
    assert (
        schema["$defs"]["RecoveryPlan"]["properties"]["inherited_reapply_inputs"]
        == generated["properties"]["inherited_reapply_inputs"]
    )
    Draft202012Validator(schema).validate(new.to_wire())
    with pytest.raises(RecoveryRejected):
        old.model_copy(
            update={"inherited_reapply_inputs": (inherited_input(),)}
        ).validate_integrity()


def test_inherited_schema_sync_is_narrow_and_reproducible() -> None:
    root = Path(__file__).parents[2]
    schema = json.loads((root / "schemas/delivery-recovery.schema.json").read_text())
    sync = runpy.run_path(str(root / "scripts/sync-inherited-reapply-schema.py"))["synchronize"]
    missing = deepcopy(schema)
    del missing["$defs"]["InheritedReapplyInput"]
    del missing["$defs"]["RecoveryPlan"]["properties"]["inherited_reapply_inputs"]
    assert sync(missing, RecoveryPlan.model_json_schema()) == schema
    assert sync(schema, RecoveryPlan.model_json_schema()) == schema


@pytest.mark.parametrize("change", ["origin", "uri", "body", "bytes", "sha", "binary", "nul"])
def test_inherited_patch_rejects_corrupt_identity_and_body(change: str) -> None:
    wire = inherited_input().to_wire()
    if change == "origin":
        wire["origin_task_id"] = "task_other"
    elif change == "uri":
        wire["patch_uri"] = "recovery://" + "a" * 64 + "/patch/" + "f" * 64
    elif change == "body":
        wire["patch"] = "lost original body"
    elif change == "bytes":
        wire["patch_bytes"] = 1
    elif change == "sha":
        wire["patch_sha256"] = "0" * 64
    else:
        body = "GIT binary patch" if change == "binary" else "bad\0body"
        wire.update(
            patch=body,
            patch_bytes=len(body.encode()),
            patch_sha256=hashlib.sha256(body.encode()).hexdigest(),
        )
    with pytest.raises(ValidationError):
        InheritedReapplyInput.model_validate(wire)


def test_inherited_patch_set_refuses_duplicates_count_and_aggregate_bytes(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "project")
    one = inherited_input()
    for values in (
        (one, one),
        tuple(inherited_input(c) for c in "012345678"),
        (
            inherited_input(body="x" * (MAX_CAPTURE_BYTES // 2 + 1)),
            inherited_input("c", body="y" * (MAX_CAPTURE_BYTES // 2 + 1)),
        ),
    ):
        with pytest.raises(ValidationError):
            RecoveryPlan.create(**{**old.to_wire(), "inherited_reapply_inputs": values})


def test_no_ancestry_is_distinct_from_missing_recovery_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    original = fixture.builder._facts.inspect(fixture.plan).original.task
    source = fixture.plan.source.model_copy(update={"task_sha256": digest(original.to_wire())})
    records = cast(InheritedInputRecords, object())
    assert reconstruct_inherited_reapply_inputs(records, source, original) is None
    missing = original.model_copy(update={"id": "task_recovery_" + "f" * 32})
    source = source.model_copy(
        update={"task_id": missing.id, "task_sha256": digest(missing.to_wire())}
    )
    with pytest.raises(RecoveryRejected, match="no approved origin"):
        reconstruct_inherited_reapply_inputs(records, source, missing)


@pytest.mark.parametrize("failure", ["missing_input", "malformed_claim", "connection", "query"])
def test_final_context_rejection_is_a_definitive_failed_result_without_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    seed, _, request = seed_fixture(fixture)
    calls: list[AgentRequest] = []

    class UnavailableCursor:
        def execute(self, sql: str, *arguments: object) -> None:
            if sql.startswith("SELECT"):
                raise OperationalError("private-dsn-and-sql-must-never-appear")

    @contextmanager
    def cursor(*arguments: object) -> Iterator[UnavailableCursor]:
        yield UnavailableCursor()

    def unavailable_connection(*arguments: object) -> SimpleNamespace:
        if failure == "connection":
            raise MySqlConnectionError("private-dsn-and-sql-must-never-appear")
        return SimpleNamespace(cursor=cursor, rollback=lambda: None, close=lambda: None)

    if failure in {"connection", "query"}:
        monkeypatch.setattr(
            "ai_software_engineer.recovery.inherited_queue.open_mysql_connection",
            unavailable_connection,
        )

    @reject_invalid_admission
    def refuse(current: AgentRequest) -> None:
        calls.append(current)
        if failure == "malformed_claim":
            _original_claim({}, {"payload_json": '{"detail":{}}'})
        if failure in {"connection", "query"}:
            assert seed.guard is not None and seed.guard.lease is not None
            start = seed.invocations.get(
                "invocation-starts", seed.guard.lease.claim.work_item.id, DeliveryInvocationStart
            )
            read_inherited_invocation_queue(
                "never-opened",
                start,
                seed.dispatch,
                seed.dispatch.task,
                fixture.plan.source.scope,
                "project_example",
            )
        raise RecoveryWorkspaceAdmissionRejected("immutable old input changed")

    adapter = DispatchDeliveryAgentAdapter(
        dispatch=seed.dispatch,
        definitions={},
        plan_adapter=cast(ExecutionPlanAgentAdapter, object()),
        config=ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            model_routes=(
                ProviderRouteConfig(
                    provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        repository_root=tmp_path / "project",
        repository_workspace_root=tmp_path / "sidecar",
        context_resolver=cast(StoredContextResolver, None),
        recovery_input_validator=refuse,
    )
    with pytest.raises(RecoveryWorkspaceAdmissionRejected):
        adapter.prepare_input(request)
    result = adapter.run(request)
    assert calls == [request, request]
    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None and result.error.code.value == "WORK_INTERRUPTED"
    assert "private-dsn-and-sql" not in result.error.message
    assert result.artifact is None
    assert not adapter._adapters, "no provider adapter constructed after failed final gate"
    assert seed.guard is not None and seed.guard.lease is not None
    control = DurableInvocationControl(seed.invocations, seed.guard)
    control.completed(request, result)
    outcome = seed.invocations.get(
        "invocation-outcomes", seed.guard.lease.claim.work_item.id, DeliveryInvocationOutcome
    )
    outcome.validate_integrity()
    assert outcome.start.request == request and outcome.result == result
