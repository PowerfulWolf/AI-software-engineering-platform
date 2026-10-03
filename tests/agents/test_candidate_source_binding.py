"""Production factory must deliver the candidate view and gate the complete prompt."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_software_engineer.agents import AgentRunStatus, StoredContextResolver
from ai_software_engineer.agents.candidate_binding import (
    candidate_read_scope,
    validate_candidate_artifact_lineage,
)
from ai_software_engineer.agents.codex_cli import SubprocessCodexCommandRunner, _compile_prompt
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import ContextBudget, InMemoryContextStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.enums import QaReportStatus
from ai_software_engineer.git import WorkspacePolicyError
from ai_software_engineer.manager.production_delivery import ConfiguredDeliveryRouteAdapterFactory
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.recovery.verification_execution import VerificationEvidence
from tests.agents.test_candidate_review_source import repository
from tests.agents.test_codex_cli import _QaRunner
from tests.agents.test_openai_compatible import _request
from tests.domain.factories import (
    NOW,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_task,
)
from tests.manager.test_production_delivery import _config
from tests.orchestration.test_runner import _definitions


@pytest.mark.parametrize("budget", [128_000, 2_000])
@pytest.mark.parametrize("receipt", [False, True])
def test_factory_bounds_final_prompt_without_loading_unrelated_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: int, receipt: bool
) -> None:
    root, scope = repository(tmp_path)
    task = make_task().model_copy(update={"base_ref": scope.base_revision, "repository": str(root)})
    plan = make_plan_artifact()
    plan = seal_artifact(
        plan.model_copy(
            update={
                "source_revision": scope.base_revision,
                "content": plan.content.model_copy(
                    update={
                        "steps": (
                            plan.content.steps[0].model_copy(
                                update={"files": ("dependency.txt", "new.py")}
                            ),
                        )
                    }
                ),
            }
        ),
        validated_at=NOW,
    )
    implementation = make_implementation_artifact()
    implementation = seal_artifact(
        implementation.model_copy(
            update={
                "source_revision": scope.candidate_revision,
                "content": implementation.content.model_copy(
                    update={"commit_sha": scope.candidate_revision}
                ),
            }
        ),
        validated_at=NOW,
    )
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    artifacts.put(plan)
    artifacts.put(implementation)
    contexts = InMemoryContextStore()
    definition = _definitions()[AgentRole.QA]
    context = FileRunContextBuilder(
        root,
        context_store=contexts,
        budget=ContextBudget(max_input_tokens=budget, reserved_output_tokens=4000),
    ).build(
        task,
        definition,
        attempt=1,
        candidate_revision=scope.candidate_revision,
        input_artifacts=(plan, implementation),
    )
    request = _request(
        AgentRole.QA,
        source_revision=scope.candidate_revision,
        context_manifest_id=context.context_id,
    ).model_copy(
        update={
            "permissions": definition.permissions,
            "input_artifact_ids": (plan.artifact_id, implementation.artifact_id),
        }
    )
    runner = _QaRunner(request)
    prompts: list[str] = []

    def run(_self: object, *args: object, **kwargs: object) -> object:
        prompts.append(str(kwargs["stdin"]))
        return runner.run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SubprocessCodexCommandRunner, "run", run)
    binding = MagicMock()
    binding.worktree.path = root
    config = _config(tmp_path)
    factory = ConfiguredDeliveryRouteAdapterFactory()
    if receipt:
        provider = MagicMock()
        provider.evidence_for.return_value = VerificationEvidence(text="receipt data\n" * 50_000)
        factory = factory.with_verification_evidence(provider)
    adapter = factory.create(
        route=config.model_routes[0],
        definition=definition,
        binding=binding,
        context_resolver=StoredContextResolver(contexts, artifacts),
        config=config,
        environment={},
    )
    result = adapter.run(request)
    if budget == 128_000 and not receipt:
        assert result.status is AgentRunStatus.SUCCEEDED, result.error
        assert len(prompts) == 1
        assert "first change must remain visible" in prompts[0]
        assert "irrelevant baseline" not in prompts[0]
        assert "SOURCE_PACKAGE=" in prompts[0]
        assert runner.argv is not None and "read-only" in runner.argv
        assert "shell_tool" in runner.argv
        assert runner.argv[runner.argv.index("shell_tool") - 1] == "--disable"
    else:
        assert result.status is AgentRunStatus.FAILED
        assert not prompts
        assert result.error is not None and "budget" in result.error.message.lower()


@pytest.mark.parametrize("fault", ["task", "revision", "parent", "digest", "plan_base"])
def test_scope_refuses_false_task_lineage_and_integrity(tmp_path: Path, fault: str) -> None:
    _, scope = repository(tmp_path)
    task = make_task().model_copy(update={"base_ref": scope.base_revision})
    plan = seal_artifact(
        make_plan_artifact().model_copy(update={"source_revision": scope.base_revision}),
        validated_at=NOW,
    )
    implementation = make_implementation_artifact()
    implementation = implementation.model_copy(
        update={
            "source_revision": scope.candidate_revision,
            "content": implementation.content.model_copy(
                update={"commit_sha": scope.candidate_revision}
            ),
        }
    )
    if fault == "task":
        implementation = implementation.model_copy(update={"task_id": "task_other"})
    elif fault == "revision":
        implementation = implementation.model_copy(update={"source_revision": "e" * 40})
    elif fault == "parent":
        implementation = implementation.model_copy(update={"parent_artifact_ids": ("art_other",)})
    elif fault == "plan_base":
        plan = seal_artifact(
            plan.model_copy(update={"source_revision": "e" * 40}), validated_at=NOW
        )
    implementation = seal_artifact(implementation, validated_at=NOW)
    if fault == "digest":
        implementation = implementation.model_copy(update={"source_revision": "d" * 40})
    with pytest.raises(WorkspacePolicyError, match="differs"):
        candidate_read_scope(task, plan, implementation, scope.candidate_revision)


def test_scope_accepts_qa_remediation_candidate_lineage(tmp_path: Path) -> None:
    _, scope = repository(tmp_path)
    task = make_task().model_copy(update={"base_ref": scope.base_revision})
    source_plan = make_plan_artifact()
    plan = source_plan.model_copy(
        update={
            "task_id": task.id,
            "source_revision": scope.base_revision,
            "content": source_plan.content.model_copy(
                update={
                    "steps": tuple(
                        step.model_copy(update={"files": ("dependency.txt",)})
                        for step in source_plan.content.steps
                    )
                }
            ),
        }
    )
    plan = seal_artifact(plan, validated_at=NOW)
    previous = seal_artifact(
        make_implementation_artifact().model_copy(
            update={
                "task_id": task.id,
                "source_revision": "b" * 40,
                "content": make_implementation_artifact().content.model_copy(
                    update={"commit_sha": "b" * 40}
                ),
            }
        ),
        validated_at=NOW,
    )
    feedback = seal_artifact(
        make_qa_artifact().model_copy(
            update={
                "task_id": task.id,
                "source_revision": "b" * 40,
                "parent_artifact_ids": (previous.artifact_id,),
                "content": make_qa_artifact().content.model_copy(
                    update={"status": QaReportStatus.FAIL}
                ),
            }
        ),
        validated_at=NOW,
    )
    remediation = seal_artifact(
        make_implementation_artifact().model_copy(
            update={
                "artifact_id": "art_impl_remediation",
                "task_id": task.id,
                "source_revision": scope.candidate_revision,
                "parent_artifact_ids": (plan.artifact_id, feedback.artifact_id),
                "supersedes": previous.artifact_id,
                "content": make_implementation_artifact().content.model_copy(
                    update={"commit_sha": scope.candidate_revision}
                ),
            }
        ),
        validated_at=NOW,
    )
    artifacts = {item.artifact_id: item for item in (plan, previous, feedback, remediation)}

    validate_candidate_artifact_lineage(task, plan, remediation, artifacts)
    result = candidate_read_scope(task, plan, remediation, scope.candidate_revision)
    assert result.candidate_revision == scope.candidate_revision


def test_cli_structured_message_encoding_retains_all_fields() -> None:
    original = {
        "identity": {"task": "task_example"},
        "sections": [
            {"content": '"quote"\\backslash\n中文\nSOURCE_DIFF_END\n', "sha256": "e" * 64}
        ],
    }
    messages = [
        {"role": "system", "content": "exact machine policy"},
        {"role": "user", "content": json.dumps(original, ensure_ascii=False)},
        {"role": "user", "content": 'raw receipt data\n"quote"'},
    ]
    compiled = _compile_prompt(_request(AgentRole.QA), messages)
    encoded = json.loads(compiled.split("PROMPT_MESSAGES=", 1)[1])
    assert encoded[0] == messages[0]
    assert encoded[1]["content"] == original
    assert encoded[1]["content_format"] == "json"
    assert encoded[2] == messages[2]
