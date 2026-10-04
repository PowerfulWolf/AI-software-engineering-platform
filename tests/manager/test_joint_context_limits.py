"""Prompt compaction must retain frozen rules and complete upstream stage outputs."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents import StructuredModelResult
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.context.native import native_rule_prompt_sources
from ai_software_engineer.context.ports import ContextBudgetExceeded
from ai_software_engineer.context.profile import repository_profile_context
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy
from ai_software_engineer.knowledge.context import snapshot_from_sources
from ai_software_engineer.knowledge.delivery import KnowledgeDeliveryGate
from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline import ProjectSpecBaseline, _baseline_digest
from ai_software_engineer.manager.production_agents import ProductDraft
from ai_software_engineer.manager.production_backend import PRODUCTION_DELIVERY_CONTEXT_BUDGET
from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointExecutionPlan,
    JointTechnicalDesign,
)
from ai_software_engineer.multi_directory.production import (
    ProductionJointBackend,
    approved_joint_context_sources,
)
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryingOrchestrator
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import make_agent, make_task
from tests.knowledge.test_delivery_context import Clients
from tests.manager.test_baseline import hard_rule
from tests.manager.test_joint_contracts import checkpoint
from tests.manager.test_production_backend import _git, _git_output
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task


@pytest.mark.parametrize("count,accepted", [(6, True), (20, False)])
def test_preparation_freezes_large_rule_corpus_without_expanding_model_input(
    tmp_path: Path, count: int, accepted: bool
) -> None:
    current = checkpoint(tmp_path)
    unit = current.scope.units[0]
    root = Path(unit.root)
    rules = root / ".trellis/spec/core"
    rules.mkdir(parents=True)
    body = "Frozen project rule.\n" * 11_000
    for index in range(count):
        (rules / f"rule-{index}.md").write_text(body)
    (root / "AGENTS.md").write_text("Read applicable frozen project rules.\n")
    _git("init", "-b", "main", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    _git("config", "user.email", "test@example.invalid", cwd=root)
    _git("add", ".", cwd=root)
    _git("commit", "-m", "Freeze project rules", cwd=root)
    unit = unit.model_copy(update={"base_revision": _git_output("rev-parse", "HEAD", cwd=root)})
    native = Mock()
    native.prepare.return_value = current.preparations[0].result
    native.prepared_context.return_value = ()
    backend = ProductionJointBackend(
        native=native, factory=Mock(), clients=Mock(), team=Mock(), project=Mock(), environment={}
    )
    if not accepted:
        with pytest.raises(ValueError, match="冻结数据超过存储上限"):
            backend.prepare(unit)
        return

    prepared = backend.prepare(unit)
    assert len(prepared.context_sources) == count + 1
    assert sum(len((s.content or "").encode()) for s in prepared.context_sources) > 1_000_000
    assert all(s.content == body for s in prepared.context_sources if "rule-" in s.uri)
    projected = native_rule_prompt_sources(prepared.context_sources)
    assert sum(len(s.content or "") for s in projected) < 10_000
    assert next(s.content for s in projected if s.uri.endswith("AGENTS.md")) == (
        "Read applicable frozen project rules.\n"
    )


def joint_sources(tmp_path: Path) -> tuple[JointCheckpoint, tuple[ContextSource, ...]]:
    current = checkpoint(tmp_path)
    prepared = current.preparations[0]
    repository_id = prepared.result.repository_id
    rules = tuple(
        ContextSource(
            source_id=f"native.rule.{index}",
            uri=f"project://{repository_id}/.trellis/spec/core/rule-{index}.md",
            content=(
                "# Refunds\nUse original payment identity. Preserve the ledger sequence.\n"
                + "General project guidance.\n" * 9_000
            ),
            required=True,
        )
        for index in range(3)
    )
    agents = tuple(
        ContextSource(
            source_id=f"native.rule.agents{index}",
            uri=f"project://{repository_id}/{path}",
            content="Read applicable project rules before coding.\n",
            required=True,
        )
        for index, path in enumerate(("AGENTS.md", "src/AGENTS.md"))
    )
    frozen = prepared.model_copy(update={"context_sources": (*rules, *agents)})
    current = JointCheckpoint.seal(
        {**current.to_wire(), "preparations": (frozen, *current.preparations[1:])}
    )
    return current, approved_joint_context_sources(current, prepared.unit_id)


def test_projection_keeps_frozen_rules_and_full_approved_stages(tmp_path: Path) -> None:
    current, sources = joint_sources(tmp_path)
    assert sources[1:] == current.preparations[0].context_sources
    assert current.product_spec and current.design and current.plan and current.approval
    shared = json.loads(sources[0].content or "")
    for key, value in (
        ("product", current.product_spec),
        ("design", current.design),
        ("plan", current.plan),
        ("approval", current.approval),
    ):
        assert shared[key] == value.to_wire()
    projected = native_rule_prompt_sources(sources)
    assert projected[0] == sources[0]
    assert projected[-2:] == sources[-2:]  # Nested AGENTS instructions also remain full.
    assert all(source.required for source in projected)
    assert all("Preserve the ledger sequence" not in (s.content or "") for s in projected[1:4])
    legacy_bundle = FileRunContextBuilder(
        tmp_path, sources=sources, budget=PRODUCTION_DELIVERY_CONTEXT_BUDGET
    ).build(make_task(), make_agent(), attempt=1)
    assert all(not section.truncated for section in legacy_bundle.sections)
    bundle = FileRunContextBuilder(
        tmp_path, sources=projected, budget=PRODUCTION_DELIVERY_CONTEXT_BUDGET
    ).build(make_task(), make_agent(), attempt=1)
    assert all(not section.truncated for section in bundle.sections)


@pytest.mark.parametrize("stage", ["product", "design", "plan"])
def test_joint_stage_producer_projects_prompt_but_passes_full_checkpoint_to_knowledge(
    tmp_path: Path,
    stage: str,
) -> None:
    current, _ = joint_sources(tmp_path)
    assert current.product_spec and current.design and current.plan
    before = current.to_wire()
    output = {
        "product": current.product_spec.product,
        "design": current.design,
        "plan": current.plan,
    }[stage]
    model = {"product": ProductDraft, "design": JointTechnicalDesign, "plan": JointExecutionPlan}[
        stage
    ]
    client = Mock()
    client.complete.return_value = StructuredModelResult(payload=output.to_wire(), duration_ms=1)
    service = object.__new__(JointDeliveryService)
    service.backend = Mock()
    service.backend.client.return_value = client
    service.execution_retry_policy = ExecutionRetryPolicy()
    service.attachments = Mock()

    assert service._produce(current, model, "Produce the requested stage.") == output
    payload = client.complete.call_args.kwargs["input_payload"]
    assert len(json.dumps(payload, ensure_ascii=False)) < 50_000
    assert "General project guidance." not in json.dumps(payload)
    assert "Read applicable project rules before coding." in json.dumps(payload)
    assert payload["product_spec"] == before["product_spec"]
    assert payload["design"] == before["design"]
    assert payload["plan"] == before["plan"]
    assert payload["approval"] == before["approval"]
    assert payload["scope"] == before["scope"]
    assert service.backend.client.call_args.args[0] is current
    assert current.to_wire() == before


@pytest.mark.parametrize("rework", ["none", "qa", "progress"])
def test_complete_role_chain_retains_artifacts_and_frozen_read_text(
    tmp_path: Path, rework: str
) -> None:
    current, sources = joint_sources(tmp_path)
    repository_id = current.preparations[0].result.repository_id
    profile = RepositoryProfile.discover(tmp_path, repository_id=repository_id)
    baseline = ProjectSpecBaseline(
        repository_id=repository_id,
        repository_profile_sha256=profile.profile_sha256,
        rules=(hard_rule(),),
        baseline_sha256="0" * 64,
    )
    baseline = baseline.model_copy(update={"baseline_sha256": _baseline_digest(baseline)})
    sources += (
        repository_profile_context(profile),
        ContextSource(
            source_id="project.baseline",
            uri=f"baseline://{repository_id}/frozen",
            content=json.dumps(baseline.to_wire()),
            required=True,
        ),
    )
    frozen = snapshot_from_sources(
        team_id=current.team_id,
        project_id=current.project_id,
        requirement_id=current.delivery_id,
        repository_ids=(repository_id,),
        sources=tuple((repository_id, s) for s in sources),
    )
    contexts = FileContextStore(tmp_path / "contexts")
    records = KnowledgeRecordStore(tmp_path / "knowledge")
    builder = KnowledgeRunContextBuilder(
        FileRunContextBuilder(
            tmp_path,
            sources=native_rule_prompt_sources(sources),
            context_store=contexts,
            budget=PRODUCTION_DELIVERY_CONTEXT_BUDGET,
        ),
        contexts=contexts,
        clients=Clients(),
        repository_root=tmp_path,
        records=records,
        team_id=current.team_id,
        project_id=current.project_id,
        repository_id=repository_id,
        sources=sources,
    )
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    adapter = ScriptedAdapter(
        qa_failures=(1,) if rework == "qa" else (),
        coder_progress=(1,) if rework == "progress" else (),
    )
    task = _task(tmp_path)
    with SqliteTaskRepository(tmp_path / "tasks.sqlite") as repository:
        repository.create(task)
        result = RetryingOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=builder,
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            clock=_clock,
            transition_gate=KnowledgeDeliveryGate(
                records=records, artifacts=artifacts, contexts=contexts
            ),
        ).run_task(task.id)
    assert result.task.status is TaskStatus.DONE
    assert records.get("snapshots", frozen.snapshot_sha256, type(frozen)) == frozen
    assert {r.role for r in adapter.requests} == set(AgentRole)
    for request in adapter.requests:
        context = contexts.get(request.context_manifest_id)
        sections = {s.name.removeprefix("source:"): s for s in context.sections}
        assert {
            "policy",
            "task",
            "role",
            "project.profile",
            "project.baseline",
            "joint.approved_context",
        } <= sections.keys()
        assert json.loads(sections["joint.approved_context"].content) == json.loads(
            sources[0].content or ""
        )
        assert all(not s.truncated for s in context.sections)
        assert context.budget.max_input_tokens == 256_000
        assert context.budget.used_input_tokens == sum(s.tokens for s in context.sections)
        for identity in request.input_artifact_ids:
            assert (
                json.loads(sections[f"artifact.{identity}"].content)
                == artifacts.get(identity).to_wire()
            )
        if request.role is not AgentRole.ORCHESTRATOR:
            assert "knowledge.consultation" in sections
            # This exact rule is absent from both the pointer and the model's claim.
            assert "Preserve the ledger sequence." in sections["knowledge.reads"].content
    if rework != "none":
        assert ("art_qa_001" if rework == "qa" else "art_progress_001") in next(
            r for r in adapter.requests if r.role is AgentRole.CODER and r.attempt == 2
        ).input_artifact_ids


@pytest.mark.parametrize("size,accepted", [(520_000, True), (1_100_000, False)])
def test_production_budget_accepts_larger_required_inputs_but_remains_bounded(
    tmp_path: Path, size: int, accepted: bool
) -> None:
    builder = FileRunContextBuilder(
        tmp_path,
        budget=PRODUCTION_DELIVERY_CONTEXT_BUDGET,
        sources=(
            ContextSource(
                source_id="approved", uri="approved://fixture", content="x" * size, required=True
            ),
        ),
    )
    if not accepted:
        with pytest.raises(ContextBudgetExceeded):
            builder.build(make_task(), make_agent(), attempt=1)
    else:
        context = builder.build(make_task(), make_agent(), attempt=1)
        assert 64_000 < context.budget.used_input_tokens < 256_000
        assert context.budget.reserved_output_tokens == 4_000
