"""Restart-safe investigation handoff without fabricated approvals or live models."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import StructuredModelResult
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.agents import (
    KnowledgeAwareStructuredClient,
    RepositoryInspection,
)
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeGapRaised,
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
)
from ai_software_engineer.knowledge.models import KnowledgeError, digest, text_digest
from ai_software_engineer.knowledge.runtime import joint_knowledge_client
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery import DeliveryCheckpointStale, ResumeProjectDelivery
from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointStage,
    JointTechnicalDesign,
)
from ai_software_engineer.multi_directory.planning import joint_planning_decision
from ai_software_engineer.multi_directory.service import JointDeliveryService, RecheckDesign
from tests.knowledge.test_consultation import Model
from tests.knowledge.test_gaps import Approval
from tests.manager.test_joint_designer_feedback import DesigningBackend, setup_design
from tests.manager.test_joint_planner_feedback import DeliveryReached


class CaptureModel(Model):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: dict[str, Mapping[str, object]] = {}

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        name = str(output_schema["title"])
        self.inputs[name] = input_payload
        if name == "KnowledgeIntent":
            self.calls.append(name)
            return StructuredModelResult(payload={"queries": []}, duration_ms=0)
        return super().complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
        )


def wait_at_plan(
    tmp_path: Path,
) -> tuple[JointDeliveryService, DesigningBackend, JointCheckpoint, KnowledgeGap, RecheckDesign]:
    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    assert isinstance(valid, JointTechnicalDesign)
    planning = service._save(
        seed,
        stage=JointStage.PLANNING,
        design=valid,
        attempts={"product": 2, "design": 1, "plan": 1},
    )
    planning = service._save(planning, planning_decision=joint_planning_decision(planning))
    root = service.journal.directory(seed.delivery_id) / "knowledge"
    client = joint_knowledge_client(Model(), planning, TeamRole.PLANNER, root)
    with pytest.raises(KnowledgeGapRaised) as error:
        client.complete(
            instructions="Plan",
            input_payload=planning.to_wire(),
            output_schema={"title": "Output"},
            timeout_seconds=10,
        )
    gap = error.value.gap
    waiting = service._save(
        planning,
        stage=JointStage.WAITING_HUMAN,
        knowledge_wait_stage=JointStage.PLANNING,
        knowledge_gap_id=gap.gap_id,
    )
    command = RecheckDesign(
        delivery_id=waiting.delivery_id,
        expected_checkpoint_sha256=waiting.checkpoint_sha256,
        operator_id="test-user",
        request_reference="human-recheck:001",
    )
    return service, backend, waiting, gap, command


def approve(records: KnowledgeRecordStore, gap: KnowledgeGap) -> KnowledgeResolution:
    answer = "仅删除两个字，其他功能不变。"  # noqa: RUF001
    item = KnowledgeResolution(
        gap_id=gap.gap_id,
        previous_run_id=gap.binding.run_id,
        answer=answer,
        sources=(
            KnowledgeResolutionSource(
                uri="human://prior-answer", content=answer, sha256=text_digest(answer)
            ),
        ),
        approval_reference="human-answer:001",
        approved_by="test-user",
        resolution_id="0" * 64,
    )
    item = item.model_copy(
        update={"resolution_id": digest(item.model_dump(mode="json", exclude={"resolution_id"}))}
    )
    return KnowledgeGapService(records).resolve(item, Approval(item))


def test_recheck_keeps_approval_history_budget_and_requires_later_continue(tmp_path: Path) -> None:
    service, backend, waiting, gap, command = wait_at_plan(tmp_path)
    recovered = service.recheck_design(command).checkpoint
    assert recovered.stage is JointStage.DESIGNING
    assert recovered.approval == waiting.approval and recovered.product_spec == waiting.product_spec
    assert recovered.attempts == waiting.attempts
    assert recovered.design is None and recovered.plan is None
    assert waiting.planning_decision is not None and recovered.planning_decision is None
    assert recovered.knowledge_gap_id is None and recovered.knowledge_wait_stage is None
    assert recovered.knowledge_rechecks and recovered.knowledge_rechecks[0].gap == gap
    assert not backend.design_inputs and not backend.inputs
    records = KnowledgeRecordStore(service.journal.directory(waiting.delivery_id) / "knowledge")
    assert records.find("gap-resolutions", gap.gap_id, KnowledgeResolution) is None
    assert service.journal.history(waiting.delivery_id)[-2] == waiting
    reopened = JointDeliveryService(backend=backend, team=service.team, project=service.project)
    assert reopened.status(waiting.delivery_id).checkpoint == recovered
    with pytest.raises(DeliveryCheckpointStale):
        reopened.recheck_design(command)
    backend.designs = backend.designs[1:]
    with pytest.raises(DeliveryReached):
        reopened.resume(ResumeProjectDelivery(delivery_id=waiting.delivery_id))
    final = reopened.status(waiting.delivery_id).checkpoint
    assert final.stage is JointStage.DELIVERING and final.attempts["design"] == 2


def test_recheck_is_investigation_only_new_human_gap_still_blocks(tmp_path: Path) -> None:
    service, _, waiting, old_gap, command = wait_at_plan(tmp_path)
    recovered = service.recheck_design(command).checkpoint
    root = service.journal.directory(waiting.delivery_id) / "knowledge"
    capture = CaptureModel()
    client = joint_knowledge_client(capture, recovered, TeamRole.DESIGNER, root)
    client.complete(
        instructions="Design",
        input_payload=recovered.to_wire(),
        output_schema={"title": "Output"},
        timeout_seconds=10,
    )
    task = capture.inputs["KnowledgeIntent"]["task"]
    assert isinstance(task, dict) and task["design_rechecks"][0]["gap"]["gap_id"] == old_gap.gap_id
    next_cp = service._save(recovered, attempts={**recovered.attempts, "design": 2})
    client = joint_knowledge_client(Model(), next_cp, TeamRole.DESIGNER, root)
    with pytest.raises(KnowledgeGapRaised) as error:
        client.complete(
            instructions="Design",
            input_payload=next_cp.to_wire(),
            output_schema={"title": "Output"},
            timeout_seconds=10,
        )
    assert error.value.gap.gap_id != old_gap.gap_id
    again = service._save(next_cp, next_action="still investigate")
    untouched = CaptureModel()
    client = joint_knowledge_client(untouched, again, TeamRole.PLANNER, root)
    with pytest.raises(KnowledgeGapRaised) as repeated:
        client.complete(
            instructions="Plan",
            input_payload=again.to_wire(),
            output_schema={"title": "Output"},
            timeout_seconds=10,
        )
    assert repeated.value.gap == error.value.gap and not untouched.calls


@pytest.mark.parametrize(
    "change", ["resolved", "design_budget", "transient_budget", "wrong_stage", "foreign_scope"]
)
def test_recheck_rejects_unsafe_inputs_without_appending(tmp_path: Path, change: str) -> None:
    service, _, waiting, gap, command = wait_at_plan(tmp_path)
    records = KnowledgeRecordStore(service.journal.directory(waiting.delivery_id) / "knowledge")
    if change == "resolved":
        approve(records, gap)
    elif change.endswith("budget"):
        key, value = ("design", 3) if change == "design_budget" else ("design_transient", 5)
        waiting = service._save(waiting, attempts={**waiting.attempts, key: value})
    elif change == "wrong_stage":
        waiting = service._save(waiting, knowledge_wait_stage=JointStage.PRODUCT_DISCOVERY)
    else:
        foreign = gap.model_copy(
            update={"binding": gap.binding.model_copy(update={"project_id": "project_other"})}
        )
        foreign = foreign.model_copy(
            update={"gap_id": digest(foreign.model_dump(mode="json", exclude={"gap_id"}))}
        )
        records.put("gaps", foreign.gap_id, foreign)
        waiting = service._save(waiting, knowledge_gap_id=foreign.gap_id)
    command = command.model_copy(update={"expected_checkpoint_sha256": waiting.checkpoint_sha256})
    with pytest.raises((ValueError, KnowledgeError), match=r"design recheck|GAP_NOT_FOUND"):
        service.recheck_design(command)
    assert service.status(waiting.delivery_id).checkpoint == waiting


def test_approved_upstream_facts_and_exact_git_context_reach_all_calls(tmp_path: Path) -> None:
    service, _, waiting, gap, _ = wait_at_plan(tmp_path)
    root = service.journal.directory(waiting.delivery_id) / "knowledge"
    records = KnowledgeRecordStore(root)
    resolution = approve(records, gap)
    cp = service._save(
        waiting, stage=JointStage.DESIGNING, knowledge_gap_id=None, knowledge_wait_stage=None
    )
    capture = CaptureModel()
    inspection = tuple(
        RepositoryInspection(
            unit_id=u.id,
            repository_id=p.result.repository_id,
            read_root=u.root,
            git_revision=u.base_revision or "",
        )
        for u, p in zip(cp.scope.units, cp.preparations, strict=True)
    )
    client = joint_knowledge_client(
        capture, cp, TeamRole.DESIGNER, root, repository_inspection=inspection
    )
    assert isinstance(client, KnowledgeAwareStructuredClient)
    assert client.binding.source_revision != inspection[0].git_revision
    client.complete(
        instructions="Design",
        input_payload=cp.to_wire(),
        output_schema={"title": "Output"},
        timeout_seconds=10,
    )
    task = capture.inputs["KnowledgeIntent"]["task"]
    assert isinstance(task, dict)
    assert task["approved_knowledge_resolutions"] == [resolution.to_wire()]
    assert task["repository_inspection"] == [r.to_wire() for r in inspection]
    final = capture.inputs["Output"]
    assert final["repository_inspection"] == task["repository_inspection"]
    assert final["knowledge_consultation"]["resolutions"] == [resolution.to_wire()]  # type: ignore[index]


def test_recheck_cannot_change_scope_or_erase_history(tmp_path: Path) -> None:
    service, _, _waiting, _, command = wait_at_plan(tmp_path)
    recovered = service.recheck_design(command).checkpoint
    with pytest.raises(ValueError, match="append-only"):
        service._save(recovered, knowledge_rechecks=None)
    assert recovered.knowledge_rechecks
    recheck = recovered.knowledge_rechecks[0]
    with pytest.raises(KnowledgeError, match="RECHECK_BINDING"):
        recheck.validate_binding(
            recheck.gap.binding.model_copy(update={"source_revision": "f" * 64})
        )


def test_read_projection_retains_wait_origin_and_recheck_readiness(tmp_path: Path) -> None:
    from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
    from ai_software_engineer.team_view.reader import ProductionTeamReader

    service, _, waiting, _, command = wait_at_plan(tmp_path)
    reader = ProductionTeamReader(
        ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            team_id="team_test",
            team_name="Test",
            model_routes=(
                ProviderRouteConfig(
                    provider="codex", model="test", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        {},
    )
    view = reader.snapshot("project_test").requests[0]
    assert view.knowledge_wait_stage == "PLANNING"
    assert view.design_recheck_available and not view.design_recheck_pending
    service.recheck_design(command)
    view = reader.snapshot("project_test").requests[0]
    assert view.stage == "DESIGNING" and view.knowledge_wait_stage is None
    assert not view.design_recheck_available and view.design_recheck_pending
    assert view.knowledge_rechecked_gap_ids == (waiting.knowledge_gap_id,)


def test_legacy_checkpoint_and_nested_payload_omit_new_absent_fields(tmp_path: Path) -> None:
    from tests.manager.test_joint_contracts import checkpoint

    cp = checkpoint(tmp_path)
    assert cp.design is not None
    legacy = cp.design.model_copy(update={"blocking_issues": None})
    assert "blocking_issues" not in legacy.model_dump(mode="json")
    sealed = JointCheckpoint.seal({**cp.to_wire(), "design": legacy, "plan": None})
    restored = JointCheckpoint.model_validate_json(sealed.model_dump_json())
    restored.validate_integrity()
    for field in ("knowledge_rechecks", "design_feedback"):
        assert field not in restored.model_dump(mode="json")


@pytest.mark.parametrize("candidate", [False, True])
def test_production_inspection_uses_exact_role_roots_and_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, candidate: bool
) -> None:
    from ai_software_engineer.multi_directory.production import ProductionJointBackend
    from tests.manager.test_joint_planner_feedback import _done_child

    service, _, waiting, _, _ = wait_at_plan(tmp_path)
    child = _done_child(waiting, 0)
    child = child.model_copy(
        update={"checkpoint": child.checkpoint.model_copy(update={"candidate_revision": "e" * 40})}
    )
    cp = waiting.model_copy(update={"children": (child,) if candidate else ()})
    roots = tuple(
        tmp_path / ("candidate" if candidate else "baseline") / u.id for u in cp.scope.units
    )
    captured_roots: list[tuple[Path, ...]] = []

    class Clients:
        def for_projects(
            self, paths: tuple[Path, ...], role: TeamRole = TeamRole.PRODUCT
        ) -> CaptureModel:
            captured_roots.append(paths)
            return CaptureModel()

        def for_project(self, path: Path, role: TeamRole = TeamRole.PRODUCT) -> CaptureModel:
            raise AssertionError("multi-repository context must not collapse to one root")

    backend = object.__new__(ProductionJointBackend)
    backend.clients = Clients()
    backend.project = service.project
    monkeypatch.setattr(backend, "_baseline_paths", lambda _cp: roots)
    monkeypatch.setattr(backend, "_candidate_paths", lambda _cp: roots)
    monkeypatch.setattr(
        "ai_software_engineer.knowledge.index.retrieval_for_project", lambda _p: None
    )
    client = backend.client(cp, TeamRole.PLANNER)
    assert isinstance(client, KnowledgeAwareStructuredClient)
    assert captured_roots == [roots]
    assert tuple(r.read_root for r in client.repository_inspection) == tuple(map(str, roots))
    assert client.repository_inspection[0].git_revision == (
        "e" * 40 if candidate else cp.scope.units[0].base_revision
    )
    assert client.repository_inspection[1].git_revision == cp.scope.units[1].base_revision


def test_recheck_is_rejected_after_child_dispatch(tmp_path: Path) -> None:
    from tests.manager.test_joint_planner_feedback import _done_child

    service, _, waiting, _, command = wait_at_plan(tmp_path)
    dispatched = service._save(waiting, children=(_done_child(waiting, 0),))
    with pytest.raises(ValueError, match="design recheck"):
        service.recheck_design(
            command.model_copy(update={"expected_checkpoint_sha256": dispatched.checkpoint_sha256})
        )
    assert service.status(waiting.delivery_id).checkpoint == dispatched
