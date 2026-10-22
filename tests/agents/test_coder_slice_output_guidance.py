"""Actual prompt and native acceptance seams preserve a frozen Coder slice."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentRunStatus,
    CodexCliAgentAdapter,
    CodexInvocationResult,
    ContextPromptBuilder,
    RequestPromptBuilder,
)
from ai_software_engineer.context import ContextBudget, ContextBundle, ContextSection
from ai_software_engineer.domain import (
    AgentRole,
    ChangedFile,
    ChangeType,
    ImplementationReportArtifact,
    ImplementationTestStatus,
)
from ai_software_engineer.domain.artifact import Artifact
from ai_software_engineer.domain.execution_window import CoderWorkSlice, PlanExecutionWindow
from tests.agents.test_codex_cli import _ArtifactOutputRunner, _git, _repository
from tests.agents.test_openai_compatible import RecordingContextResolver, _align, _request
from tests.domain.factories import (
    NOW,
    make_coder_progress_artifact,
    make_implementation_artifact,
    make_plan_artifact,
)

_MARKER = "CODER_WORK_SLICE_GUIDANCE:"
_VERIFICATION_MARKER = "CODER_VERIFICATION_BOUNDARY:"


def _slice_request(base: str = "b" * 40, *, deferred: bool = True) -> AgentRequest:
    request = _request(AgentRole.CODER, source_revision=base)
    work = CoderWorkSlice(
        task_id=request.task_id,
        attempt=request.attempt,
        source_revision=request.source_revision,
        plan_artifact_id="art_plan_001",
        plan_sha256="c" * 64,
        window=PlanExecutionWindow.for_seconds(request.timeout_seconds),
        authorized_work_remaining=3,
        completed_step_ids=("step_prior",),
        selected_step_ids=("step_now", "step_next"),
        later_step_ids=("step_later",) if deferred else (),
    )
    return AgentRequest.model_validate(
        {**request.to_wire(), "input_artifact_ids": [work.plan_artifact_id], "work_slice": work}
    )


def _context_builder(request: AgentRequest) -> ContextPromptBuilder:
    plan = _align(make_plan_artifact(), request)
    context = ContextBundle(
        context_id=request.context_manifest_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        sections=(
            ContextSection(
                name="policy",
                uri="policy://permissions",
                sha256="a" * 64,
                tokens=1,
                content=json.dumps(request.permissions.to_wire()),
                priority=0,
            ),
            ContextSection(
                name="plan",
                uri=f"artifact://{plan.artifact_id}",
                sha256="b" * 64,
                tokens=1,
                content=plan.model_dump_json(),
                priority=30,
            ),
        ),
        budget=ContextBudget(max_input_tokens=10, reserved_output_tokens=2, used_input_tokens=2),
        built_at=NOW,
    )
    return ContextPromptBuilder(RecordingContextResolver(context, plan))


def _output(
    request: AgentRequest,
    *,
    implementation: bool = False,
    completed: tuple[str, ...] = ("step_prior", "step_now"),
    remaining: tuple[str, ...] = ("step_next", "step_later"),
) -> Artifact:
    artifact = _align(
        make_implementation_artifact() if implementation else make_coder_progress_artifact(),
        request,
    )
    content = artifact.content.to_wire()
    content["changed_files"] = [
        ChangedFile(
            path="src/change.py", change=ChangeType.ADDED, lines_added=1, lines_deleted=0
        ).to_wire()
    ]
    if implementation:
        content["commit_sha"] = request.source_revision
    else:
        content["checkpoint_sequence"] = request.attempt
        content["summary"] = "private-output-text-must-not-be-diagnostic"
        content["completed_step_ids"] = list(completed)
        content["remaining_step_ids"] = list(remaining)
    return type(artifact).model_validate(
        {
            **artifact.to_wire(),
            "parent_artifact_ids": list(request.input_artifact_ids),
            "content": content,
        }
    )


class _DraftOutputRunner(_ArtifactOutputRunner):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        target = cwd / "src/change.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")
        return super().run(
            argv, cwd=cwd, environment=environment, stdin=stdin, timeout_seconds=timeout_seconds
        )


@pytest.mark.parametrize("builder", ["request", "context", "native"])
@pytest.mark.parametrize("deferred", [True, False])
def test_prompt_explains_exact_inherited_selected_and_deferred_output_contract(
    tmp_path: Path, builder: str, deferred: bool
) -> None:
    root, base = _repository(tmp_path)
    request = _slice_request(base, deferred=deferred)
    prompt_builder = _context_builder(request) if builder == "context" else RequestPromptBuilder()
    if builder == "native":
        runner = _DraftOutputRunner(
            _output(
                request, remaining=("step_next", "step_later") if deferred else ("step_next",)
            ).to_wire()
        )
        result = CodexCliAgentAdapter(
            workspace_root=root,
            model="test-model",
            agent_id="agent_coder_001",
            agent_version="v0.1",
            prompt_builder=prompt_builder,
            runner=runner,
        ).run(request)
        assert result.status is AgentRunStatus.SUCCEEDED
        text = runner.prompt
    else:
        prompt = prompt_builder.build(request)
        text = prompt.messages[0].content
        assert _MARKER not in prompt.messages[1].content
        assert request.work_slice is not None
        assert json.loads(prompt.messages[1].content)["work_slice"] == request.work_slice.to_wire()
    assert text.count(_MARKER) == 1
    for rule in (
        "work_slice.completed_step_ids are inherited completed steps",
        "Newly completed steps must come only from work_slice.selected_step_ids",
        "Keep every work_slice.later_step_ids entry in content.remaining_step_ids",
        "unfinished selected steps must also remain",
        "partition the complete approved step set",
        "Existing files or a recovered draft do not prove deferred steps complete",
    ):
        assert rule in text
    if deferred:
        assert "This slice has deferred steps: return coder-progress" in text
        assert "Do not return implementation-report for this slice" in text
    else:
        assert "This slice has no deferred steps" in text
        assert "implementation-report only after the complete implementation" in text


@pytest.mark.parametrize("builder", ["request", "context"])
@pytest.mark.parametrize("role", list(AgentRole))
def test_legacy_requests_receive_no_invented_slice_instructions(
    builder: str, role: AgentRole
) -> None:
    request = _request(role)
    prompt = (_context_builder(request) if builder == "context" else RequestPromptBuilder()).build(
        request
    )
    assert _MARKER not in prompt.messages[0].content
    assert json.loads(prompt.messages[1].content)["work_slice"] is None


@pytest.mark.parametrize(
    ("implementation", "completed", "remaining", "rule"),
    [
        (True, (), (), "PARTIAL_CANDIDATE"),
        (False, ("step_prior", "step_now", "step_later"), ("step_next",), "UNSELECTED_COMPLETION"),
        (False, ("step_now",), ("step_prior", "step_next", "step_later"), "PRIOR_COMPLETION"),
        (False, ("step_prior", "step_now"), ("step_next",), "STEP_PARTITION"),
    ],
)
def test_actual_native_slice_rejection_retains_draft_and_reports_only_fixed_subcause(
    tmp_path: Path,
    implementation: bool,
    completed: tuple[str, ...],
    remaining: tuple[str, ...],
    rule: str,
) -> None:
    root, base = _repository(tmp_path)
    request = _slice_request(base)
    runner = _DraftOutputRunner(
        _output(
            request, implementation=implementation, completed=completed, remaining=remaining
        ).to_wire()
    )
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="test-model",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
    ).run(request)
    assert result.status is AgentRunStatus.FAILED
    assert result.artifact is None
    assert result.error is not None and result.error.code is AgentErrorCode.INVALID_OUTPUT
    assert result.error.transient is False
    assert "cause=WORK_SLICE;" in result.error.message
    assert f"validation_rule={rule}" in result.error.message
    explanations = {
        "PARTIAL_CANDIDATE": "本轮仍有后续步骤。只能保存开发进度。完整候选未接纳",
        "UNSELECTED_COMPLETION": "本轮仅能完成选定步骤。后续步骤必须保留为待完成",
        "PRIOR_COMPLETION": "开发进度不能撤回此前已完成的步骤",
        "STEP_PARTITION": "开发进度未完整列出已完成和待完成步骤。未接纳本次报告",
    }
    assert explanations[rule] in result.error.message
    assert "cause=GIT_CONTRACT" not in result.error.message
    assert hashlib.sha256(runner.raw_output.encode()).hexdigest() in result.error.message
    assert f"output_bytes={len(runner.raw_output.encode())}" in result.error.message
    assert "private-output-text-must-not-be-diagnostic" not in result.error.message
    assert "step_later" not in result.error.message
    assert _git(root, "rev-parse", "HEAD") == base
    assert _git(root, "rev-list", "--count", "HEAD") == "1"
    assert (root / "src/change.py").read_text() == "VALUE = 1\n"


def test_last_slice_can_finish_through_original_candidate_gate(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request = _slice_request(base, deferred=False)
    runner = _DraftOutputRunner(_output(request, implementation=True).to_wire())
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="test-model",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
    ).run(request)
    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None and result.artifact.kind.value == "implementation-report"
    assert result.artifact.source_revision == _git(root, "rev-parse", "HEAD") != base
    assert _git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("builder", ["request", "context", "native"])
@pytest.mark.parametrize("sliced", [True, False])
def test_coder_prompt_distinguishes_independent_verification_from_implementation(
    tmp_path: Path, builder: str, sliced: bool
) -> None:
    root, base = _repository(tmp_path)
    request = _slice_request(base, deferred=False) if sliced else _request(AgentRole.CODER)
    original_request = request.to_wire()
    prompt_builder = _context_builder(request) if builder == "context" else RequestPromptBuilder()
    if builder == "native":
        request = request.model_copy(update={"source_revision": base})
        original_request = request.to_wire()
        runner = _DraftOutputRunner(_output(request, implementation=True).to_wire())
        result = CodexCliAgentAdapter(
            workspace_root=root,
            model="test-model",
            agent_id="agent_coder_001",
            agent_version="v0.1",
            prompt_builder=prompt_builder,
            runner=runner,
        ).run(request)
        assert result.status is AgentRunStatus.SUCCEEDED
        text = runner.prompt
    else:
        prompt = prompt_builder.build(request)
        text = prompt.messages[0].content
        assert _VERIFICATION_MARKER not in prompt.messages[1].content
    assert text.count(_VERIFICATION_MARKER) == 1
    for rule in (
        "verification assigned to independent QA/Reviewer",
        "continue other authorized implementation and test-code work",
        "Record unexecuted checks as NOT_RUN",
        "explicit Coder obligations and genuine implementation dependencies",
        "do not mark incomplete steps complete",
        "original candidate, independent QA and Review gates",
    ):
        assert rule in text
    assert request.to_wire() == original_request
    if sliced:
        assert "complete implementation and required Coder verification" in text
        assert "complete implementation and required verification have finished" not in text


@pytest.mark.parametrize("builder", ["request", "context"])
@pytest.mark.parametrize("role", [AgentRole.ORCHESTRATOR, AgentRole.QA, AgentRole.REVIEWER])
def test_other_roles_do_not_receive_coder_verification_boundary(
    builder: str, role: AgentRole
) -> None:
    request = _request(role)
    prompt = (_context_builder(request) if builder == "context" else RequestPromptBuilder()).build(
        request
    )
    assert _VERIFICATION_MARKER not in prompt.messages[0].content


def test_native_candidate_retains_not_run_without_promoting_it_to_verdict(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request = _slice_request(base, deferred=False)
    artifact = _output(request, implementation=True)
    assert isinstance(artifact, ImplementationReportArtifact)
    artifact = artifact.model_copy(
        update={
            "content": artifact.content.model_copy(
                update={
                    "tests_run": tuple(
                        test.model_copy(update={"status": ImplementationTestStatus.NOT_RUN})
                        for test in artifact.content.tests_run
                    ),
                    "known_risks": (
                        "Independent SQL verification needs the registered QA executor.",
                    ),
                }
            )
        }
    )
    runner = _DraftOutputRunner(artifact.to_wire())
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="test-model",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
    ).run(request)
    assert result.status is AgentRunStatus.SUCCEEDED
    assert isinstance(result.artifact, ImplementationReportArtifact)
    assert result.artifact.content.tests_run == artifact.content.tests_run
    assert result.artifact.content.known_risks == artifact.content.known_risks
    assert result.artifact.evidence == artifact.evidence
    assert result.artifact.source_revision == _git(root, "rev-parse", "HEAD") != base
    assert _git(root, "status", "--porcelain") == ""


def test_unidentified_git_contract_keeps_generic_classification_without_output_prose(
    tmp_path: Path,
) -> None:
    root, base = _repository(tmp_path)
    request = _slice_request(base, deferred=False)
    artifact = _output(request, implementation=True)
    runner = _ArtifactOutputRunner(artifact.to_wire())
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="test-model",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
    ).run(request)
    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None and result.error.code is AgentErrorCode.INVALID_OUTPUT
    assert "cause=GIT_CONTRACT;" in result.error.message
    assert "WORK_SLICE" not in result.error.message
    assert "Coder did not produce a candidate commit" not in result.error.message
    assert "Added typed models and validators" not in result.error.message
    assert _git(root, "rev-parse", "HEAD") == base
    assert _git(root, "status", "--porcelain") == ""
