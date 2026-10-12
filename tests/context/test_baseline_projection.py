"""A preserved worktree needs complete evidence, not a second full patch prompt."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.context import ContextBudget, ContextSource, InMemoryContextStore
from ai_software_engineer.context.execution_baseline import (
    ExecutionBaselineContext,
    PreservedWorktreeBaselineContext,
    ReappliedBaselineReferenceContext,
    execution_baseline_from_context,
    parse_execution_baseline_context,
)
from ai_software_engineer.context.models import ContextBundle, ContextSection
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    ExecutionBaselineBinding,
)
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from ai_software_engineer.orchestration.execution_baseline import BaselineRunContextBuilder
from tests.agents.test_openai_compatible import _request
from tests.manager.test_execution_baseline import Setup, authorize, setup
from tests.orchestration.test_runner import _definitions


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_preserved_large_patch_is_verified_without_repeating_it_in_role_input(
    tmp_path: Path, role: AgentRole
) -> None:
    f = setup(tmp_path)
    source = f.worktree.path / "src/app.py"
    source.write_text(source.read_text() + "\nDATA = (\n" + "    '" + "x" * 400 + "'\n")
    with source.open("a") as stream:
        for _ in range(1300):
            stream.write("    '" + "x" * 400 + "'\n")
        stream.write(")\n")
    plan = f.service.propose(f.target)
    binding = f.service.execute(plan.plan_sha256, authority=authorize(plan))
    task = f.collector.facts.task
    before = source.read_bytes()
    resolver = StoredCoderExecutionInputResolver(f.service.store)
    complete = resolver.required_context(resolver.current(task, implementation=None, progress=None))
    assert complete is not None and len(complete) > 500_000
    context = BaselineRunContextBuilder(
        FileRunContextBuilder(
            f.repository,
            budget=ContextBudget(max_input_tokens=32_000, reserved_output_tokens=4000),
        ),
        InMemoryContextStore(),
        resolver,
    ).build(task, _definitions()[role], attempt=1)
    section = next(s for s in context.sections if s.name == "execution.baseline")
    wire = json.loads(section.content)
    assert wire["schema_version"] == "v2"
    assert "complete_patch" not in wire
    assert wire["retained_patch"] == binding.retained_patch.to_wire()
    assert wire["binding"] == binding.to_wire()
    assert len(section.content) < 10_000
    assert context.budget.used_input_tokens < 10_000
    assert source.read_bytes() == before


def _bound(
    tmp_path: Path, *, mode: BaselineInputMode = BaselineInputMode.PRESERVE_DRAFT
) -> tuple[Setup, ContextBundle, AgentRequest, StoredCoderExecutionInputResolver]:
    f = setup(tmp_path)
    plan = f.service.propose(f.target, input_mode=mode)
    binding = f.service.execute(plan.plan_sha256, authority=authorize(plan))
    resolver = StoredCoderExecutionInputResolver(f.service.store)
    task = f.collector.facts.task
    context = BaselineRunContextBuilder(
        FileRunContextBuilder(f.repository), InMemoryContextStore(), resolver
    ).build(
        task,
        _definitions()[AgentRole.CODER],
        attempt=1,
        candidate_revision=binding.execution_source_revision,
    )
    request = _request(
        AgentRole.CODER,
        source_revision=binding.execution_source_revision,
        context_manifest_id=context.context_id,
    ).model_copy(
        update={
            "task_id": task.id,
            "execution_baseline_sha256": binding.binding_sha256,
            "execution_base_ref": binding.execution_base_ref,
        }
    )
    return f, context, request, resolver


def _replace_body(context: ContextBundle, content: str) -> ContextBundle:
    original = next(s for s in context.sections if s.name == "execution.baseline")
    section = original.model_copy(
        update={
            "content": content,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "tokens": (len(content) + 3) // 4,
        }
    )
    sections = tuple(section if s == original else s for s in context.sections)
    updated = context.model_copy(
        update={
            "sections": sections,
            "budget": context.budget.model_copy(
                update={"used_input_tokens": sum(s.tokens for s in sections)}
            ),
        }
    )
    payload = updated.model_dump(mode="json", exclude={"context_id", "built_at"})
    sha = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return updated.model_copy(update={"context_id": "ctx_" + sha})


@pytest.mark.parametrize("missing", ["baseline-plans", "baseline-authorities", "baseline-starts"])
def test_v2_requires_complete_evidence_verifier(tmp_path: Path, missing: str) -> None:
    f, context, request, resolver = _bound(tmp_path)
    task = f.collector.facts.task
    with pytest.raises(ValueError, match="完整执行基线证据"):
        execution_baseline_from_context(context, request, task)
    assert execution_baseline_from_context(context, request, task, verifier=resolver) is not None
    record = next(f.service.store.root.glob(missing + "-*.json"))
    record.unlink()
    with pytest.raises((ValueError, RuntimeError)):
        execution_baseline_from_context(context, request, task, verifier=resolver)
    # A freshly created projection cannot hide a missing immutable full body.
    with pytest.raises((ValueError, RuntimeError)):
        BaselineRunContextBuilder(
            FileRunContextBuilder(f.repository), InMemoryContextStore(), resolver
        ).build(task, _definitions()[AgentRole.CODER], attempt=1)


def test_v2_refuses_corrupted_retained_patch_even_with_valid_outer_record_digest(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.knowledge.models import digest

    f, context, request, resolver = _bound(tmp_path)
    path = next(f.service.store.root.glob("baseline-plans-*.json"))
    envelope = json.loads(path.read_text())
    envelope["record"]["complete_capture"]["patch"] += "unexpected mutation\n"
    envelope["sha256"] = digest(envelope["record"])
    path.write_text(json.dumps(envelope))
    with pytest.raises((ValueError, RuntimeError)):
        execution_baseline_from_context(context, request, f.collector.facts.task, verifier=resolver)


@pytest.mark.parametrize("field", ["context_id", "task_id", "role", "attempt", "source_revision"])
def test_projection_matches_the_exact_role_request(tmp_path: Path, field: str) -> None:
    f, context, request, resolver = _bound(tmp_path)
    changes = {
        "context_id": "ctx_" + "a" * 64,
        "task_id": "task_foreign",
        "role": AgentRole.QA,
        "attempt": 2,
        "source_revision": "a" * 40,
    }
    changed = context.model_copy(update={field: changes[field]})
    with pytest.raises(ValueError, match="角色请求身份"):
        execution_baseline_from_context(changed, request, f.collector.facts.task, verifier=resolver)


@pytest.mark.parametrize("fault", ["reference", "foreign_task", "stale_binding", "reapply_mode"])
def test_projection_cannot_replace_full_evidence_or_change_source_authority(
    tmp_path: Path, fault: str
) -> None:
    f, context, request, resolver = _bound(tmp_path)
    section = next(s for s in context.sections if s.name == "execution.baseline")
    wire = json.loads(section.content)
    if fault == "reference":
        wire["retained_patch"]["sha256"] = "f" * 64
    else:
        binding_values = wire["binding"]
        binding_values.pop("binding_sha256")
        if fault == "foreign_task":
            binding_values["task_id"] = "task_foreign"
        elif fault == "stale_binding":
            binding_values["previous_binding_sha256"] = request.execution_baseline_sha256
            binding_values["sequence"] = 2
        else:
            binding_values["input_mode"] = "coder_reapply"
            binding_values["execution_source_revision"] = binding_values["execution_base_ref"]
        binding = ExecutionBaselineBinding.create(**binding_values)
        wire["binding"] = binding.to_wire()
        request = request.model_copy(update={"execution_baseline_sha256": binding.binding_sha256})
        section = section.model_copy(update={"uri": "baseline://" + binding.binding_sha256})
        context = context.model_copy(
            update={
                "sections": tuple(
                    section if s.name == "execution.baseline" else s for s in context.sections
                )
            }
        )
    changed = _replace_body(context, json.dumps(wire, ensure_ascii=False, sort_keys=True))
    request = request.model_copy(update={"context_manifest_id": changed.context_id})
    with pytest.raises(ValueError):
        execution_baseline_from_context(changed, request, f.collector.facts.task, verifier=resolver)


def test_coder_reapply_keeps_complete_old_patch(tmp_path: Path) -> None:
    f, context, request, resolver = _bound(tmp_path, mode=BaselineInputMode.CODER_REAPPLY)
    section = next(s for s in context.sections if s.name == "execution.baseline")
    value = parse_execution_baseline_context(section.content)
    assert isinstance(value, ExecutionBaselineContext)
    assert "VALUE = 2" in value.complete_patch and "EXTRA = 3" in value.complete_patch
    assert (
        hashlib.sha256(value.complete_patch.encode()).hexdigest()
        == value.binding.retained_patch.sha256
    )
    assert (
        execution_baseline_from_context(context, request, f.collector.facts.task, verifier=resolver)
        == value.binding
    )


def test_historical_v1_reapply_stays_unchanged_with_matching_recovery_patch(tmp_path: Path) -> None:
    f, context, request, resolver = _bound(tmp_path, mode=BaselineInputMode.CODER_REAPPLY)
    baseline = next(s for s in context.sections if s.name == "execution.baseline")
    value = parse_execution_baseline_context(baseline.content)
    assert isinstance(value, ExecutionBaselineContext)
    patch = ContextSection(
        name="source:recovery.patch",
        uri="recovery://fixture/patch/capture",
        content=value.complete_patch,
        sha256=value.binding.retained_patch.sha256,
        tokens=(len(value.complete_patch) + 3) // 4,
        priority=11,
    )
    historical = _replace_body(
        context.model_copy(update={"sections": (*context.sections, patch)}), baseline.content
    )
    before = historical.to_wire()
    checked = BaselineRunContextBuilder(
        SimpleNamespace(build=lambda *args, **kwargs: historical),
        InMemoryContextStore(),
        resolver,
    ).build(
        f.collector.facts.task,
        _definitions()[AgentRole.CODER],
        attempt=1,
    )
    assert checked.to_wire() == before
    assert (
        execution_baseline_from_context(
            checked,
            request.model_copy(update={"context_manifest_id": checked.context_id}),
            f.collector.facts.task,
            verifier=resolver,
        )
        == value.binding
    )


def test_coder_reapply_deduplicates_complete_patch_when_recovery_source_is_present(
    tmp_path: Path,
) -> None:
    """The recovery patch remains complete, while baseline carries only its typed binding."""
    f = setup(tmp_path)
    source = f.worktree.path / "src/app.py"
    source.write_text(source.read_text() + "\nDATA = (\n" + "    '" + "x" * 400 + "'\n")
    with source.open("a") as stream:
        for _ in range(1300):
            stream.write("    '" + "x" * 400 + "'\n")
        stream.write(")\n")
    plan = f.service.propose(f.target, input_mode=BaselineInputMode.CODER_REAPPLY)
    binding = f.service.execute(plan.plan_sha256, authority=authorize(plan))
    task = f.collector.facts.task
    resolver = StoredCoderExecutionInputResolver(f.service.store)
    complete = resolver.required_context(resolver.current(task, implementation=None, progress=None))
    assert complete is not None and len(complete) > 500_000
    patch = complete.split("完整旧补丁:\n", 1)[1]
    recovery = ContextSource(
        source_id="recovery.patch",
        uri="recovery://fixture/patch/capture",
        content=patch,
        roles=(AgentRole.CODER,),
        required=True,
        priority=11,
    )
    contexts = InMemoryContextStore()
    context = BaselineRunContextBuilder(
        FileRunContextBuilder(
            f.repository,
            sources=(recovery,),
            budget=ContextBudget(max_input_tokens=256_000, reserved_output_tokens=4_000),
        ),
        contexts,
        resolver,
    ).build(
        task,
        _definitions()[AgentRole.CODER],
        attempt=1,
        candidate_revision=binding.execution_source_revision,
    )
    baseline = next(item for item in context.sections if item.name == "execution.baseline")
    value = parse_execution_baseline_context(baseline.content)
    assert isinstance(value, ReappliedBaselineReferenceContext)
    patch_section = next(item for item in context.sections if item.name == "source:recovery.patch")
    assert patch_section.content == patch
    assert value.complete_patch_uri == patch_section.uri
    assert "\"complete_patch\":" not in baseline.content
    # The one full body fits the production budget; two copies would not.
    assert context.budget.used_input_tokens < 256_000
    request = _request(
        AgentRole.CODER,
        source_revision=binding.execution_source_revision,
        context_manifest_id=context.context_id,
    ).model_copy(
        update={
            "task_id": task.id,
            "execution_baseline_sha256": binding.binding_sha256,
            "execution_base_ref": binding.execution_base_ref,
        }
    )
    assert (
        execution_baseline_from_context(context, request, task, verifier=resolver)
        == binding
    )

    missing = context.model_copy(
        update={
            "sections": tuple(
                item for item in context.sections if item.name != "source:recovery.patch"
            )
        }
    )
    with pytest.raises(ValueError, match=r"recovery\.patch"):
        execution_baseline_from_context(
            missing,
            request.model_copy(update={"context_manifest_id": missing.context_id}),
            task,
            verifier=resolver,
        )
    changed = patch_section.model_copy(update={"content": patch + "changed"})
    changed_context = context.model_copy(
        update={
            "sections": tuple(
                changed if item == patch_section else item for item in context.sections
            )
        }
    )
    with pytest.raises(ValueError):
        execution_baseline_from_context(
            changed_context,
            request.model_copy(update={"context_manifest_id": changed_context.context_id}),
            task,
            verifier=resolver,
        )


def test_historical_v1_body_and_finalized_context_stay_unchanged(tmp_path: Path) -> None:
    f, context, request, resolver = _bound(tmp_path)
    source = resolver.current(f.collector.facts.task, implementation=None, progress=None)
    assert source.baseline is not None
    body = resolver.required_context(source)
    assert body is not None
    content = json.dumps(
        ExecutionBaselineContext.from_required_context(source.baseline, body).to_wire(),
        ensure_ascii=False,
        sort_keys=True,
    )
    historical = _replace_body(context, content)
    request = request.model_copy(update={"context_manifest_id": historical.context_id})
    before = historical.to_wire()
    assert (
        execution_baseline_from_context(historical, request, f.collector.facts.task)
        == source.baseline
    )
    assert isinstance(parse_execution_baseline_context(content), ExecutionBaselineContext)
    checked = BaselineRunContextBuilder(
        SimpleNamespace(build=lambda *args, **kwargs: historical),
        InMemoryContextStore(),
        resolver,
    ).build(f.collector.facts.task, _definitions()[AgentRole.CODER], attempt=1)
    assert checked.to_wire() == before
    assert not isinstance(
        parse_execution_baseline_context(content), PreservedWorktreeBaselineContext
    )
