"""Public chained recovery retains complete inputs beyond the newest partial draft."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import NoReturn

import pytest

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    CodexCliAgentAdapter,
    CodexInvocationResult,
    ContextPromptBuilder,
    StoredContextResolver,
    StructuredModelClient,
    StructuredModelResult,
)
from ai_software_engineer.config import ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import ContextBundle, FileContextStore
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    Artifact,
    ChangedFile,
    ChangeType,
    TaskStatus,
    TeamRole,
)
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
)
from ai_software_engineer.manager.production_delivery import DeliveryRouteAdapterFactory
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration.retry import RetryResult
from ai_software_engineer.recovery.context import recovery_context_sources, validate_reapply_context
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.native import NativeRecoverySourceReader
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome, DeliveryResumeResult
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from ai_software_engineer.store import MySqlTaskRepository
from tests.git.test_capture import git
from tests.manager.test_production_backend import _ScriptedDeliveryAdapter
from tests.recovery import facts_window_fixture
from tests.recovery.execution_fixture import (
    OfflineRecoveryClients,
    _SourceInspectionClient,
    offline_coder_draft,
)
from tests.recovery.facts_window_fixture import modern_failed_native_fixture
from tests.recovery.test_execution import OfflineRunner
from tests.recovery.test_native import _snapshot

pytestmark = pytest.mark.mysql

_FEATURE = "feature.txt"
_FEATURE_DRAFT = "complete historical feature still needs adaptation\n"
_FEATURE_FINAL = "adapted historical feature\n"


@pytest.fixture(autouse=True)
def isolated_mysql_facts() -> Iterator[None]:
    """The shared native helper owns its exclusive, identity-checked DB reset."""
    yield


class _TwoFileClient(_SourceInspectionClient):
    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        result = super().complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )
        if output_schema.get("title") != "TechnicalDesignDraft":
            return result
        payload = dict(result.payload)
        components = payload["components"]
        assert isinstance(components, list)
        payload["components"] = [
            {**component, "affected_paths": ["hello.txt", _FEATURE]} for component in components
        ]
        return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)


class _TwoFileClients(OfflineRecoveryClients):
    def for_project(
        self, repository_root: Path, role: TeamRole = TeamRole.PRODUCT
    ) -> StructuredModelClient:
        del role
        assert repository_root.is_dir()
        return _TwoFileClient()


def _two_file_failed_codex(root: Path) -> str:
    """Real owned failures: the successor deliberately adapts only one old file."""
    executable = root / "offline-failed-codex"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        "import sys\n"
        "prompt = sys.stdin.read()\n"
        f"with Path({str(root / 'offline-provider-calls.txt')!r}).open('a') as calls:\n"
        "    calls.write('called\\n')\n"
        "Path('hello.txt').write_text('partially implemented\\n')\n"
        "if 'recovery.origin' not in prompt:\n"
        f"    Path({_FEATURE!r}).write_text({_FEATURE_DRAFT!r})\n"
        "sys.stderr.write('error: authentication failure in offline fixture\\n')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return str(executable)


def _continue(host: TeamHost, command: ResumeProjectDelivery) -> DeliveryResumeResult:
    result = host.resume_delivery(command)
    assert isinstance(result, DeliveryResumeResult)
    return result


def _context(path: Path, context_id: str) -> ContextBundle:
    return FileContextStore(path.parent.parent.parent / "contexts", read_only=True).get(context_id)


def _missing_claim(*args: object, **kwargs: object) -> NoReturn:
    del args, kwargs
    raise RecoveryRejected("missing claimed queue fact")


def _require_inputs(plan: RecoveryPlan, context: ContextBundle) -> None:
    validate_reapply_context(plan, context)
    sources = recovery_context_sources(plan)
    expected = [
        source for source in sources if source.source_id.startswith("recovery.inherited_patch.")
    ]
    actual = [s for s in context.sections if s.name.startswith("source:recovery.inherited_patch.")]
    assert len(actual) == len(expected) == len(plan.inherited_reapply_inputs or ())
    for source in expected:
        assert source.required and source.roles == (AgentRole.CODER,)
        sections = [s for s in actual if s.name == "source:" + source.source_id]
        assert len(sections) == 1
        section = sections[0]
        assert section.content == source.content and section.uri == source.uri
        assert not section.truncated
    current = [s for s in context.sections if s.name == "source:recovery.patch"]
    assert len(current) == 1
    assert current[0].content == plan.capture.patch and not current[0].truncated


class _CompleteRunner(OfflineRunner):
    def __init__(
        self,
        definition: AgentDefinition,
        root: Path,
        calls: list[AgentRequest],
        seed: RecoverySeedService,
        plan: RecoveryPlan,
    ) -> None:
        super().__init__(definition, root, calls, reapply=True)
        self.seed, self.plan = seed, plan

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del environment, timeout_seconds
        assert self.request is not None and cwd == self.root
        request = self.request
        context = self.seed.contexts.get(request.context_manifest_id)
        self.calls.append(request)
        artifact: Artifact
        if request.role is AgentRole.CODER:
            _require_inputs(self.plan, context)
            assert git(cwd, "status", "--porcelain") == ""
            assert not (cwd / _FEATURE).exists()
            assert "Do not run git add or git commit" in stdin
            messages = json.loads(stdin.partition("\nPROMPT_MESSAGES=")[2])
            assert isinstance(messages, list)
            users = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
            assert len(users) == 1 and isinstance(users[0]["content"], dict)
            sections = users[0]["content"]["sections"]
            assert isinstance(sections, list)
            delivered: dict[str, str] = {}
            for section in sections:
                assert isinstance(section, dict)
                name, content = section["name"], section["content"]
                if isinstance(name, str) and isinstance(content, str):
                    delivered[name] = content
            for inherited in self.plan.inherited_reapply_inputs or ():
                name = "source:recovery.inherited_patch." + inherited.origin_plan_sha256
                assert delivered[name] == inherited.patch
            assert delivered["source:recovery.patch"] == self.plan.capture.patch
            draft = offline_coder_draft(self.definition, request, cwd)
            (cwd / _FEATURE).write_text(_FEATURE_FINAL, encoding="utf-8")
            artifact = draft.model_copy(
                update={
                    "content": draft.content.model_copy(
                        update={
                            "changed_files": (
                                *draft.content.changed_files,
                                ChangedFile(
                                    path=_FEATURE,
                                    change=ChangeType.ADDED,
                                    lines_added=1,
                                    lines_deleted=0,
                                ),
                            )
                        }
                    )
                }
            )
        else:
            assert not any("recovery.inherited_patch." in s.name for s in context.sections)
            assert not any(s.name == "source:recovery.patch" for s in context.sections)
            assert (
                git(cwd, "show", f"{request.source_revision}:{_FEATURE}") == _FEATURE_FINAL.strip()
            )
            result = _ScriptedDeliveryAdapter(self.definition, cwd).run(request)
            assert result.artifact is not None
            artifact = result.artifact
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            json.dumps(artifact.to_wire()), encoding="utf-8"
        )
        return CodexInvocationResult(returncode=0)


class _CompleteAdapter:
    def __init__(self, adapter: CodexCliAgentAdapter, runner: _CompleteRunner) -> None:
        self.adapter, self.runner = adapter, runner

    def run(self, request: AgentRequest) -> AgentResult:
        self.runner.request = request
        return self.adapter.run(request)


class _CompleteFactory:
    def __init__(self, seed: RecoverySeedService) -> None:
        self.seed = seed
        self.calls: list[AgentRequest] = []

    def create(
        self,
        *,
        route: ProviderRouteConfig,
        definition: AgentDefinition,
        binding: RoleWorktreeBinding,
        context_resolver: StoredContextResolver,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> AgentAdapter:
        del config
        plan = self.seed.store.get_plan(self.seed.dispatch.recovery_plan_sha256)
        runner = _CompleteRunner(definition, binding.worktree.path, self.calls, self.seed, plan)
        return _CompleteAdapter(
            CodexCliAgentAdapter(
                workspace_root=binding.worktree.path,
                model=route.model,
                agent_id=definition.id,
                agent_version=definition.version,
                prompt_builder=ContextPromptBuilder(context_resolver),
                environment=environment,
                runner=runner,
                initial_workspace_admission=self.seed
                if definition.role is AgentRole.CODER
                else None,
            ),
            runner,
        )


def test_public_chained_reapply_preserves_complete_ancestor_inputs_and_independent_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the provider fixture ports change. The shared fixture retains exact DB
    # admission, all native stores, real subprocess ownership and cleanup fences.
    monkeypatch.setattr(facts_window_fixture, "OfflineRecoveryClients", _TwoFileClients)
    monkeypatch.setattr(facts_window_fixture, "offline_failed_codex", _two_file_failed_codex)
    with modern_failed_native_fixture(tmp_path, monkeypatch) as native:
        dsn = native.config.require_mysql_dsn(native.environment)

        def new_host() -> TeamHost:
            return TeamHost(
                config=native.config,
                environment=native.environment,
                structured_clients=_TwoFileClients(),
            )

        host = new_host()
        old_task = native.original.task
        old_tree = Path(native.capture.worktree_path)
        old_bytes = _snapshot(old_tree)
        assert {f.path for f in native.capture.files} == {"hello.txt", _FEATURE}
        assert _FEATURE_DRAFT.strip() in native.capture.patch
        with MySqlTaskRepository(dsn) as repository:
            old_events = repository.list_events(old_task.id)

        plans: list[RecoveryPlan] = []
        plan_files: list[Path] = []
        failed_tasks = [old_task]
        failed_trees: list[tuple[Path, dict[str, bytes]]] = []
        factories: list[_CompleteFactory] = []
        execute = NativeRecoveryEntry.execute

        def final_factory(seed: RecoverySeedService) -> DeliveryRouteAdapterFactory:
            factory = _CompleteFactory(seed)
            factories.append(factory)
            return factory

        def execute_offline(
            entry: NativeRecoveryEntry,
            path: Path,
            *,
            route_factory: Callable[[RecoverySeedService], DeliveryRouteAdapterFactory]
            | None = None,
        ) -> RetryResult:
            assert route_factory is None
            return execute(entry, path, route_factory=final_factory)

        for generation in range(3):
            # A fresh trusted Host reconstructs ancestry from durable authority;
            # an in-memory previous Plan or provider's claims cannot supply it.
            host = new_host()
            recovery = host.recovery_entry()
            source = NativeRecoverySourceReader(
                native.config, native.environment
            ).discover_failed_coder(native.original.source.scope)
            failed = FileProjectDeliveryCheckpointStore(
                Path(native.original.preparation.repository_workspace_root)
                / "state/project-deliveries",
                read_only=True,
            ).current(native.original.source.scope.delivery_id)
            assert failed.task_id == source.task.id
            assert source.source.failed_run_id is not None
            assert source.source.failed_context_id is not None
            if generation == 1:
                provider_calls = tmp_path / "offline-provider-calls.txt"
                before = provider_calls.read_bytes()
                recovery_directory = (
                    Path(native.original.preparation.repository_workspace_root)
                    / "state"
                    / f"recovery-{failed.delivery_id}"
                )
                before_plans = {
                    path.name: path.read_bytes() for path in recovery_directory.glob("plan-*.json")
                }
                with monkeypatch.context() as refused:
                    refused.setattr(
                        "ai_software_engineer.recovery.inherited_input."
                        "read_inherited_invocation_queue",
                        _missing_claim,
                    )
                    with pytest.raises(RecoveryRejected, match="missing claimed queue fact"):
                        recovery.propose(
                            repository_root=str(native.project),
                            delivery_id=failed.delivery_id,
                            failed_run_id=source.source.failed_run_id,
                            failed_context_id=source.source.failed_context_id,
                            input_mode="coder_reapply",
                        )
                assert provider_calls.read_bytes() == before
                assert {
                    path.name: path.read_bytes() for path in recovery_directory.glob("plan-*.json")
                } == before_plans
                print(
                    "inherited-reapply: missing-claim proposal refused before invocation",
                    flush=True,
                )
            plan, path = recovery.propose(
                repository_root=str(native.project),
                delivery_id=failed.delivery_id,
                failed_run_id=source.source.failed_run_id,
                failed_context_id=source.source.failed_context_id,
                input_mode="coder_reapply",
            )
            plans.append(plan)
            plan_files.append(path)
            assert len(plan.inherited_reapply_inputs or ()) == generation
            print(
                f"inherited-reapply: generation {generation + 1} proposed with "
                f"{generation} complete inherited inputs",
                flush=True,
            )
            assert plan.source.task_id == failed_tasks[-1].id
            if generation:
                assert {f.path for f in plan.capture.files} == {"hello.txt"}
                inherited = plan.inherited_reapply_inputs or ()
                assert [p.origin_plan_sha256 for p in inherited] == [
                    p.plan_sha256 for p in plans[:-1]
                ]
                assert len({p.origin_plan_sha256 for p in inherited}) == generation
                assert inherited[0].patch == plans[0].capture.patch
                assert (
                    inherited[0].patch_sha256
                    == hashlib.sha256(plans[0].capture.patch.encode("utf-8")).hexdigest()
                )
                assert _FEATURE_DRAFT.strip() in inherited[0].patch
                for item, origin, origin_file in zip(
                    inherited, plans[:-1], plan_files[:-1], strict=True
                ):
                    origin_store, _ = recovery.open_plan(origin_file)
                    original_invocation = origin_store.get_invocation(origin.plan_sha256)
                    original_context = _context(
                        origin_file, original_invocation.context_manifest_id
                    )
                    original_patch = next(
                        section
                        for section in original_context.sections
                        if section.name == "source:recovery.patch"
                    )
                    assert item.origin_task_id == origin.new_task_id
                    assert (
                        item.origin_context_manifest_id == original_invocation.context_manifest_id
                    )
                    assert item.patch_uri == original_patch.uri
                    assert item.patch == original_patch.content
                    assert item.patch_bytes == len(item.patch.encode("utf-8"))
                assert _FEATURE not in {f.path for f in plan.capture.files}
            proposed = _continue(
                host, ResumeProjectDelivery(delivery_id=plan.source.scope.delivery_id)
            )
            assert proposed.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED
            assert proposed.recovery_plan_sha256 == plan.plan_sha256
            if generation == 2:
                monkeypatch.setattr(NativeRecoveryEntry, "execute", execute_offline)
            # Approval is exact and separate from proposal; public Continue owns
            # allocation, claim, seed admission, Context and the serial execution.
            result = _continue(
                host,
                ResumeProjectDelivery(
                    delivery_id=plan.source.scope.delivery_id,
                    approved_plan_sha256=plan.plan_sha256,
                    approval_reference=f"exact-inherited-input-generation-{generation + 1}",
                ),
            )
            print(
                f"inherited-reapply: generation {generation + 1} completed "
                f"at {result.checkpoint.stage.value}",
                flush=True,
            )
            store, loaded = recovery.open_plan(path)
            assert loaded == plan and store.get_authorization(plan.plan_sha256).decision.approved
            invocation = store.get_invocation(plan.plan_sha256)
            context = _context(path, invocation.context_manifest_id)
            _require_inputs(plan, context)
            if generation < 2:
                assert result.checkpoint.stage is DeliveryStage.BLOCKED
                with MySqlTaskRepository(dsn) as repository:
                    task = repository.get(plan.new_task_id)
                assert task.status is TaskStatus.BLOCKED
                failed_tasks.append(task)
                target = Path(store.get_seed(plan.plan_sha256).capture.worktree_path)
                assert not (target / _FEATURE).exists()
                failed_trees.append((target, _snapshot(target)))
            else:
                assert result.outcome is DeliveryResumeOutcome.RECOVERED
                assert result.checkpoint.stage is DeliveryStage.DONE
                assert result.checkpoint.candidate_revision is not None
                assert len(factories) == 1
                calls = factories[0].calls
                assert [request.role for request in calls] == [
                    AgentRole.CODER,
                    AgentRole.QA,
                    AgentRole.REVIEWER,
                ]
                assert len({request.run_id for request in calls}) == 3
                dispatch = recovery._dispatch_for(store, plan)
                assert len({phase.agent_id for phase in dispatch.phases}) == 3
                assert calls[1].source_revision == calls[2].source_revision
                assert calls[1].source_revision == result.checkpoint.candidate_revision
                with MySqlTaskRepository(dsn) as repository:
                    completed = repository.get(plan.new_task_id)
                    assert completed.status is TaskStatus.DONE
                repeated = _continue(
                    new_host(), ResumeProjectDelivery(delivery_id=plan.source.scope.delivery_id)
                )
                assert repeated.checkpoint == result.checkpoint
                assert len(factories[0].calls) == 3

        assert _snapshot(old_tree) == old_bytes
        assert all(_snapshot(tree) == before for tree, before in failed_trees)
        with MySqlTaskRepository(dsn) as repository:
            assert repository.get(old_task.id) == old_task
            assert repository.list_events(old_task.id) == old_events
            for task in failed_tasks:
                assert repository.get(task.id) == task
