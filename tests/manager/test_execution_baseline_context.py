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
from ai_software_engineer.context.ports import ContextSourceError
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.git import WorkspacePolicyError
from ai_software_engineer.knowledge.runtime import append_knowledge_context
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from ai_software_engineer.orchestration.execution_baseline import BaselineRunContextBuilder
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
def test_baseline_required_context_is_full_for_all_delivery_roles(
    tmp_path: Path, role: AgentRole
) -> None:
    f = setup(tmp_path)
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
