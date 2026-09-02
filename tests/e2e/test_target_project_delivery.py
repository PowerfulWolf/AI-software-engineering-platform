"""Cross-language target-project delivery through the v0.1 public seams.

The fixture projects are deliberately tiny and dependency-free.  The test still uses
the real ProjectProfile, sidecar workspace, typed tool registry, evidence store, and
serial Orchestrator.  A language runtime is an optional local capability: when it is
not installed, the profile and delivery contract remain tested and only the command
evidence assertion is skipped.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import FakeAgentAdapter, FakeBehavior, FakeScenario
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentPermissions,
    AgentRole,
    ArtifactKind,
    ChangedFile,
    ChangeType,
    ImplementationReportArtifact,
    NetworkAccess,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
    Task,
    TaskConstraints,
    TaskStatus,
)
from ai_software_engineer.evidence import (
    CommandEvidenceRecord,
    FileEvidenceStore,
    RunEvidenceIdentity,
    RunEvidenceSession,
    RunOutcome,
)
from ai_software_engineer.evidence import (
    TestOutcome as EvidenceTestOutcome,
)
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.git import CommandPolicyViolation
from ai_software_engineer.orchestration import (
    FileRunContextBuilder,
    OrchestrationIdentityFactory,
    SerialOrchestrator,
)
from ai_software_engineer.project_profile import BuildSystem, ProjectLanguage, ProjectProfile
from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.runtime_workspace import (
    OrganizationWorkspace,
    RuntimeWorkspaceBinder,
)
from ai_software_engineer.store import SqliteTaskRepository
from ai_software_engineer.tools import (
    PolicyBoundToolRegistry,
    ReadFileRequest,
    ReadFileResult,
    RunCommandRequest,
    RunCommandResult,
    ToolRejectedResult,
)
from tests.domain.factories import (
    NOW,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
    make_task,
)


@dataclass(frozen=True, slots=True)
class TargetProjectCase:
    language: ProjectLanguage
    build_system: BuildSystem
    source_path: str
    runtime: str
    command: tuple[str, ...]


CASES = (
    TargetProjectCase(
        ProjectLanguage.PYTHON,
        BuildSystem.PYTHON,
        "src/hello.py",
        "python3",
        ("python3", "--version"),
    ),
    TargetProjectCase(
        ProjectLanguage.JAVA,
        BuildSystem.MAVEN,
        "src/main/java/example/App.java",
        "java",
        ("java", "-version"),
    ),
    TargetProjectCase(
        ProjectLanguage.CPP,
        BuildSystem.CMAKE,
        "src/hello.cpp",
        "cmake",
        ("cmake", "--version"),
    ),
    TargetProjectCase(
        ProjectLanguage.GO,
        BuildSystem.GO,
        "main.go",
        "go",
        ("go", "version"),
    ),
    TargetProjectCase(
        ProjectLanguage.TYPESCRIPT,
        BuildSystem.NPM,
        "src/hello.ts",
        "node",
        ("node", "--version"),
    ),
)


class _RegistryCommandExecutor:
    """Adapt one typed registry command to the evidence CommandExecutor port."""

    def __init__(self, registry: PolicyBoundToolRegistry, run_id: str, role: AgentRole) -> None:
        self._registry = registry
        self._run_id = run_id
        self._role = role

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        result = self._registry.execute(
            RunCommandRequest(
                run_id=self._run_id,
                role=self._role,
                operation_id="tool.e2e.command",
                argv=arguments,
                timeout_seconds=(int(timeout_seconds) if timeout_seconds is not None else None),
            )
        )
        if isinstance(result, ToolRejectedResult):
            raise CommandPolicyViolation(result.error_message)
        if not isinstance(result, RunCommandResult):
            raise CommandPolicyViolation("tool registry returned an unexpected result")
        return result.command


class _CaseIdentityFactory(OrchestrationIdentityFactory):
    def __init__(self, suffix: str) -> None:
        self._suffix = suffix

    def new_run_id(self, task_id: str, role: AgentRole, attempt: int) -> str:
        del task_id, attempt
        return f"run_t025_{self._suffix}_{role.value}"

    def new_event_id(
        self,
        task_id: str,
        from_status: TaskStatus,
        to_status: TaskStatus,
        attempt: int,
    ) -> str:
        del task_id
        return (
            f"evt_t025_{self._suffix}_{from_status.value.lower()}_"
            f"{to_status.value.lower()}_{attempt}"
        )


def _agent_definitions(case: TargetProjectCase) -> dict[AgentRole, AgentDefinition]:
    inputs = {
        AgentRole.ORCHESTRATOR: (),
        AgentRole.CODER: (
            ArtifactKind.PLAN,
            ArtifactKind.QA_REPORT,
            ArtifactKind.REVIEW_REPORT,
        ),
        AgentRole.QA: (ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT),
        AgentRole.REVIEWER: (
            ArtifactKind.PLAN,
            ArtifactKind.IMPLEMENTATION_REPORT,
            ArtifactKind.QA_REPORT,
        ),
    }
    outputs = {
        AgentRole.ORCHESTRATOR: ArtifactKind.PLAN,
        AgentRole.CODER: ArtifactKind.IMPLEMENTATION_REPORT,
        AgentRole.QA: ArtifactKind.QA_REPORT,
        AgentRole.REVIEWER: ArtifactKind.REVIEW_REPORT,
    }
    definitions: dict[AgentRole, AgentDefinition] = {}
    for role in AgentRole:
        write_paths = (
            ()
            if role is AgentRole.REVIEWER
            else ("tests/**",)
            if role is AgentRole.QA
            else ("src/**", "tests/**")
        )
        definitions[role] = AgentDefinition(
            id=f"agent_t025_{case.language.value}_{role.value}",
            role=role,
            version="v0.1",
            model=f"fixture-{case.runtime}-{role.value}",
            provider="local",
            permissions=AgentPermissions(
                read_paths=("**",),
                write_paths=write_paths,
                commands=(case.runtime, "pytest", "git status"),
                network=NetworkAccess.NONE,
                can_change_state=role is AgentRole.ORCHESTRATOR,
            ),
            input_artifacts=inputs[role],
            output_artifacts=(outputs[role],),
            max_retries=0,
            timeout_seconds=60,
            token_budget=2_000,
        )
    return definitions


def _task(project_root: Path, case: TargetProjectCase) -> Task:
    task = make_task()
    criterion = task.acceptance_criteria[0].model_copy(
        update={
            "description": (
                f"ProjectProfile detects {case.language.value} and delivery is independently "
                "reviewed."
            ),
            "verification": f"Read {case.source_path} and run the local {case.runtime} probe.",
            "test_ids": (f"test_t025_{case.language.value}",),
        }
    )
    return task.model_copy(
        update={
            "id": f"task_t025_{case.language.value}",
            "title": f"Deliver {case.language.value} target fixture",
            "repository": str(project_root.resolve()),
            "base_ref": "main",
            "acceptance_criteria": (criterion,),
            "constraints": TaskConstraints(
                allowed_paths=(
                    "src/**",
                    "tests/**",
                    "main.go",
                    "pom.xml",
                    "package.json",
                    "tsconfig.json",
                    "pyproject.toml",
                ),
                denied_paths=(".env", ".trellis/**", "*.json"),
                allowed_commands=(case.runtime, "pytest", "git status"),
                max_attempts=3,
                notes="T025 fixture delivery is offline and serial.",
            ),
            "metadata": {"t025_fixture_language": case.language.value},
        }
    )


def _build_adapter(
    task: Task,
    case: TargetProjectCase,
    definitions: dict[AgentRole, AgentDefinition],
    contexts: FileRunContextBuilder,
) -> FakeAgentAdapter:
    suffix = case.language.value
    run_ids = {role: f"run_t025_{suffix}_{role.value}" for role in AgentRole}
    plan_context = contexts.build(
        task.model_copy(update={"status": TaskStatus.PLANNING}),
        definitions[AgentRole.ORCHESTRATOR],
        attempt=1,
    )
    plan = make_plan_artifact().model_copy(
        update={
            "artifact_id": f"art_t025_{suffix}_plan",
            "task_id": task.id,
            "source_revision": task.base_ref,
            "context_manifest_id": plan_context.context_id,
            "producer": make_plan_artifact().producer.model_copy(
                update={"run_id": run_ids[AgentRole.ORCHESTRATOR]}
            ),
        }
    )
    plan = cast(PlanArtifact, seal_artifact(plan, validated_at=NOW))
    implementing = task.model_copy(update={"status": TaskStatus.IMPLEMENTING})
    coder_context = contexts.build(
        implementing,
        definitions[AgentRole.CODER],
        attempt=1,
        input_artifacts=(plan,),
    )
    candidate_sha = hashlib.sha1(f"t025-{suffix}".encode("ascii")).hexdigest()
    implementation = make_implementation_artifact().model_copy(
        update={
            "artifact_id": f"art_t025_{suffix}_implementation",
            "task_id": task.id,
            "source_revision": candidate_sha,
            "context_manifest_id": coder_context.context_id,
            "parent_artifact_ids": (plan.artifact_id,),
            "producer": make_implementation_artifact().producer.model_copy(
                update={"run_id": run_ids[AgentRole.CODER]}
            ),
            "content": make_implementation_artifact().content.model_copy(
                update={
                    "commit_sha": candidate_sha,
                    "changed_files": (
                        ChangedFile(
                            path=case.source_path,
                            change=ChangeType.MODIFIED,
                            lines_added=1,
                            lines_deleted=0,
                        ),
                    ),
                }
            ),
        }
    )
    implementation = cast(
        ImplementationReportArtifact,
        seal_artifact(implementation, validated_at=NOW),
    )
    qa_context = contexts.build(
        task.model_copy(update={"status": TaskStatus.QA}),
        definitions[AgentRole.QA],
        attempt=1,
        candidate_revision=candidate_sha,
        input_artifacts=(plan, implementation),
    )
    qa = make_qa_artifact().model_copy(
        update={
            "artifact_id": f"art_t025_{suffix}_qa",
            "task_id": task.id,
            "source_revision": candidate_sha,
            "context_manifest_id": qa_context.context_id,
            "parent_artifact_ids": (implementation.artifact_id,),
            "producer": make_qa_artifact().producer.model_copy(
                update={"run_id": run_ids[AgentRole.QA]}
            ),
        }
    )
    qa = cast(QaReportArtifact, seal_artifact(qa, validated_at=NOW))
    review_context = contexts.build(
        task.model_copy(update={"status": TaskStatus.REVIEW}),
        definitions[AgentRole.REVIEWER],
        attempt=1,
        candidate_revision=candidate_sha,
        input_artifacts=(plan, implementation, qa),
    )
    review = make_review_artifact().model_copy(
        update={
            "artifact_id": f"art_t025_{suffix}_review",
            "task_id": task.id,
            "source_revision": candidate_sha,
            "context_manifest_id": review_context.context_id,
            "parent_artifact_ids": (qa.artifact_id,),
            "producer": make_review_artifact().producer.model_copy(
                update={"run_id": run_ids[AgentRole.REVIEWER]}
            ),
        }
    )
    review = cast(ReviewReportArtifact, seal_artifact(review, validated_at=NOW))
    return FakeAgentAdapter(
        scenarios={
            (AgentRole.ORCHESTRATOR, 1): FakeScenario(
                behavior=FakeBehavior.SUCCESS,
                artifact=plan,
            ),
            (AgentRole.CODER, 1): FakeScenario(
                behavior=FakeBehavior.SUCCESS,
                artifact=implementation,
            ),
            (AgentRole.QA, 1): FakeScenario(behavior=FakeBehavior.SUCCESS, artifact=qa),
            (AgentRole.REVIEWER, 1): FakeScenario(behavior=FakeBehavior.SUCCESS, artifact=review),
        }
    )


def _copy_fixture(case: TargetProjectCase, destination: Path) -> Path:
    source = Path(__file__).parents[2] / "fixtures" / "target-projects" / case.language.value
    target = destination / case.language.value
    shutil.copytree(source, target)
    return target


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.language.value)
def test_target_project_serial_delivery_matrix(tmp_path: Path, case: TargetProjectCase) -> None:
    project_root = _copy_fixture(case, tmp_path / "targets")
    sidecars = tmp_path / "sidecars"
    workspace = ProjectWorkspaceRegistry(sidecars).register(
        project_root,
        project_id=f"project_t025_{case.language.value}",
    )
    profile = ProjectProfile.discover(
        project_root,
        project_id=workspace.project_id,
        observed_at=NOW,
    )
    assert {fact.language for fact in profile.languages} >= {case.language}
    assert {fact.system for fact in profile.build_systems} >= {case.build_system}
    assert workspace.project_root == project_root.resolve()
    assert not (project_root / ".ase").exists()

    organization = OrganizationWorkspace.initialize(
        tmp_path / "organization",
        organization_id="organization_t025_001",
        created_at=NOW,
    )
    binding = RuntimeWorkspaceBinder().bind(organization, workspace, profile, bound_at=NOW)
    assert Path(binding.project_root) == project_root.resolve()
    assert Path(binding.project_workspace_root) == workspace.root
    assert workspace.directory("evidence").is_dir()
    assert workspace.directory("runs").is_dir()

    task = _task(project_root, case)
    definitions = _agent_definitions(case)
    tool_run_id = f"run_t025_{case.language.value}_tool"
    tool_registry = PolicyBoundToolRegistry(
        project_root,
        definitions[AgentRole.CODER],
        run_id=tool_run_id,
    )
    source_result = tool_registry.execute(
        ReadFileRequest(
            run_id=tool_run_id,
            role=AgentRole.CODER,
            operation_id="tool.e2e.read-source",
            path=case.source_path,
        )
    )
    assert isinstance(source_result, ReadFileResult)
    assert "hello" in source_result.content.lower()

    if shutil.which(case.runtime) is not None:
        evidence_identity = RunEvidenceIdentity(
            project_id=workspace.project_id,
            task_id=task.id,
            run_id=tool_run_id,
            agent_id=definitions[AgentRole.CODER].id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=task.base_ref,
            context_manifest_id="ctx_" + "0" * 64,
        )
        evidence_store = FileEvidenceStore(
            workspace.directory("evidence"),
            workspace.directory("runs"),
        )
        evidence_session = RunEvidenceSession(
            evidence_store,
            evidence_identity,
            workspace_root=project_root,
            clock=lambda: NOW,
        )
        command_evidence = evidence_session.capture_command(
            "tool.e2e.command",
            _RegistryCommandExecutor(tool_registry, tool_run_id, AgentRole.CODER),
            case.command,
        )
        assert isinstance(command_evidence, CommandEvidenceRecord)
        assert command_evidence.payload.outcome.value == "COMPLETED"
        test_evidence = evidence_session.record_test(
            "tool.e2e.test",
            framework=case.runtime,
            suite="runtime-probe",
            outcome=(
                EvidenceTestOutcome.PASS
                if command_evidence.payload.returncode == 0
                else EvidenceTestOutcome.FAIL
            ),
            command_evidence_id=command_evidence.evidence_id,
        )
        manifest = evidence_session.seal(RunOutcome.SUCCEEDED)
        assert test_evidence.evidence_id in manifest.evidence_ids
        assert evidence_store.get_run(tool_run_id) == manifest

    contexts = FileRunContextBuilder(
        project_root,
        context_store=FileContextStore(workspace.directory("contexts")),
    )
    adapter = _build_adapter(task, case, definitions, contexts)
    artifacts = FileArtifactStore(workspace.directory("artifacts"))
    with SqliteTaskRepository(workspace.directory("state") / "tasks.sqlite3") as repository:
        repository.create(task)
        result = SerialOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=contexts,
            agent_adapter=adapter,
            agent_definitions=definitions,
            identities=_CaseIdentityFactory(case.language.value),
            clock=lambda: NOW,
        ).run_task(task.id)
        assert result.task.status is TaskStatus.DONE
        implementation = artifacts.get(result.artifact_ids[1])
        assert isinstance(implementation, ImplementationReportArtifact)
        assert result.candidate_revision == implementation.content.commit_sha
        assert tuple(event.to_status for event in repository.list_events(task.id)) == (
            TaskStatus.PLANNING,
            TaskStatus.IMPLEMENTING,
            TaskStatus.QA,
            TaskStatus.REVIEW,
            TaskStatus.DONE,
        )
        assert len(result.artifact_ids) == 4
        persisted_artifacts = tuple(artifacts.get(item) for item in result.artifact_ids)
        assert len({artifact.producer.role for artifact in persisted_artifacts}) == 4
        assert all(
            (workspace.directory("contexts") / f"{context_id}.json").is_file()
            for context_id in result.context_manifest_ids
        )
