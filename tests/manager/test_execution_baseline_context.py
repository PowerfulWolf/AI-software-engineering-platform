"""Verifier baseline Context uses the new engineering base and same candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.agents import StoredContextResolver
from ai_software_engineer.agents.candidate_binding import BoundCandidateSource, candidate_read_scope
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import ContextBudget, InMemoryContextStore
from ai_software_engineer.context.execution_baseline import execution_baseline_from_context
from ai_software_engineer.context.models import ContextSource
from ai_software_engineer.context.native import (
    execution_native_rule_sources,
    native_rule_prompt_sources,
)
from ai_software_engineer.context.ports import ContextSourceError
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.execution_baseline import (
    CoderExecutionInput,
    ExecutionBaselineBinding,
)
from ai_software_engineer.git import WorkspacePolicyError
from ai_software_engineer.knowledge.runtime import append_knowledge_context
from ai_software_engineer.manager.baseline_native_rules import (
    build_native_rule_change,
    load_native_rule_epoch,
)
from ai_software_engineer.manager.baseline_production import native_rules_at_revision
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from ai_software_engineer.orchestration.execution_baseline import BaselineRunContextBuilder
from ai_software_engineer.repository_profile import RepositoryProfile
from tests.agents.test_candidate_review_source import source_payload
from tests.agents.test_openai_compatible import _request
from tests.domain.factories import (
    NOW,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
)
from tests.git.test_worktree import _git
from tests.manager.test_execution_baseline import authorize, setup
from tests.orchestration.test_runner import _definitions


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
@pytest.mark.parametrize("knowledge_projection", [False, True])
def test_all_role_contexts_use_exact_native_epoch_before_consultation(
    tmp_path: Path, role: AgentRole, knowledge_projection: bool
) -> None:
    from ai_software_engineer.knowledge.context import snapshot_from_sources
    from ai_software_engineer.knowledge.models import digest

    f = setup(tmp_path)
    facts = f.collector.facts.model_copy(
        update={
            "scope": f.collector.facts.scope.model_copy(
                update={"repository_id": "repository_fixture"}
            )
        }
    )
    f.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    plan = f.service.propose(f.target)
    original_binding = f.service.execute(plan.plan_sha256, authority=authorize(plan))
    task = f.collector.facts.task
    scope = f.collector.facts.scope
    original_rules = native_rules_at_revision(
        f.manager, repository_id=scope.repository_id, revision=task.base_ref
    )
    target_rules = native_rules_at_revision(
        f.manager, repository_id=scope.repository_id, revision=f.target
    )
    change = build_native_rule_change(
        git=f.manager,
        records=f.service.store.records,
        scope=scope,
        task_id=task.id,
        source_revision=task.base_ref,
        target_base_ref=f.target,
        source_rules=original_rules,
        target_rules=target_rules,
    )
    assert change is not None
    epoch = load_native_rule_epoch(f.service.store.records, change.target.epoch_sha256)
    values = original_binding.to_wire()
    values.pop("binding_sha256")
    values["native_rule_epoch_sha256"] = epoch.epoch_sha256
    binding = ExecutionBaselineBinding.create(**values)
    source = CoderExecutionInput(
        source_revision=binding.execution_source_revision,
        execution_base_ref=binding.execution_base_ref,
        active_progress=None,
        baseline=binding,
    )
    resolver = SimpleNamespace(
        current=lambda *args, **kwargs: source,
        required_context=lambda *args: f.service.store.required_context(original_binding),
        native_rule_epoch=lambda *args: epoch,
    )
    frozen_sources = execution_native_rule_sources(
        tuple(
            ContextSource(
                source_id=f"native.rule.{index}",
                uri=body.source.uri,
                content=body.content,
                required=True,
            )
            for index, body in enumerate(epoch.before_bodies)
        ),
        epoch,
        profile=RepositoryProfile.discover(f.repository, repository_id=scope.repository_id),
    )
    snapshot = snapshot_from_sources(
        team_id=scope.team_id,
        project_id=scope.project_id,
        requirement_id=task.id,
        repository_ids=(scope.repository_id,),
        sources=tuple((scope.repository_id, item) for item in frozen_sources),
    )
    assert any("updated main prerequisite" in document.content for document in snapshot.documents)
    contexts = InMemoryContextStore()
    delegate = FileRunContextBuilder(
        f.repository,
        sources=native_rule_prompt_sources(frozen_sources)
        if knowledge_projection
        else frozen_sources,
        context_store=contexts,
        budget=ContextBudget(max_input_tokens=128000, reserved_output_tokens=4000),
    )
    context = BaselineRunContextBuilder(
        delegate, contexts, resolver, native_sources=frozen_sources
    ).build(task, _definitions()[role], attempt=1)
    marker = next(
        section for section in context.sections if section.name == "source:execution.native_rules"
    )
    assert epoch.epoch_sha256 in marker.content
    native_sections = tuple(
        section
        for section in context.sections
        if section.name.startswith(("source:native.rule.", "source:native.reference."))
    )
    assert len(native_sections) == len(epoch.bodies)
    finalized = append_knowledge_context(
        context,
        contexts,
        name="knowledge.consultation",
        uri="knowledge://native-epoch-fixture-finalized",
        content='{"fixture":"consulted current native rules"}',
    )
    assert (
        BaselineRunContextBuilder(
            SimpleNamespace(build=lambda *args, **kwargs: finalized), contexts, resolver
        ).build(task, _definitions()[role], attempt=1)
        == finalized
    )
    dropped = finalized.model_copy(
        update={
            "sections": tuple(
                section for section in finalized.sections if section not in native_sections
            )
        }
    )
    with pytest.raises(ContextSourceError, match="完整目标"):
        BaselineRunContextBuilder(
            SimpleNamespace(build=lambda *args, **kwargs: dropped),
            contexts,
            resolver,
            native_sources=frozen_sources,
        ).build(task, _definitions()[role], attempt=1)
    old = epoch.before_bodies[0].content
    victim = native_sections[0]
    changed = victim.model_copy(
        update={"content": old, "sha256": hashlib.sha256(old.encode()).hexdigest()}
    )
    tampered = finalized.model_copy(
        update={
            "sections": tuple(
                changed if section == victim else section for section in finalized.sections
            )
        }
    )
    with pytest.raises(ContextSourceError, match="正文"):
        BaselineRunContextBuilder(
            SimpleNamespace(build=lambda *args, **kwargs: tampered), contexts, resolver
        ).build(task, _definitions()[role], attempt=1)


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_baseline_required_context_is_full_for_all_delivery_roles(
    tmp_path: Path, role: AgentRole
) -> None:
    f = setup(tmp_path)
    # These are source references, not literal credentials. The complete
    # retained draft must survive capture, plan persistence, replay, and the
    # required Context guard for each independent delivery role.
    source = f.worktree.path / "src/app.py"
    source.write_text(
        source.read_text()
        + "\ndef connect(settings, foreign):\n"
        + '    secret = foreign / "secret.json"\n'
        + "    return client(password=settings.password, path=secret)\n"
    )
    baseline_plan = f.service.propose(f.target)
    binding = f.service.execute(baseline_plan.plan_sha256, authority=authorize(baseline_plan))
    task = f.collector.facts.task
    # Independent test fixture represents the new admitted Coder candidate.
    _git(f.worktree.path, "add", "src/app.py")
    _git(f.worktree.path, "commit", "-m", "new admitted candidate")
    candidate = _git(f.worktree.path, "rev-parse", "HEAD")
    original_plan = make_plan_artifact()
    plan = seal_artifact(
        original_plan.model_copy(
            update={
                "task_id": task.id,
                "source_revision": task.base_ref,
                "content": original_plan.content.model_copy(
                    update={
                        "steps": tuple(
                            step.model_copy(update={"files": ("src/app.py",)})
                            for step in original_plan.content.steps
                        )
                    }
                ),
            }
        ),
        validated_at=NOW,
    )
    original_implementation = make_implementation_artifact()
    implementation = seal_artifact(
        original_implementation.model_copy(
            update={
                "task_id": task.id,
                "source_revision": candidate,
                "parent_artifact_ids": (plan.artifact_id,),
                "content": original_implementation.content.model_copy(
                    update={"commit_sha": candidate}
                ),
            }
        ),
        validated_at=NOW,
    )
    qa = seal_artifact(
        make_qa_artifact().model_copy(
            update={
                "task_id": task.id,
                "source_revision": candidate,
                "parent_artifact_ids": (implementation.artifact_id,),
            }
        ),
        validated_at=NOW,
    )
    artifacts = FileArtifactStore(tmp_path / "context-artifacts")
    for artifact in (plan, implementation, qa):
        artifacts.put(artifact)
    inputs = (
        (plan,)
        if role is AgentRole.CODER
        else ((plan, implementation) if role is AgentRole.QA else (plan, implementation, qa))
    )
    contexts = InMemoryContextStore()
    resolver = StoredCoderExecutionInputResolver(f.service.store)
    context = BaselineRunContextBuilder(
        FileRunContextBuilder(
            f.repository, budget=ContextBudget(max_input_tokens=128000, reserved_output_tokens=4000)
        ),
        contexts,
        resolver,
    ).build(
        task, _definitions()[role], attempt=1, candidate_revision=candidate, input_artifacts=inputs
    )
    request = _request(
        role, source_revision=candidate, context_manifest_id=context.context_id
    ).model_copy(
        update={
            "task_id": task.id,
            "input_artifact_ids": tuple(artifact.artifact_id for artifact in inputs),
            "execution_baseline_sha256": binding.binding_sha256,
            "execution_base_ref": binding.execution_base_ref,
            "permissions": _definitions()[role].permissions,
        }
    )
    type(request).model_validate(request.to_wire())
    assert execution_baseline_from_context(context, request, task) == binding
    section = next(section for section in context.sections if section.name == "execution.baseline")
    assert "VALUE = 2" in section.content and "EXTRA = 3" in section.content
    assert "password=settings.password" in section.content
    assert 'secret = foreign / \\"secret.json\\"' in section.content
    assert not section.truncated
    assert task.base_ref != binding.execution_base_ref and plan.source_revision == task.base_ref
    finalized = append_knowledge_context(
        context,
        contexts,
        name="knowledge.consultation",
        uri="knowledge://fixture-finalized",
        content='{"fixture":"sealed consultation"}',
    )
    verified = BaselineRunContextBuilder(
        SimpleNamespace(build=lambda *args, **kwargs: finalized),
        contexts,
        resolver,
    ).build(
        task,
        _definitions()[role],
        attempt=1,
        candidate_revision=candidate,
        input_artifacts=inputs,
    )
    assert verified == finalized
    assert verified.context_id != context.context_id
    assert verified.sections[-1].name == "knowledge.consultation"
    assert sum(s.name == "execution.baseline" for s in verified.sections) == 1
    if role is not AgentRole.CODER:
        snapshot = BoundCandidateSource(StoredContextResolver(contexts, artifacts)).append(
            request, f.worktree.path, "prompt"
        )
        payload = source_payload(snapshot.removeprefix("prompt"))
        assert payload["base_revision"] == binding.execution_base_ref
        assert payload["candidate_revision"] == candidate
        diff = payload["diff"]
        assert isinstance(diff, str)
        assert "updated main prerequisite" not in diff
        assert "src/app.py" in diff and "EXTRA = 3" in diff
        # The original approved Task/Plan base still denotes the product intent.
        assert (
            candidate_read_scope(task, plan, implementation, candidate).base_revision
            == task.base_ref
        )
        assert (
            candidate_read_scope(
                task, plan, implementation, candidate, execution_baseline=binding
            ).base_revision
            == binding.execution_base_ref
        )
        for bad_request in (
            request.model_copy(update={"execution_baseline_sha256": "e" * 64}),
            request.model_copy(update={"execution_base_ref": task.base_ref}),
            request.model_copy(
                update={"execution_baseline_sha256": None, "execution_base_ref": None}
            ),
        ):
            with pytest.raises(WorkspacePolicyError, match="baseline"):
                BoundCandidateSource(StoredContextResolver(contexts, artifacts)).append(
                    bad_request, f.worktree.path, "prompt"
                )
    changed = json.loads(section.content)
    changed["complete_patch"] += "unexpected extra mutation\n"
    content = json.dumps(changed)
    bad_section = section.model_copy(
        update={"content": content, "sha256": hashlib.sha256(content.encode()).hexdigest()}
    )
    bad_context = context.model_copy(
        update={
            "sections": tuple(
                bad_section if original.name == "execution.baseline" else original
                for original in context.sections
            )
        }
    )
    with pytest.raises(ValueError, match="补丁"):
        execution_baseline_from_context(bad_context, request, task)
    with pytest.raises(ContextSourceError, match="完整输入不一致"):
        BaselineRunContextBuilder(
            SimpleNamespace(build=lambda *args, **kwargs: bad_context),
            contexts,
            resolver,
        ).build(
            task,
            _definitions()[role],
            attempt=1,
            candidate_revision=candidate,
            input_artifacts=inputs,
        )
