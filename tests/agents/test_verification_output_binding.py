"""Native verifier output must cite its real controlled execution receipt."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    CodexCliAgentAdapter,
)
from ai_software_engineer.agents.codex_cli import CodexInvocationResult
from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.verification_output import (
    TrustedVerificationOutputContract,
    VerificationOutputRejected,
    validate_verification_output,
    verification_output_contract,
)
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.artifact import Finding, QaReportArtifact, ReviewReportArtifact
from ai_software_engineer.domain.enums import (
    FindingSeverity,
    QaCriterionStatus,
    QaReportStatus,
    QaTestStatus,
    ReviewVerdict,
)
from ai_software_engineer.domain.execution_window import (
    PlannedVerificationInspection,
    PlannedVerificationRequirement,
)
from ai_software_engineer.domain.native_verification import NativeVerificationWaiting
from ai_software_engineer.recovery.verification_execution import VerificationEvidencePromptBuilder
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from tests.agents.test_codex_cli import _ArtifactOutputRunner
from tests.agents.test_openai_compatible import StaticPromptBuilder
from tests.domain.factories import make_qa_artifact, make_review_artifact
from tests.manager.test_native_verification import _fake_ports, _Fixture, _fixture


def _bound_report(
    request: AgentRequest, contract: TrustedVerificationOutputContract
) -> QaReportArtifact | ReviewReportArtifact:
    template = make_qa_artifact() if request.role is AgentRole.QA else make_review_artifact()
    return template.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "parent_artifact_ids": request.input_artifact_ids,
            "producer": template.producer.model_copy(update={"run_id": request.run_id}),
            "evidence": (
                template.evidence[0].model_copy(
                    update={"uri": contract.receipt_uri, "sha256": contract.receipt_sha256}
                ),
            ),
        }
    )


class _DuringModelRunner(_ArtifactOutputRunner):
    def __init__(self, payload: object, action: Callable[[], None]) -> None:
        super().__init__(payload)
        self._action = action

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        result = super().run(
            argv, cwd=cwd, environment=environment, stdin=stdin, timeout_seconds=timeout_seconds
        )
        self._action()
        return result


def _adapter(
    fixture: _Fixture,
    builder: VerificationEvidencePromptBuilder,
    report: QaReportArtifact | ReviewReportArtifact,
    action: Callable[[], None] = lambda: None,
) -> CodexCliAgentAdapter:
    return CodexCliAgentAdapter(
        workspace_root=fixture.root,
        model="fixture",
        agent_id=fixture.claim.assignment.agent_id,
        agent_version="v0.1",
        prompt_builder=builder,
        execution_guard=fixture.guard,
        runner=_DuringModelRunner(json.loads(report.model_dump_json()), action),
    )


def _assert_rejected(result: AgentResult) -> None:
    assert result.status is AgentRunStatus.FAILED
    assert result.artifact is None
    assert result.error is not None
    assert result.error.code is AgentErrorCode.INVALID_OUTPUT
    assert result.error.transient is False


def test_native_qa_rejects_model_only_command_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    _, executions, _ = _fake_ports(monkeypatch, fixture)
    provider = fixture.bind()
    assert provider is not None
    request = fixture.request
    template = make_qa_artifact()
    report = template.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "parent_artifact_ids": request.input_artifact_ids,
            "producer": template.producer.model_copy(update={"run_id": request.run_id}),
            "evidence": (
                template.evidence[0].model_copy(
                    update={
                        "uri": "command://pytest/model-declared-only",
                        "sha256": "e" * 64,
                    }
                ),
            ),
        }
    )
    runner = _ArtifactOutputRunner(json.loads(report.model_dump_json()))
    adapter = CodexCliAgentAdapter(
        workspace_root=fixture.root,
        model="fixture",
        agent_id=fixture.claim.assignment.agent_id,
        agent_version="v0.1",
        prompt_builder=VerificationEvidencePromptBuilder(
            StaticPromptBuilder(), provider, fixture.root, fixture.guard
        ),
        execution_guard=fixture.guard,
        runner=runner,
    )

    result = adapter.run(request)

    assert len(executions) == 1
    assert result.status is AgentRunStatus.FAILED
    assert result.artifact is None
    assert result.error is not None
    assert result.error.code is AgentErrorCode.INVALID_OUTPUT
    assert result.error.transient is False
    assert "model-declared-only" not in result.error.message


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
@pytest.mark.parametrize("background", [False, True])
def test_native_accepts_exact_receipt_with_optional_background_without_executor_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: AgentRole, background: bool
) -> None:
    fixture = _fixture(tmp_path, role)
    _, executions, _ = _fake_ports(monkeypatch, fixture)
    provider = fixture.bind()
    assert provider is not None
    evidence = provider.evidence_for(fixture.request, fixture.root, fixture.guard)
    contract = evidence.output_contract
    assert contract is not None
    report = _bound_report(fixture.request, contract)
    if background:
        report = report.model_copy(
            update={
                "evidence": (
                    *report.evidence,
                    report.evidence[0].model_copy(
                        update={
                            "evidence_id": "ev_ancestor",
                            "uri": "artifact://ancestor",
                            "sha256": "c" * 64,
                        }
                    ),
                )
            }
        )
    calls: list[AgentRequest] = []
    original = provider.evidence_for

    def counted(request: AgentRequest, root: Path, guard: ExecutionGuard | None = None):
        calls.append(request)
        assert len(calls) == 1, "output admission must not call evidence_for again"
        return original(request, root, guard)

    monkeypatch.setattr(provider, "evidence_for", counted)
    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(), provider, fixture.root, fixture.guard
    )
    result = _adapter(fixture, builder, report).run(fixture.request)
    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None
    assert len(executions) == len(calls) == 1


@pytest.mark.parametrize("defect", ["uri", "sha", "tests", "coverage", "review"])
def test_native_rejects_receipt_and_claim_reference_mismatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    fixture = _fixture(tmp_path, AgentRole.REVIEWER if defect == "review" else AgentRole.QA)
    _, executions, _ = _fake_ports(monkeypatch, fixture)
    provider = fixture.bind()
    assert provider is not None
    contract = provider.evidence_for(fixture.request, fixture.root, fixture.guard).output_contract
    assert contract is not None
    report = _bound_report(fixture.request, contract)
    forged = report.evidence[0].model_copy(
        update={"evidence_id": "ev_unverified", "uri": "command://unverified", "sha256": "d" * 64}
    )
    if defect in {"uri", "sha"}:
        changes = {"uri": "command://unverified"} if defect == "uri" else {"sha256": "d" * 64}
        report = report.model_copy(
            update={"evidence": (report.evidence[0].model_copy(update=changes),)}
        )
    else:
        report = report.model_copy(update={"evidence": (*report.evidence, forged)})
        if isinstance(report, QaReportArtifact):
            content = report.content
            if defect == "tests":
                content = content.model_copy(
                    update={
                        "tests_run": (
                            content.tests_run[0].model_copy(
                                update={"evidence_id": "ev_unverified"}
                            ),
                        )
                    }
                )
            else:
                content = content.model_copy(
                    update={
                        "criteria_results": (
                            content.criteria_results[0].model_copy(
                                update={"evidence_ids": ("ev_unverified",)}
                            ),
                        )
                    }
                )
            report = report.model_copy(update={"content": content})
        else:
            report = report.model_copy(
                update={
                    "content": report.content.model_copy(update={"evidence": ("ev_unverified",)})
                }
            )
    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(), provider, fixture.root, fixture.guard
    )
    _assert_rejected(_adapter(fixture, builder, report).run(fixture.request))
    assert len(executions) == 1


@pytest.mark.parametrize("drift", ["claim", "context", "receipt", "request", "candidate", "guard"])
def test_native_output_rereads_current_facts_and_receipt_without_executor_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    fixture = _fixture(tmp_path)
    _, executions, _ = _fake_ports(monkeypatch, fixture)
    fixture.registry.prepare_verifier(
        request=fixture.request, workspace_root=fixture.root, guard=fixture.guard
    )
    provider = fixture.registry.provider_for(
        workspace_root=fixture.root, guard=fixture.guard, require_prepared=True
    )
    contract = provider.evidence_for(fixture.request, fixture.root, fixture.guard).output_contract
    assert contract is not None
    report = _bound_report(fixture.request, contract)

    def changed() -> None:
        if drift == "claim":
            fixture.guard.claim = fixture.claim.model_copy(
                update={"lease": fixture.claim.lease.model_copy(update={"id": "lease_replaced"})}
            )
        elif drift == "context":
            fixture.facts.context = "ctx_replaced"
        elif drift == "request":
            fixture.facts.request = fixture.request.model_copy(update={"timeout_seconds": 97})
        elif drift == "candidate":
            (fixture.root / "tests/test_case.py").write_text("CHANGED = True\n")
        elif drift == "guard":
            fixture.guard.active = False
        else:
            prepared = next(iter(fixture.registry._prepared.values()))
            assert prepared.provider is not None
            (prepared.provider._store.root / "finished.json").unlink()

    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(), provider, fixture.root, fixture.guard
    )
    with pytest.raises((NativeVerificationWaiting, QueueLeaseLost)):
        _adapter(fixture, builder, report, changed).run(fixture.request)
    assert len(executions) == 1


@pytest.mark.parametrize("report_pass", [False, True])
def test_native_failed_command_preserves_truthful_qa_fail_and_rejects_overall_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, report_pass: bool
) -> None:
    fixture = _fixture(tmp_path)
    _, executions, _ = _fake_ports(monkeypatch, fixture, returncode=1)
    provider = fixture.bind()
    assert provider is not None
    contract = provider.evidence_for(fixture.request, fixture.root, fixture.guard).output_contract
    assert contract is not None
    report = _bound_report(fixture.request, contract)
    assert isinstance(report, QaReportArtifact)
    if not report_pass:
        report = report.model_copy(
            update={
                "content": report.content.model_copy(
                    update={
                        "status": QaReportStatus.FAIL,
                        "criteria_results": (
                            report.content.criteria_results[0].model_copy(
                                update={"status": QaCriterionStatus.FAIL}
                            ),
                        ),
                        "tests_run": (
                            report.content.tests_run[0].model_copy(
                                update={"status": QaTestStatus.FAIL}
                            ),
                        ),
                    }
                )
            }
        )
    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(), provider, fixture.root, fixture.guard
    )
    result = _adapter(fixture, builder, report).run(fixture.request)
    if report_pass:
        _assert_rejected(result)
    else:
        assert result.status is AgentRunStatus.SUCCEEDED
        assert isinstance(result.artifact, QaReportArtifact)
        assert result.artifact.content.status is QaReportStatus.FAIL
    assert len(executions) == 1


def test_mixed_receipt_permits_individual_pass_and_source_only_criterion() -> None:
    request = _fixture_request()
    contract = verification_output_contract(
        request,
        receipt_uri="receipt://current",
        receipt_sha256="a" * 64,
        authority_sha256="b" * 64,
        receipt_covered_required_criterion_ids=("ac_models_01",),
        command_returncodes=(0, 1),
    )
    report = _bound_report(request, contract)
    assert isinstance(report, QaReportArtifact)
    source = report.evidence[0].model_copy(
        update={"evidence_id": "ev_source", "uri": "source://candidate/file", "sha256": "c" * 64}
    )
    report = report.model_copy(
        update={
            "evidence": (*report.evidence, source),
            "content": report.content.model_copy(
                update={
                    "status": QaReportStatus.FAIL,
                    "criteria_results": (
                        *report.content.criteria_results,
                        report.content.criteria_results[0].model_copy(
                            update={"criterion_id": "ac_source_01", "evidence_ids": ("ev_source",)}
                        ),
                    ),
                }
            ),
        }
    )
    validate_verification_output(request, report, contract)
    with pytest.raises(VerificationOutputRejected):
        validate_verification_output(
            request,
            report.model_copy(
                update={
                    "content": report.content.model_copy(update={"status": QaReportStatus.PASS})
                }
            ),
            contract,
        )


def test_native_mixed_source_inspection_does_not_claim_test_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    task = fixture.task.model_copy(
        update={
            "acceptance_criteria": (
                *fixture.task.acceptance_criteria,
                fixture.task.acceptance_criteria[0].model_copy(update={"id": "ac_source_01"}),
            )
        }
    )
    requirements = fixture.plan.content.verification_requirements
    assert requirements is not None
    plan = fixture.plan.model_copy(
        update={
            "content": fixture.plan.content.model_copy(
                update={
                    "verification_requirements": (
                        *requirements,
                        PlannedVerificationRequirement(
                            id="verify_source",
                            role=AgentRole.QA,
                            criterion_ids=("ac_source_01",),
                            inspection=PlannedVerificationInspection(
                                kind="source",
                                paths=("tests/test_case.py",),
                                checklist=("inspect source",),
                            ),
                            verification_levels=("source-inspection",),
                        ),
                    ),
                }
            )
        }
    )
    fixture = replace(fixture, task=task, plan=plan)
    _, executions, _ = _fake_ports(monkeypatch, fixture)
    provider = fixture.bind()
    assert provider is not None
    contract = provider.evidence_for(fixture.request, fixture.root, fixture.guard).output_contract
    assert contract is not None
    assert contract.receipt_covered_required_criterion_ids == ("ac_models_01",)
    report = _bound_report(fixture.request, contract)
    assert isinstance(report, QaReportArtifact)
    source = report.evidence[0].model_copy(
        update={
            "evidence_id": "ev_source",
            "uri": "source://candidate/tests/test_case.py",
            "sha256": "c" * 64,
        }
    )
    report = report.model_copy(
        update={
            "evidence": (*report.evidence, source),
            "content": report.content.model_copy(
                update={
                    "criteria_results": (
                        *report.content.criteria_results,
                        report.content.criteria_results[0].model_copy(
                            update={
                                "criterion_id": "ac_source_01",
                                "evidence_ids": ("ev_source",),
                            }
                        ),
                    )
                }
            ),
        }
    )
    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(), provider, fixture.root, fixture.guard
    )
    assert (
        _adapter(fixture, builder, report).run(fixture.request).status is AgentRunStatus.SUCCEEDED
    )
    assert len(executions) == 1


@pytest.mark.parametrize("returncode", [0, 1])
def test_native_truthful_review_reject_is_not_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int
) -> None:
    fixture = _fixture(tmp_path, AgentRole.REVIEWER)
    _, executions, _ = _fake_ports(monkeypatch, fixture, returncode=returncode)
    provider = fixture.bind()
    assert provider is not None
    contract = provider.evidence_for(fixture.request, fixture.root, fixture.guard).output_contract
    assert contract is not None
    report = _bound_report(fixture.request, contract)
    assert isinstance(report, ReviewReportArtifact)
    report = report.model_copy(
        update={
            "content": report.content.model_copy(
                update={
                    "verdict": ReviewVerdict.REJECT,
                    "findings": (
                        Finding(
                            finding_id="finding_reject",
                            severity=FindingSeverity.MAJOR,
                            message="Controlled observations require remediation",
                            evidence_ids=(report.evidence[0].evidence_id,),
                        ),
                    ),
                }
            )
        }
    )
    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(), provider, fixture.root, fixture.guard
    )
    result = _adapter(fixture, builder, report).run(fixture.request)
    assert result.status is AgentRunStatus.SUCCEEDED
    assert isinstance(result.artifact, ReviewReportArtifact)
    assert result.artifact.content.verdict is ReviewVerdict.REJECT
    assert len(executions) == 1


def test_native_review_approve_cannot_override_failed_required_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, AgentRole.REVIEWER)
    _, executions, _ = _fake_ports(monkeypatch, fixture, returncode=1)
    provider = fixture.bind()
    assert provider is not None
    contract = provider.evidence_for(fixture.request, fixture.root, fixture.guard).output_contract
    assert contract is not None
    report = _bound_report(fixture.request, contract)
    assert isinstance(report, ReviewReportArtifact)
    assert report.content.verdict is ReviewVerdict.APPROVE
    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(), provider, fixture.root, fixture.guard
    )
    result = _adapter(fixture, builder, report).run(fixture.request)
    assert len(executions) == 1
    _assert_rejected(result)


def _fixture_request() -> AgentRequest:
    from tests.agents.test_openai_compatible import _request

    return _request(AgentRole.QA)
