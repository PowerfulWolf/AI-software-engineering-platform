"""Production reads retain current facts while assembling only selected complete bodies."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import ProductSpec, ProjectRequest, ProjectRequestStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import EngineeringDispositionRecord
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryIntake,
)
from ai_software_engineer.manager.production_agents import ProductDraft
from ai_software_engineer.multi_directory.models import (
    DialogueMessage,
    JointCheckpoint,
    JointProductSpec,
    digest,
)
from ai_software_engineer.multi_directory.retirement import RequirementRetirementStore
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.product.models import (
    ProductDiscoveryCheckpoint,
    ProductDiscoveryStatus,
    ProjectRequestRevision,
)
from ai_software_engineer.product.store import FileProductRecordStore
from ai_software_engineer.projection.models import ProjectionEventKind, TimelineEntry
from ai_software_engineer.read_record_scope import recovery_record_read_scope
from ai_software_engineer.recovery.models import digest as record_digest
from ai_software_engineer.redaction import source_inspection_scope
from ai_software_engineer.team_view.models import (
    DocumentView,
    RoleQueueView,
    TaskView,
    TeamReadError,
)
from ai_software_engineer.team_view.read_models import (
    RequestDetail,
    TaskDetail,
    TeamDetail,
    TeamDetailNotFound,
    TeamDetailQuery,
    TeamDetailSource,
    TeamDetailStale,
    TeamSummary,
)
from ai_software_engineer.team_view.reader import (
    ProductionTeamReader,
    _DetailJournalReads,
    _Native,
    _TaskReadSnapshot,
)
from tests.manager.test_production_backend import _ScriptedStructuredClient
from tests.product.test_store import _spec
from tests.team_view.test_baseline_snapshot import _fixture, _read_snapshot_fixture
from tests.team_view.test_continuation_history import _start
from tests.team_view.test_live import _bytes, _historical_child_fixture


def _native_product_fixture(
    tmp_path: Path,
) -> tuple[ProductionTeamReader, ProjectDeliveryCheckpoint, ProductSpec, Path]:
    config, _, parent, delivery_store = _historical_child_fixture(tmp_path)
    child = parent.children[0].checkpoint
    sidecar = next(Path(config.platform_root).glob("projects/*/repositories/*"))
    product_root = sidecar / "state/product"
    products = FileProductRecordStore(product_root)
    example = _spec()
    request = ProjectRequest.create(
        request_id=example.request_id,
        repository_id=child.repository_id,
        preparation_sha256="a" * 64,
        title="Native Product approval",
        original_request="Export the report.",
        status=ProjectRequestStatus.WAITING_PRODUCT_APPROVAL,
        created_at=example.created_at,
    )
    revision = products.put_request_revision(
        ProjectRequestRevision.create(
            request, revision=1, supersedes_sha256=None, recorded_at=example.created_at
        )
    )
    spec = products.put_product_spec(
        ProductSpec.create(
            spec_id=example.id,
            request_id=request.id,
            repository_id=child.repository_id,
            version=1,
            status=example.status,
            summary=example.summary,
            goals=example.goals,
            requirements=example.requirements,
            acceptance_criteria=example.acceptance_criteria,
            created_at=example.created_at,
        )
    )
    discovery = products.put_checkpoint(
        ProductDiscoveryCheckpoint.create(
            request_id=request.id,
            repository_id=child.repository_id,
            revision=1,
            previous_checkpoint_sha256=None,
            request_revision=revision.revision,
            request_sha256=request.request_sha256,
            dialogue_count=0,
            dialogue_head_sha256=None,
            current_product_spec_id=spec.id,
            current_product_spec_sha256=spec.product_spec_sha256,
            current_product_spec_version=spec.version,
            current_approval_id=None,
            current_approval_sha256=None,
            status=ProductDiscoveryStatus.WAITING_PRODUCT_APPROVAL,
            updated_at=example.created_at,
        )
    )
    identity = "delivery_native_product"
    delivery_store.put_intake(
        ProjectDeliveryIntake.create(
            delivery_id=identity,
            repository_id=child.repository_id,
            repository_root=child.repository_root,
            title=request.title,
            requirement=request.original_request,
            submitted_at=example.created_at,
        )
    )
    checkpoint = delivery_store.put(
        ProjectDeliveryCheckpoint.create(
            delivery_id=identity,
            sequence=1,
            repository_id=child.repository_id,
            repository_root=child.repository_root,
            preparation_sha256=request.preparation_sha256,
            request_id=request.id,
            request_revision=revision.revision,
            product_checkpoint_sha256=discovery.checkpoint_sha256,
            product_spec_id=spec.id,
            product_spec_sha256=spec.product_spec_sha256,
            stage=DeliveryStage.WAITING_PRODUCT_APPROVAL,
            stage_attempts=DeliveryStageAttempts(product_discovery=1),
            next_action=DeliveryNextAction.APPROVE_PRODUCT_SPEC,
            checkpointed_at=example.created_at,
        )
    )
    return ProductionTeamReader(config, {}), checkpoint, spec, product_root


def test_native_product_detail_reads_complete_exact_spec_and_keeps_old_wire(
    tmp_path: Path,
) -> None:
    reader, checkpoint, spec, _ = _native_product_fixture(tmp_path)
    summary = reader.summary("project_test")
    compact = next(request for request in summary.requests if request.id == checkpoint.delivery_id)
    assert compact.product_spec_source is not None
    assert compact.product_spec_source.spec_id == spec.id
    assert compact.product_spec_source.sha256 == spec.product_spec_sha256
    before = _bytes(Path(reader.config.platform_root))
    full = next(request for request in reader.snapshot().requests if request.id == compact.id)
    assert full.documents[0].content == ""
    detail = reader.detail(TeamDetailQuery.from_source(compact.detail_source))
    assert isinstance(detail, RequestDetail)
    assert detail.resource.model_dump(exclude={"documents"}) == full.model_dump(
        exclude={"documents"}
    )
    document = detail.resource.documents[0]
    assert document.source_uri == f"ProductSpec://{spec.id}"
    assert document.sha256 == spec.product_spec_sha256
    assert ProductSpec.model_validate_json(document.content or "null") == spec
    assert _bytes(Path(reader.config.platform_root)) == before


@pytest.mark.parametrize("change", ["corrupt", "missing", "wrong_digest", "wrong_owner"])
def test_native_product_detail_never_accepts_missing_corrupt_or_foreign_body(
    tmp_path: Path, change: str
) -> None:
    reader, checkpoint, _specification, product_root = _native_product_fixture(tmp_path)
    compact = next(
        request for request in reader.summary().requests if request.id == checkpoint.delivery_id
    )
    query = TeamDetailQuery.from_source(compact.detail_source)
    path = next((product_root / "specs").rglob("*.json"))
    if change == "corrupt":
        path.write_bytes(path.read_bytes() + b"corrupt")
    elif change == "missing":
        path.unlink()
    else:
        import json

        payload = json.loads(path.read_bytes())
        payload["product_spec_sha256" if change == "wrong_digest" else "request_id"] = (
            "f" * 64 if change == "wrong_digest" else "request_foreign"
        )
        path.write_text(json.dumps(payload), encoding="utf-8")
    before = _bytes(Path(reader.config.platform_root))
    with pytest.raises(TeamReadError):
        reader.detail(query)
    assert _bytes(Path(reader.config.platform_root)) == before


def test_verification_read_version_changes_for_same_phase_outcomes_and_sealed_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.agents import AgentRequest, AgentResult
    from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, ModelRouteAttempt
    from ai_software_engineer.artifacts import FileArtifactStore
    from ai_software_engineer.manager.dispatch import VerificationReservation
    from ai_software_engineer.recovery.models import (
        RecoveryApprovalCommand,
        RecoveryRejected,
        RecoveryScope,
    )
    from ai_software_engineer.recovery.store import FileRecoveryStore, authority_sha256
    from ai_software_engineer.recovery.verification_admission import (
        CandidateVerificationAdmission,
        ExplicitVerificationHuman,
    )
    from ai_software_engineer.recovery.verification_records import (
        CandidateVerificationCompletion,
        CandidateVerificationInvocation,
        CandidateVerificationPlan,
    )
    from ai_software_engineer.team_view import reader as read_module
    from ai_software_engineer.team_view.models import ScopeView
    from tests.e2e.test_delivery_checkpoint import _checkpoint, _full_fields, _intake
    from tests.manager.test_dispatch import RecordingDispatchStore, _facts, _service
    from tests.orchestration.test_retry import ScriptedAdapter
    from tests.orchestration.test_runner import _clock, _definitions
    from tests.recovery.test_candidate_verification import Admission, setup_verification
    from tests.recovery.test_verification_admission import Facts

    class RecordedAdapter(ScriptedAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.results: dict[str, AgentResult] = {}

        def run(self, request: AgentRequest) -> AgentResult:
            result = super().run(request)
            self.results[request.run_id] = result
            return result

    adapter = RecordedAdapter()
    inputs, repository, verifier = setup_verification(tmp_path, adapter, Admission())
    try:
        result = verifier.verify_candidate(inputs)
        scope = RecoveryScope(
            team_id="team_test",
            repository_id="repository_test",
            delivery_id="delivery_test",
            repository_root=str(tmp_path / "project"),
        )
        cp = _checkpoint(
            tmp_path / "project",
            **{
                **_full_fields(),
                "delivery_id": scope.delivery_id,
                "repository_id": scope.repository_id,
                "task_id": inputs.task_id,
                "candidate_revision": inputs.candidate_revision,
                "stage": DeliveryStage.DONE,
                "next_action": DeliveryNextAction.NONE,
            },
        )
        sidecar = tmp_path / "sidecar"
        (sidecar / "state").mkdir(parents=True)
        native = _Native(
            cp,
            _intake(
                tmp_path / "project",
                delivery_id=scope.delivery_id,
                repository_id=scope.repository_id,
            ),
            sidecar,
            (cp,),
            scope.team_id,
        )
        store = FileRecoveryStore.initialize(
            sidecar / "state" / f"candidate-verification-{scope.delivery_id}", scope=scope
        )
        plan = CandidateVerificationPlan.create(
            scope=scope,
            inputs=inputs,
            native_checkpoint_sha256=cp.checkpoint_sha256,
            dispatch_sha256=cp.dispatch_commit_sha256,
            approved_stage_chain_sha256="3" * 64,
            current_policy_sha256="4" * 64,
            definitions=tuple(_definitions().values()),
            created_at=_clock(),
        )
        admission = CandidateVerificationAdmission(
            store=store,
            plan_sha256=plan.plan_sha256,
            facts=Facts(),
            artifacts=FileArtifactStore(tmp_path / "artifacts"),
            clock=_clock,
        )
        admission.propose(plan)
        admission.approve(
            RecoveryApprovalCommand(
                operation_id="op_summary_version",
                plan_sha256=plan.plan_sha256,
                approval_reference="offline-human-confirmation",
                submitted_at=_clock(),
            ),
            human=ExplicitVerificationHuman(plan.plan_sha256),
        )
        authorization = store.get_verification_authority(plan.plan_sha256)
        (tmp_path / "dispatch").mkdir()
        dispatch_request, workforce = _facts(tmp_path / "dispatch")
        dispatch = _service(RecordingDispatchStore(), workforce, dispatch_request).commit_dispatch(
            dispatch_request
        )
        phases = tuple(
            phase.model_copy(
                update={
                    "assignment": phase.assignment.model_copy(
                        update={
                            "task_id": plan.execution_task_id,
                            "repository_id": scope.repository_id,
                        }
                    ),
                    "lease": phase.lease.model_copy(update={"task_id": plan.execution_task_id}),
                }
            )
            for phase in dispatch.phases[1:]
        )
        reservation = VerificationReservation(
            plan_sha256=plan.plan_sha256,
            repository_id=scope.repository_id,
            source_task_id=inputs.task_id,
            task_id=plan.execution_task_id,
            workforce_snapshot_sha256=dispatch.workforce_snapshot_sha256,
            phases=phases,
            committed_at=_clock(),
        )
        source_scope = ScopeView(root=scope.repository_root, selected_paths=(".",))

        def observe(release: str | None = None, abandonment: str | None = None) -> TeamDetailSource:
            versions: dict[str, str] = {}
            with recovery_record_read_scope(), source_inspection_scope():
                view = read_module._verification_view(
                    native,
                    cp.delivery_id,
                    source_scope,
                    reservation,
                    release,
                    abandonment,
                    superseded=False,
                    team_id=scope.team_id,
                    project_id="project_test",
                    include_details=False,
                    resource_states=versions,
                )
                full = read_module._verification_view(
                    native,
                    cp.delivery_id,
                    source_scope,
                    reservation,
                    release,
                    abandonment,
                    superseded=False,
                    team_id=scope.team_id,
                    project_id="project_test",
                    resource_states=versions,
                )
            assert view.status == full.status and view.task_revision is None
            assert view.documents == () and view.runs == ()
            return read_module._task_detail_source(
                scope.team_id, cp.checkpoint_sha256, view, cp.checkpoint_sha256, versions[view.id]
            )

        invocations = tuple(
            CandidateVerificationInvocation.create(
                plan_sha256=plan.plan_sha256,
                authorization_sha256=authority_sha256(authorization),
                request=request,
                admitted_at=_clock(),
            )
            for request in adapter.requests
        )
        store.put_verification_invocation(invocations[0])
        qa_started = observe()
        route = ModelRouteAttempt.create(
            request=adapter.requests[0],
            route_index=1,
            provider="offline",
            model="test",
            started_at=_clock(),
            completed_at=_clock(),
            fallback=False,
            result=adapter.results[adapter.requests[0].run_id],
        )
        FileModelRouteAttemptStore(sidecar / "runs/model-routes").append(route)
        qa_finished = observe()
        assert qa_started.resource_checkpoint_sha256 == qa_finished.resource_checkpoint_sha256
        assert qa_started.resource_state_sha256 != qa_finished.resource_state_sha256

        class ReservationCursor:
            def execute(self, *arguments: object) -> None:
                pass

            def fetchall(self) -> list[dict[str, object]]:
                return [
                    {
                        "plan_sha256": reservation.plan_sha256,
                        "payload_json": reservation.model_dump_json(),
                        "completion_sha256": None,
                        "abandonment_sha256": None,
                    }
                ]

        source_view = TaskView(
            id=cp.delivery_id,
            project_id="project_test",
            request_id=cp.delivery_id,
            task_id=inputs.task_id,
            title="Source candidate",
            scope=source_scope,
            status="DONE",
            checkpoint_stage="DONE",
            terminal=True,
            last_activity=_clock(),
            next_action="已完成。",
        )
        monkeypatch.setattr(read_module, "_read_task", lambda *args, **kwargs: source_view)
        rendered: list[str] = []
        original_render = CandidateVerificationPlan.model_dump_json

        def render_plan(selected: CandidateVerificationPlan, *, indent: int | None = None) -> str:
            rendered.append(selected.plan_sha256)
            return original_render(selected, indent=indent)

        monkeypatch.setattr(CandidateVerificationPlan, "model_dump_json", render_plan)
        with (
            pytest.raises(TeamDetailStale),
            recovery_record_read_scope(),
            source_inspection_scope(),
        ):
            read_module._read_verifications(
                ReservationCursor(),  # type: ignore[arg-type]
                {inputs.task_id: (native, cp.delivery_id, source_scope)},
                team_id=scope.team_id,
                project_id="project_test",
                include_details=False,
                detail_query=TeamDetailQuery.from_source(qa_started),
                requirement_checkpoints={cp.delivery_id: cp.checkpoint_sha256},
                resource_states={},
            )
        assert rendered == []
        monkeypatch.setattr(CandidateVerificationPlan, "model_dump_json", original_render)
        store.put_verification_invocation(invocations[1])
        review_started = observe()
        completion = store.put_verification_completion(
            CandidateVerificationCompletion.create(
                plan_sha256=plan.plan_sha256,
                authorization_sha256=authority_sha256(authorization),
                qa_invocation_sha256=invocations[0].invocation_sha256,
                reviewer_invocation_sha256=invocations[1].invocation_sha256,
                qa=result.qa,
                review=result.review,
                completed_at=_clock(),
            )
        )
        review_finished = observe()
        released = observe(completion.completion_sha256)
        abandoned = observe(abandonment="f" * 64)
        assert (
            len(
                {
                    source.resource_state_sha256
                    for source in (
                        qa_started,
                        qa_finished,
                        review_started,
                        review_finished,
                        released,
                        abandoned,
                    )
                }
            )
            == 6
        )
        assert all(source.task_revision is None for source in (qa_finished, released))
        assert observe(completion.completion_sha256) == released
        assert TeamDetailQuery.from_source(qa_started).source() != qa_finished
        before = _bytes(sidecar)
        path = next((sidecar / "state").rglob("verification-completion-*.json"))
        path.write_bytes(path.read_bytes() + b"corrupt")
        with pytest.raises(RecoveryRejected):
            observe()
        assert len(before) == len(_bytes(sidecar))
    finally:
        repository.close()


def _add_product(journal: object, parent: JointCheckpoint) -> JointCheckpoint:
    from ai_software_engineer.multi_directory.store import JointJournal

    assert isinstance(journal, JointJournal)
    draft = ProductDraft.model_validate(
        _ScriptedStructuredClient()
        .complete(
            instructions="",
            input_payload={},
            output_schema=ProductDraft.model_json_schema(),
            timeout_seconds=1,
        )
        .payload
    )
    updated = JointCheckpoint.seal(
        {
            **parent.to_wire(),
            "sequence": parent.sequence + 1,
            "previous_checkpoint_sha256": parent.checkpoint_sha256,
            "product_spec": JointProductSpec(
                scope_sha256=digest(parent.scope), version=1, product=draft
            ),
            "dialogue": tuple(
                DialogueMessage(
                    speaker="user" if number % 2 else "product",
                    text=f"turn {number}: " + "正文" * 3000,
                )
                for number in range(20)
            ),
        }
    )
    journal.append(updated, expected=parent.checkpoint_sha256)
    return updated


def test_production_summary_skips_pretty_bodies_and_details_equal_original_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, journal, parent, _ = _historical_child_fixture(tmp_path)
    parent = _add_product(journal, parent)
    reader = ProductionTeamReader(config, {})
    original = JointProductSpec.model_dump_json
    rendered: list[int] = []

    def render(spec: JointProductSpec, *, indent: int | None = None) -> str:
        rendered.append(spec.version)
        return original(spec, indent=indent)

    monkeypatch.setattr(JointProductSpec, "model_dump_json", render)
    before = _bytes(Path(config.platform_root))
    summary = reader.summary("project_test")
    assert rendered == []
    full = reader.snapshot("project_test")
    assert rendered == [1]
    for compact, complete in zip(summary.requests, full.requests, strict=True):
        assert compact.model_dump(
            exclude={"detail_source", "product_spec_source"}
        ) == complete.model_dump(exclude={"dialogue", "documents"})
    for compact_task, complete_task in zip(summary.tasks, full.tasks, strict=True):
        assert compact_task.model_dump(exclude={"detail_source"}) == complete_task.model_dump(
            exclude={"documents", "timeline", "execution_history", "runs"}
        )
    assert summary.agents == full.agents and summary.projects == full.projects
    metadata = summary.requests[0].product_spec_source
    assert metadata is not None and metadata.spec_id is None and metadata.version == 1
    assert parent.product_spec is not None
    assert metadata.sha256 == digest(parent.product_spec)
    request = reader.detail(TeamDetailQuery.from_source(summary.requests[0].detail_source))
    assert isinstance(request, RequestDetail) and request.resource == full.requests[0]
    assert len(request.resource.dialogue) == 20 and len(request.resource.documents) == 1
    task = reader.detail(TeamDetailQuery.from_source(summary.tasks[0].detail_source))
    assert isinstance(task, TaskDetail) and task.resource == full.tasks[0]
    assert _bytes(Path(config.platform_root)) == before


@pytest.mark.parametrize(
    "change", ["team", "project", "owner", "checkpoint", "resource", "deleted"]
)
def test_production_exact_detail_rejects_foreign_deleted_and_stale_sources(
    tmp_path: Path, change: str
) -> None:
    config, journal, parent, _ = _historical_child_fixture(tmp_path)
    reader = ProductionTeamReader(config, {})
    query = TeamDetailQuery.from_source(reader.summary().requests[0].detail_source)
    expected: type[TeamReadError] = TeamDetailStale
    if change == "team":
        query = query.model_copy(update={"team_id": "team_foreign"})
        expected = TeamDetailNotFound
    elif change == "project":
        query = query.model_copy(update={"project_id": "project_foreign"})
        expected = TeamDetailNotFound
    elif change == "owner":
        query = query.model_copy(update={"request_id": "delivery_multi_foreign"})
    elif change == "resource":
        query = query.model_copy(
            update={"id": "delivery_multi_foreign", "request_id": "delivery_multi_foreign"}
        )
        expected = TeamDetailNotFound
    elif change == "checkpoint":
        _add_product(journal, parent)
    else:
        RequirementRetirementStore(
            journal.root,
            team_id=parent.team_id,
            team_manifest_sha256=parent.team_manifest_sha256,
            project_id=parent.project_id,
            project_manifest_sha256=parent.project_manifest_sha256,
        ).retire(parent, reason="deleted", retired_at=datetime.now(UTC))
        expected = TeamDetailNotFound
    before = _bytes(Path(config.platform_root))
    with pytest.raises(expected):
        reader.detail(query)
    assert _bytes(Path(config.platform_root)) == before


def test_detail_rechecks_source_after_complete_body_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, journal, parent, _ = _historical_child_fixture(tmp_path)
    reader = ProductionTeamReader(config, {})
    query = TeamDetailQuery.from_source(reader.summary().requests[0].detail_source)
    original = reader._read_snapshot
    calls = 0

    def read(
        project_id: str | None,
        *,
        summary_only: bool = False,
        detail_query: TeamDetailQuery | None = None,
        source_query: TeamDetailQuery | None = None,
        joint_reads: _DetailJournalReads | None = None,
    ) -> TeamSummary | TeamDetail | object:
        nonlocal calls
        result = original(
            project_id,
            summary_only=summary_only,
            detail_query=detail_query,
            source_query=source_query,
            joint_reads=joint_reads,
        )
        calls += 1
        if calls == 1:
            _add_product(journal, parent)
        return result

    monkeypatch.setattr(reader, "_read_snapshot", read)
    with pytest.raises(TeamDetailStale):
        reader.detail(query)
    assert calls == 2


@pytest.mark.parametrize("change", ["corrupt", "symlink"])
def test_summary_and_detail_reject_unreadable_original_chain_without_writing(
    tmp_path: Path, change: str
) -> None:
    config, journal, _, _ = _historical_child_fixture(tmp_path)
    reader = ProductionTeamReader(config, {})
    query = TeamDetailQuery.from_source(reader.summary().requests[0].detail_source)
    path = next(journal.root.rglob("000001.json"))
    if change == "corrupt":
        path.write_bytes(path.read_bytes() + b"corrupt")
    else:
        external = tmp_path / "external.json"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
    before = _bytes(Path(config.platform_root))
    with pytest.raises(TeamReadError):
        reader.summary()
    with pytest.raises(TeamReadError):
        reader.detail(query)
    assert _bytes(Path(config.platform_root)) == before


class _Cursor:
    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *arguments: object) -> None:
        pass

    def execute(self, sql: str, arguments: object = None) -> None:
        assert sql.startswith(("SET TRANSACTION", "START TRANSACTION"))


class _Connection:
    def cursor(self, cursor_type: object) -> _Cursor:
        return _Cursor()

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_summary_avoids_old_task_full_hydration_but_detail_keeps_all_feedback_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _, parent, store = _historical_child_fixture(tmp_path)
    cp = parent.children[0].checkpoint
    for number in range(1, 14):
        cp = store.put(
            ProjectDeliveryCheckpoint.create(
                **{
                    **cp.to_wire(),
                    "sequence": cp.sequence + 1,
                    "previous_checkpoint_sha256": cp.checkpoint_sha256,
                    "product_spec_id": "product_spec_reads",
                    "product_spec_sha256": "1" * 64,
                    "approval_id": "approval_reads",
                    "approval_sha256": "2" * 64,
                    "technical_design_id": "design_reads",
                    "technical_design_sha256": "3" * 64,
                    "execution_plan_id": "plan_reads",
                    "execution_plan_sha256": "4" * 64,
                    "planning_preview_id": "preview_reads",
                    "planning_preview_sha256": "5" * 64,
                    "dispatch_commit_id": f"dispatch_reads_{number}",
                    "dispatch_commit_sha256": "6" * 64,
                    "task_id": f"task_reads_{number:02d}",
                    "task_revision": number,
                    "task_status": TaskStatus.BLOCKED,
                    "checkpointed_at": cp.checkpointed_at + timedelta(seconds=1),
                }
            )
        )
    calls: list[tuple[str | None, bool]] = []

    def task_read(
        snapshot: _TaskReadSnapshot,
        native: _Native,
        base: TaskView,
        *,
        dispatch_override: object = None,
        include_details: bool = True,
    ) -> TaskView:
        checkpoint = native.checkpoint
        calls.append((checkpoint.task_id, include_details))
        entry = TimelineEntry(
            id=f"finding_{checkpoint.task_id}",
            kind=ProjectionEventKind.ARTIFACT,
            occurred_at=checkpoint.checkpointed_at,
            task_id=checkpoint.task_id,
            summary="QA FAIL / Review REJECT: 修复原反馈后再交付",
            source_uri=f"artifact://finding_{checkpoint.task_id}",
            source_sha256="7" * 64,
            details={
                "kind": "qa-report",
                "status": "FAIL",
                "parent_artifact_ids": [f"implementation_{checkpoint.task_id}"],
                "coder_feedback": "必须处理本轮原始finding",
            },
        )
        return base.model_copy(
            update={
                "task_id": checkpoint.task_id,
                "task_revision": checkpoint.task_revision,
                "task_intent_sha256": "8" * 64,
                "timeline": (entry,) if include_details else (),
                "documents": (
                    DocumentView(
                        name="qa-report",
                        source_uri=entry.source_uri,
                        sha256="7" * 64,
                        content="反馈完整正文" * 3000,
                    ),
                )
                if include_details
                else (),
            }
        )

    monkeypatch.setattr(
        "ai_software_engineer.team_view.reader.open_mysql_connection", lambda dsn: _Connection()
    )
    monkeypatch.setattr(type(config), "require_mysql_dsn", lambda config, environment: "test-only")
    monkeypatch.setattr(_TaskReadSnapshot, "read", task_read)
    monkeypatch.setattr(
        "ai_software_engineer.team_view.reader._active_successor_dispatch", lambda *arguments: None
    )
    monkeypatch.setattr(
        "ai_software_engineer.team_view.reader._read_verifications",
        lambda *arguments, **keywords: (),
    )
    reader = ProductionTeamReader(config, {})
    summary = reader.summary()
    assert calls == [("task_reads_13", False)]
    assert len(summary.tasks[0].history_task_ids) == 13
    for change in (
        {"expected_task_id": "task_other"},
        {"expected_task_revision": 99},
        {"expected_task_intent_sha256": "e" * 64},
    ):
        calls.clear()
        query = TeamDetailQuery.from_source(summary.tasks[0].detail_source).model_copy(
            update=change
        )
        with pytest.raises(TeamDetailStale):
            reader.detail(query)
        assert calls == [("task_reads_13", False)]
    calls.clear()
    full = reader.snapshot()
    assert len(calls) == 13 and all(complete for _, complete in calls)
    calls.clear()
    detail = reader.detail(TeamDetailQuery.from_source(summary.tasks[0].detail_source))
    assert isinstance(detail, TaskDetail) and detail.resource == full.tasks[0]
    assert len(detail.resource.execution_history) == len(detail.resource.documents) == 13
    assert all(
        "parent_artifact_ids" in entry.details for entry in detail.resource.execution_history
    )
    assert sum(complete for _, complete in calls) == 13


def _current_task_compact_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    import ai_software_engineer.team_view.queue_reader as queue_reader
    import ai_software_engineer.team_view.reader as module

    fixture = _fixture(tmp_path)
    if phase == "live_qa":
        fixture = replace(fixture, task=fixture.task.model_copy(update={"status": TaskStatus.QA}))
    elif phase == "terminal_disposition":
        fixture = replace(
            fixture, task=fixture.task.model_copy(update={"status": TaskStatus.BLOCKED})
        )
        disposition = decide_delivery_disposition(
            DeliveryFailureFacts(
                task_id=fixture.task.id,
                role=AgentRole.QA,
                classification="ENGINEERING_AUTHORIZATION",
                source_revision=fixture.task.base_ref,
                task_intent_sha256=task_intent_sha256(fixture.task),
                checkpoint_sequence=3,
                budget_available=True,
            )
        )
        record = EngineeringDispositionRecord(
            delivery_id=fixture.receipt.scope.requirement_id,
            native_checkpoint_sha256="a" * 64,
            source_task_id=fixture.task.id,
            source_task_status=TaskStatus.BLOCKED,
            source_task_snapshot_sha256=record_digest(fixture.task.to_wire()),
            repository_root=fixture.task.repository,
            plan_sha256="b" * 64,
            rejection_code="LEGACY_AUTHORITY",
            disposition=disposition,
            recorded_at=datetime.now(UTC),
            record_sha256="0" * 64,
        )
        record = record.model_copy(update={"record_sha256": record.recompute_sha256()})
        root = fixture.sidecar / "state" / "recovery"
        root.mkdir(parents=True)
        (root / f"engineering-disposition-{record.record_sha256}.json").write_text(
            record.model_dump_json()
        )
    _start(fixture.sidecar, fixture.receipt)
    queue = (
        RoleQueueView(
            work_item_id=fixture.receipt.original_work_item_id,
            role=AgentRole.QA if phase == "live_qa" else AgentRole.CODER,
            attempt=fixture.receipt.request.attempt,
            status=WorkItemStatus.RUNNING
            if phase == "live_qa"
            else WorkItemStatus.WAITING_DEPENDENCY,
            lease_liveness="LEASE_VALID" if phase == "live_qa" else "UNKNOWN",
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=10)
            if phase == "live_qa"
            else None,
            execution_phase="ROLE_EXECUTION" if phase == "live_qa" else None,
        ),
    )
    reads, native, base, dispatch = _read_snapshot_fixture(fixture, monkeypatch)
    monkeypatch.setattr(queue_reader, "read_role_queue", lambda *arguments, **keywords: queue)
    observations: list[str] = []
    originals = {
        name: getattr(module, name)
        for name in ("_read_accepted_artifact_history", "_continuation_history")
    }

    def artifacts(*arguments: object, **keywords: object) -> object:
        observations.append("artifacts")
        return originals["_read_accepted_artifact_history"](*arguments, **keywords)

    def continuation(*arguments: object, **keywords: object) -> object:
        observations.append("continuation")
        return originals["_continuation_history"](*arguments, **keywords)

    monkeypatch.setattr(module, "_read_accepted_artifact_history", artifacts)
    monkeypatch.setattr(module, "_continuation_history", continuation)
    complete = reads.read(native, base, dispatch_override=dispatch, include_details=True)
    compact = reads.read(native, base, dispatch_override=dispatch, include_details=False)
    assert compact.model_dump(exclude={"documents", "runs"}) == complete.model_dump(
        exclude={"documents", "runs"}
    )
    assert observations == ["artifacts", "continuation"] * 2
    assert compact.role_queue == queue and compact.execution is not None
    if phase == "current_receipt":
        assert compact.execution.receipt_uri is not None
    elif phase == "live_qa":
        assert compact.execution.state == "RUNNING" and compact.execution.receipt_uri is None
    else:
        assert compact.execution.reason_code == "ENGINEERING_AUTHORIZATION"
        assert compact.execution.state == "STOPPED"
    # Fresh compact reads re-open actual filesystem facts, including a complete
    # terminal/receipt body, rather than keeping a successful display cache.
    path = next((fixture.sidecar / "state" / "continuations").rglob("receipt*.json"))
    path.write_bytes(path.read_bytes() + b"corrupt")
    fresh, native, base, dispatch = _read_snapshot_fixture(fixture, monkeypatch)
    monkeypatch.setattr(queue_reader, "read_role_queue", lambda *arguments, **keywords: queue)
    with pytest.raises((ValueError, KnowledgeError, ContinuationRejected)):
        fresh.read(native, base, dispatch_override=dispatch, include_details=False)


@pytest.mark.parametrize("phase", ["current_receipt", "live_qa", "terminal_disposition"])
def test_current_task_compact_projection_keeps_real_receipts_queue_and_terminal_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    # Match the production synchronous reader scope; source and every later
    # ledger read still reopen original bytes and reject the mutated receipt.
    with recovery_record_read_scope(), source_inspection_scope():
        _current_task_compact_projection(tmp_path, monkeypatch, phase)
