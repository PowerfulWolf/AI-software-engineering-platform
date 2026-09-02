"""Run-scoped workforce allocation and bound RuntimeSession tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import pytest

from ai_software_engineer.context import ContextBundle, FileContextBuilder, FileContextStore
from ai_software_engineer.domain import (
    AgentProfile,
    AgentRole,
    BrainTier,
    ModelRouteReason,
    ModelSelection,
    OrganizationRole,
    RiskTier,
    RoleAssignment,
    Task,
    TaskLease,
    WorkItem,
    WorkItemStatus,
)
from ai_software_engineer.evaluation import CaseStartedEvent, FileEvaluationEventStore
from ai_software_engineer.runtime import RuntimeConfig, RuntimeConfigurationError, RuntimeSession
from ai_software_engineer.runtime_workspace import (
    FileOrganizationWorkforceStore,
    RuntimeAllocationError,
    RuntimeWorkforceResolver,
    RuntimeWorkspaceBinding,
)
from ai_software_engineer.spec_compiler import CompiledSpec, SpecCompiler
from ai_software_engineer.store import SqliteTaskRepository
from tests.runtime.test_runtime import RuntimeFixtureAdapter
from tests.runtime_workspace.test_binding import (
    NOW,
    bind,
    hard_rule,
    model_policy,
    runtime_task,
)


class AllocationFacts(NamedTuple):
    binding: RuntimeWorkspaceBinding
    config: RuntimeConfig
    task: Task
    compiled: CompiledSpec
    context: ContextBundle
    item: WorkItem
    assignment: RoleAssignment
    lease: TaskLease
    selection: ModelSelection
    resolver: RuntimeWorkforceResolver


def allocation_facts(tmp_path: Path) -> AllocationFacts:
    org, _workspace, profile, project, binding = bind(tmp_path)
    store = FileOrganizationWorkforceStore(org)
    agent = AgentProfile(
        id="agent_runtime_coder_001",
        version="v1",
        display_name="Runtime Coder",
        capabilities=("python",),
        eligible_roles=(OrganizationRole.CODER,),
        max_parallel_assignments=2,
        default_model_policy_id="model_policy_runtime_001",
    )
    policy = model_policy()
    store.put_agent(agent)
    store.put_policy(policy)
    task = runtime_task(project)
    compilation = SpecCompiler().compile(profile, task, (hard_rule(),), compiled_at=NOW)
    assert compilation.compiled_spec is not None
    compiled = compilation.compiled_spec
    config = binding.compose_runtime_config(
        RuntimeConfig(
            endpoint="https://api.example.test/v1",
            model="fallback-model",
            api_key_required=False,
        ),
        compiled,
    )
    context = FileContextBuilder(
        project,
        config.agent_definitions()[AgentRole.CODER].permissions,
        sources=config.context_sources,
    ).build(task, AgentRole.CODER, attempt=1)
    FileContextStore(binding.paths.contexts).put(context)
    item = WorkItem(
        task_id=task.id,
        project_id=binding.project_id,
        status=WorkItemStatus.READY,
        priority=800,
        risk=RiskTier.NORMAL,
        required_capabilities=("python",),
        created_at=NOW,
        updated_at=NOW,
    )
    assignment = RoleAssignment(
        id="assignment_runtime_coder_001",
        project_id=binding.project_id,
        task_id=task.id,
        agent_id=agent.id,
        role=AgentRole.CODER,
        attempt=1,
        lease_id="lease_runtime_coder_001",
        assigned_at=NOW,
    )
    lease = TaskLease(
        id=assignment.lease_id,
        assignment_id=assignment.id,
        task_id=task.id,
        agent_id=agent.id,
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    selection = ModelSelection(
        policy_id=policy.id,
        policy_version=policy.version,
        provider="provider-a",
        model="model-standard",
        tier=BrainTier.STANDARD,
        reasons=(ModelRouteReason.DEFAULT,),
        selected_at=NOW,
    )
    resolver = RuntimeWorkforceResolver(binding, store, config)
    return AllocationFacts(
        binding,
        config,
        task,
        compiled,
        context,
        item,
        assignment,
        lease,
        selection,
        resolver,
    )


def test_resolver_builds_auditable_allocation_and_existing_agent_definition(
    tmp_path: Path,
) -> None:
    (
        binding,
        _config,
        _task,
        compiled,
        context,
        item,
        assignment,
        lease,
        selection,
        resolver,
    ) = allocation_facts(tmp_path)

    first = resolver.resolve(
        work_item=item,
        assignment=assignment,
        lease=lease,
        selection=selection,
        context_manifest_id=context.context_id,
        compiled_spec=compiled,
        allocated_at=NOW + timedelta(minutes=1),
    )
    replay = resolver.resolve(
        work_item=item,
        assignment=assignment,
        lease=lease,
        selection=selection,
        context_manifest_id=context.context_id,
        compiled_spec=compiled,
        allocated_at=NOW + timedelta(minutes=2),
    )

    assert first.allocation.run_id == replay.allocation.run_id
    assert first.allocation.assignment_id == assignment.id
    assert first.allocation.context_manifest_id == context.context_id
    assert first.allocation.spec_version == compiled.compiled_sha256
    assert first.agent_definition.id == assignment.agent_id
    assert first.agent_definition.model == selection.model
    assert first.agent_definition.provider == selection.provider
    assert first.code_root == binding.project_root
    assert first.allocation.tool_policy_ref.startswith(f"policy://{binding.project_id}/coder/")


def test_waiting_or_expired_work_does_not_allocate_or_mutate_delivery_state(
    tmp_path: Path,
) -> None:
    (
        _binding,
        _config,
        task,
        compiled,
        context,
        item,
        assignment,
        lease,
        selection,
        resolver,
    ) = allocation_facts(tmp_path)
    waiting = item.model_copy(
        update={
            "status": WorkItemStatus.WAITING_HUMAN,
            "wait_reason": "Resolve SPEC_CONFLICT",
        }
    )
    original_status = task.status

    with pytest.raises(RuntimeAllocationError, match="waiting or closed"):
        resolver.resolve(
            work_item=waiting,
            assignment=assignment,
            lease=lease,
            selection=selection,
            context_manifest_id=context.context_id,
            compiled_spec=compiled,
            allocated_at=NOW + timedelta(minutes=1),
        )
    assert task.status is original_status

    with pytest.raises(RuntimeAllocationError, match="not active"):
        resolver.resolve(
            work_item=item,
            assignment=assignment,
            lease=lease,
            selection=selection,
            context_manifest_id=context.context_id,
            compiled_spec=compiled,
            allocated_at=lease.expires_at,
        )
    assert task.status is original_status


def test_resolver_rejects_policy_route_and_context_mismatches(tmp_path: Path) -> None:
    (
        _binding,
        _config,
        _task,
        compiled,
        context,
        item,
        assignment,
        lease,
        selection,
        resolver,
    ) = allocation_facts(tmp_path)
    invalid_selection = selection.model_copy(update={"model": "model-not-approved"})

    with pytest.raises(RuntimeAllocationError, match="absent from ModelPolicy"):
        resolver.resolve(
            work_item=item,
            assignment=assignment,
            lease=lease,
            selection=invalid_selection,
            context_manifest_id=context.context_id,
            compiled_spec=compiled,
            allocated_at=NOW + timedelta(minutes=1),
        )
    with pytest.raises(RuntimeAllocationError, match="Context manifest"):
        resolver.resolve(
            work_item=item,
            assignment=assignment,
            lease=lease,
            selection=selection,
            context_manifest_id="ctx_" + "f" * 64,
            compiled_spec=compiled,
            allocated_at=NOW + timedelta(minutes=1),
        )


def test_bound_runtime_session_rejects_task_from_another_project(tmp_path: Path) -> None:
    binding, config, task, _compiled, _context, *_rest = allocation_facts(tmp_path)
    other_project = tmp_path / "other-project"
    other_project.mkdir()
    mismatched = task.model_copy(update={"repository": str(other_project)})
    with SqliteTaskRepository(config.paths.database) as repository:
        repository.create(mismatched)

    with (
        RuntimeSession(
            config,
            environment={},
            agent_adapter=RuntimeFixtureAdapter(),
            project_root=binding.project_root,
        ) as session,
        pytest.raises(RuntimeConfigurationError, match="bound project root"),
    ):
        session.run_task(mismatched.id)


def test_bound_runtime_uses_workforce_definitions_and_records_model_set_identity(
    tmp_path: Path,
) -> None:
    binding, config, task, _compiled, _context, *_rest = allocation_facts(tmp_path)
    definitions = {
        role: definition.model_copy(
            update={
                "id": f"agent_{role.value}_001",
                "provider": "provider-a",
                "model": f"model-{role.value}",
            }
        )
        for role, definition in config.agent_definitions().items()
    }
    observed_at = datetime.now(UTC)
    task = task.model_copy(update={"created_at": observed_at, "updated_at": observed_at})
    with SqliteTaskRepository(config.paths.database) as repository:
        repository.create(task)

    with RuntimeSession(
        config,
        environment={},
        agent_adapter=RuntimeFixtureAdapter(),
        agent_definitions=definitions,
        project_root=binding.project_root,
    ) as session:
        result = session.run_task(task.id)

    events = FileEvaluationEventStore(config.paths.evaluation_events).list_for_case(result.case_id)
    assert result.result.task.status.value == "DONE"
    assert isinstance(events[0], CaseStartedEvent)
    assert events[0].model_id.startswith("model-set-")
    assert events[0].model_id != config.model
