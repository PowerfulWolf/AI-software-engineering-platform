"""Independent positive examples for the public domain contracts."""

from datetime import UTC, datetime

from ai_software_engineer.domain import (
    AcceptanceCriterion,
    AgentDefinition,
    AgentPermissions,
    AgentProducer,
    AgentRole,
    ArtifactIntegrity,
    ArtifactKind,
    ChangedFile,
    ChangeType,
    Evidence,
    EvidenceType,
    ImplementationAcceptanceMapping,
    ImplementationReportArtifact,
    ImplementationReportContent,
    ImplementationTestRun,
    ImplementationTestStatus,
    NetworkAccess,
    PlanAcceptanceMapping,
    PlanArtifact,
    PlanContent,
    PlanRisk,
    PlanStep,
    QaCriterionResult,
    QaCriterionStatus,
    QaReportArtifact,
    QaReportContent,
    QaReportStatus,
    QaTestRun,
    QaTestStatus,
    ReviewDimension,
    ReviewReportArtifact,
    ReviewReportContent,
    ReviewVerdict,
    Task,
    TaskConstraints,
    TaskStatus,
)

NOW = datetime(2026, 8, 31, 7, 0, tzinfo=UTC)
SHA256 = "a" * 64
CANDIDATE_SHA = "b" * 40


def make_task() -> Task:
    return Task(
        id="task_domain_001",
        title="Implement typed domain contracts",
        description="Validate Task, Agent, and Artifact payloads at the domain boundary.",
        repository="/workspace/example",
        base_ref="main",
        acceptance_criteria=(
            AcceptanceCriterion(
                id="ac_models_01",
                description="Valid payloads become typed immutable models.",
                required=True,
                verification="Run the domain contract tests.",
                test_ids=("test_valid_task",),
            ),
        ),
        constraints=TaskConstraints(
            allowed_paths=("src/**", "tests/**"),
            denied_paths=(".env",),
            allowed_commands=("pytest", "ruff"),
            max_attempts=3,
            notes="No provider SDKs in the domain package.",
        ),
        status=TaskStatus.NEW,
        max_attempts=3,
        attempts=0,
        labels=("domain", "contract"),
        created_at=NOW,
        updated_at=NOW,
        metadata={"milestone": "M1"},
    )


def make_agent() -> AgentDefinition:
    return AgentDefinition(
        id="agent_coder_001",
        role=AgentRole.CODER,
        version="v0.1",
        model="fake-coder",
        provider="local",
        system_prompt_ref="prompts/coder.md.j2",
        permissions=AgentPermissions(
            read_paths=("src/**", "tests/**", ".trellis/spec/**"),
            write_paths=("src/**", "tests/unit/**"),
            commands=("pytest", "ruff", "git diff", "git status"),
            network=NetworkAccess.NONE,
        ),
        input_artifacts=(
            ArtifactKind.PLAN,
            ArtifactKind.QA_REPORT,
            ArtifactKind.REVIEW_REPORT,
        ),
        output_artifacts=(ArtifactKind.IMPLEMENTATION_REPORT,),
        max_retries=1,
        timeout_seconds=600,
        token_budget=20_000,
        metadata={"purpose": "contract-test"},
    )


def _producer(role: AgentRole, agent_id: str) -> AgentProducer:
    return AgentProducer(
        role=role,
        agent_id=agent_id,
        agent_version="v0.1",
        run_id=f"run_{agent_id}_001",
    )


def _evidence(evidence_id: str, evidence_type: EvidenceType) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        type=evidence_type,
        uri=f"evidence/{evidence_id}.txt",
        description=f"Evidence for {evidence_id}",
        sha256=SHA256,
        required=True,
    )


def _integrity() -> ArtifactIntegrity:
    return ArtifactIntegrity(sha256=SHA256, validated=True, validated_at=NOW)


def make_plan_artifact() -> PlanArtifact:
    return PlanArtifact(
        artifact_id="art_plan_001",
        task_id="task_domain_001",
        schema_version="v0.1",
        producer=_producer(AgentRole.ORCHESTRATOR, "agent_orchestrator_001"),
        source_revision="a" * 40,
        context_manifest_id="ctx_plan_001",
        created_at=NOW,
        parent_artifact_ids=(),
        evidence=(_evidence("ev_plan_spec", EvidenceType.FILE),),
        content=PlanContent(
            goal="Create typed contracts.",
            assumptions=("Canonical JSON Schemas are available.",),
            steps=(
                PlanStep(
                    step_id="step_models",
                    description="Implement the domain models.",
                    files=("src/ai_software_engineer/domain/",),
                    verification="Run contract tests.",
                ),
            ),
            acceptance_mapping=(
                PlanAcceptanceMapping(
                    criterion_id="ac_models_01",
                    step_ids=("step_models",),
                    test_strategy="Validate positive and negative payloads.",
                ),
            ),
            risks=(
                PlanRisk(
                    risk="Python and JSON Schema contracts drift.",
                    mitigation="Validate every positive wire fixture against both.",
                ),
            ),
        ),
        integrity=_integrity(),
    )


def make_implementation_artifact() -> ImplementationReportArtifact:
    return ImplementationReportArtifact(
        artifact_id="art_impl_001",
        task_id="task_domain_001",
        schema_version="v0.1",
        producer=_producer(AgentRole.CODER, "agent_coder_001"),
        source_revision=CANDIDATE_SHA,
        context_manifest_id="ctx_impl_001",
        created_at=NOW,
        parent_artifact_ids=("art_plan_001",),
        evidence=(_evidence("ev_impl_tests", EvidenceType.TEST),),
        content=ImplementationReportContent(
            commit_sha=CANDIDATE_SHA,
            changed_files=(
                ChangedFile(
                    path="src/ai_software_engineer/domain/task.py",
                    change=ChangeType.ADDED,
                    lines_added=80,
                    lines_deleted=0,
                ),
            ),
            acceptance_mapping=(
                ImplementationAcceptanceMapping(
                    criterion_id="ac_models_01",
                    implementation="Added typed models and validators.",
                    tests=("tests/domain/test_task_agent.py",),
                ),
            ),
            tests_run=(
                ImplementationTestRun(
                    command="pytest tests/domain",
                    status=ImplementationTestStatus.PASS,
                    evidence_id="ev_impl_tests",
                    duration_ms=120,
                ),
            ),
            known_risks=(),
        ),
        integrity=_integrity(),
    )


def make_qa_artifact() -> QaReportArtifact:
    return QaReportArtifact(
        artifact_id="art_qa_001",
        task_id="task_domain_001",
        schema_version="v0.1",
        producer=_producer(AgentRole.QA, "agent_qa_001"),
        source_revision=CANDIDATE_SHA,
        context_manifest_id="ctx_qa_001",
        created_at=NOW,
        parent_artifact_ids=("art_impl_001",),
        evidence=(_evidence("ev_qa_tests", EvidenceType.TEST),),
        content=QaReportContent(
            status=QaReportStatus.PASS,
            criteria_results=(
                QaCriterionResult(
                    criterion_id="ac_models_01",
                    status=QaCriterionStatus.PASS,
                    evidence_ids=("ev_qa_tests",),
                ),
            ),
            tests_run=(
                QaTestRun(
                    command="pytest",
                    status=QaTestStatus.PASS,
                    evidence_id="ev_qa_tests",
                    duration_ms=200,
                ),
            ),
            findings=(),
            environment={"python": "3.12"},
        ),
        integrity=_integrity(),
    )


def make_review_artifact() -> ReviewReportArtifact:
    return ReviewReportArtifact(
        artifact_id="art_review_001",
        task_id="task_domain_001",
        schema_version="v0.1",
        producer=_producer(AgentRole.REVIEWER, "agent_reviewer_001"),
        source_revision=CANDIDATE_SHA,
        context_manifest_id="ctx_review_001",
        created_at=NOW,
        parent_artifact_ids=("art_qa_001",),
        evidence=(_evidence("ev_review_diff", EvidenceType.DIFF),),
        content=ReviewReportContent(
            verdict=ReviewVerdict.APPROVE,
            findings=(),
            checked_dimensions=(
                ReviewDimension.CORRECTNESS,
                ReviewDimension.ACCEPTANCE,
                ReviewDimension.CONTRACT_CONSISTENCY,
            ),
            evidence=("ev_review_diff",),
            summary="The candidate satisfies the typed contract.",
        ),
        integrity=_integrity(),
    )
