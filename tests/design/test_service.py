"""Designer application, persistence, and interrupted commit recovery tests."""

from pathlib import Path

import pytest

from ai_software_engineer.design import (
    DesignerAgentRequest,
    DesignerAgentResult,
    DesignerInputStale,
    DesignerOutputRejected,
    DesignerRunConflict,
    DesignerService,
    DesignRunOutcome,
    FakeDesignerAgentAdapter,
    FakeDesignerBehavior,
    FakeDesignerScenario,
    FileDesignRecordStore,
)
from ai_software_engineer.domain import ProjectRequestStatus
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.product.store import FileProductRecordStore
from tests.design.factories import BoundStageAdvancer, approved_facts, design_for


class CountingAdapter(FakeDesignerAgentAdapter):
    def __init__(self, scenario: FakeDesignerScenario) -> None:
        super().__init__(default=scenario)
        self.calls = 0

    def run(self, request: DesignerAgentRequest) -> DesignerAgentResult:
        self.calls += 1
        return super().run(request)


class AdvanceRevisionDuringRunAdapter(CountingAdapter):
    """Simulate another stage writer winning while the model is running."""

    def __init__(
        self,
        scenario: FakeDesignerScenario,
        store: FileProductRecordStore,
        current: ProjectRequestRevision,
    ) -> None:
        super().__init__(scenario)
        self._store = store
        self._current = current

    def run(self, request: DesignerAgentRequest) -> DesignerAgentResult:
        advanced = ProjectRequestRevision.create(
            self._current.request,
            revision=self._current.revision + 1,
            supersedes_sha256=self._current.request_revision_sha256,
            recorded_at=self._current.recorded_at,
        )
        self._store.compare_and_put_request_revision(
            advanced,
            expected_current_sha256=self._current.request_revision_sha256,
        )
        return super().run(request)


class FailNextRevisionStore(FileProductRecordStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.fail_next = False

    def compare_and_put_request_revision(
        self,
        record: ProjectRequestRevision,
        *,
        expected_current_sha256: StageSha256 | None,
    ) -> ProjectRequestRevision:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated interruption before revision publish")
        return super().compare_and_put_request_revision(
            record,
            expected_current_sha256=expected_current_sha256,
        )


def _service(
    tmp_path: Path,
    product_store: FileProductRecordStore,
    adapter: FakeDesignerAgentAdapter,
    advancer: BoundStageAdvancer,
) -> DesignerService:
    return DesignerService(
        design_store=FileDesignRecordStore(tmp_path / "design-records"),
        product_store=product_store,
        adapter=adapter,
        stage_advancer=advancer,
    )


def test_success_appends_planning_revision_and_commits_exact_handoff(tmp_path: Path) -> None:
    command, product_store, advancer = approved_facts(tmp_path)
    design = design_for(command)
    adapter = CountingAdapter(
        FakeDesignerScenario(behavior=FakeDesignerBehavior.READY, technical_design=design)
    )
    service = _service(tmp_path, product_store, adapter, advancer)

    result = service.run(command)

    assert result.run_record.outcome is DesignRunOutcome.READY_FOR_PLANNING
    assert result.technical_design == design
    assert result.request_revision is not None
    assert result.request_revision.revision == command.request_revision.revision + 1
    assert result.request_revision.request.status is ProjectRequestStatus.PLANNING
    assert (
        result.request_revision.supersedes_sha256
        == command.request_revision.request_revision_sha256
    )
    assert result.planning_authorization is not None
    assert result.checkpoint is not None
    assert product_store.current_request_revision(command.request_revision.request.id) == (
        result.request_revision
    )
    assert adapter.calls == 1
    assert advancer.calls == 1

    replay = service.run(command.model_copy())
    assert replay.replayed is True
    assert replay.run_record == result.run_record
    assert replay.checkpoint == result.checkpoint
    assert adapter.calls == 1
    assert advancer.calls == 1


def test_interruption_after_design_receipt_recovers_revision_before_commit(
    tmp_path: Path,
) -> None:
    command, seeded, _ = approved_facts(tmp_path)
    product_store = FailNextRevisionStore(tmp_path / "recover-product")
    product_store.put_request_revision(command.request_revision)
    product_store.put_product_spec(command.product_spec)
    product_store.put_approval(command.product_approval)
    design = design_for(command)
    adapter = CountingAdapter(
        FakeDesignerScenario(behavior=FakeDesignerBehavior.READY, technical_design=design)
    )
    advancer = BoundStageAdvancer()
    service = _service(tmp_path, product_store, adapter, advancer)
    product_store.fail_next = True

    with pytest.raises(RuntimeError, match="simulated interruption"):
        service.run(command)
    design_store = FileDesignRecordStore(tmp_path / "design-records")
    assert design_store.find_run(command.run_id) is not None
    assert design_store.find_design(design.id) is None
    assert design_store.find_checkpoint(command.run_id) is None
    assert product_store.current_request_revision(command.request_revision.request.id) == (
        command.request_revision
    )

    recovered = service.run(command)
    assert recovered.replayed is True
    assert recovered.checkpoint is not None
    assert design_store.find_design(design.id) == design
    assert recovered.request_revision is not None
    assert recovered.request_revision.request.status is ProjectRequestStatus.PLANNING
    assert adapter.calls == 1
    assert advancer.calls == 1
    del seeded


def test_failure_does_not_write_design_revision_or_checkpoint(tmp_path: Path) -> None:
    command, product_store, advancer = approved_facts(tmp_path)
    service = _service(
        tmp_path,
        product_store,
        FakeDesignerAgentAdapter(
            default=FakeDesignerScenario(behavior=FakeDesignerBehavior.TIMEOUT)
        ),
        advancer,
    )

    result = service.run(command)

    assert result.run_record.outcome is DesignRunOutcome.TIMED_OUT
    assert result.checkpoint is None
    assert result.technical_design is None
    assert product_store.current_request_revision(command.request_revision.request.id) == (
        command.request_revision
    )
    assert advancer.calls == 0


def test_concurrent_revision_advance_during_agent_call_leaves_no_design_effects(
    tmp_path: Path,
) -> None:
    command, product_store, advancer = approved_facts(tmp_path)
    design = design_for(command)
    adapter = AdvanceRevisionDuringRunAdapter(
        FakeDesignerScenario(
            behavior=FakeDesignerBehavior.READY,
            technical_design=design,
        ),
        product_store,
        command.request_revision,
    )
    service = _service(tmp_path, product_store, adapter, advancer)

    with pytest.raises(DesignerInputStale):
        service.run(command)

    design_store = FileDesignRecordStore(tmp_path / "design-records")
    assert design_store.find_run(command.run_id) is None
    assert design_store.find_design(design.id) is None
    assert design_store.find_checkpoint(command.run_id) is None
    assert adapter.calls == 1
    assert advancer.calls == 0


def test_stale_product_facts_run_conflict_and_bad_coverage_fail_closed(tmp_path: Path) -> None:
    command, product_store, advancer = approved_facts(tmp_path)
    design = design_for(command)
    service = _service(
        tmp_path,
        product_store,
        FakeDesignerAgentAdapter(
            default=FakeDesignerScenario(
                behavior=FakeDesignerBehavior.READY, technical_design=design
            )
        ),
        advancer,
    )
    changed_command = command.model_copy(update={"timeout_seconds": 30})
    first = service.run(command)
    assert first.checkpoint is not None
    with pytest.raises(DesignerRunConflict):
        service.run(changed_command)

    other_path = tmp_path / "stale"
    other_path.mkdir()
    stale_command, stale_store, stale_advancer = approved_facts(other_path)
    newer = ProjectRequestRevision.create(
        stale_command.request_revision.request,
        revision=2,
        supersedes_sha256=stale_command.request_revision.request_revision_sha256,
        recorded_at=stale_command.submitted_at,
    )
    stale_store.put_request_revision(newer)
    stale_service = _service(
        other_path,
        stale_store,
        FakeDesignerAgentAdapter(
            default=FakeDesignerScenario(
                behavior=FakeDesignerBehavior.READY,
                technical_design=design_for(stale_command),
            )
        ),
        stale_advancer,
    )
    with pytest.raises(DesignerInputStale):
        stale_service.run(stale_command)

    bad_path = tmp_path / "bad"
    bad_path.mkdir()
    bad_command, bad_store, bad_advancer = approved_facts(bad_path)
    bad_design = design_for(bad_command).model_copy(update={"requirement_mappings": ()})
    bad_service = _service(
        bad_path,
        bad_store,
        FakeDesignerAgentAdapter(
            default=FakeDesignerScenario(
                behavior=FakeDesignerBehavior.READY,
                technical_design=bad_design,
            )
        ),
        bad_advancer,
    )
    with pytest.raises(DesignerOutputRejected, match=r"invalid output|coverage"):
        bad_service.run(bad_command)
