"""Sealed route facts, rather than empty containers, identify terminal recovery."""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
    AgentRunStatus,
    FileModelRouteAttemptStore,
    ModelRouteAttempt,
)
from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import Task, TaskStatus
from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.recovery import native
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import NOW, make_task


@dataclass(frozen=True)
class DiscoveryFixture:
    reader: native.NativeRecoverySourceReader
    scope: RecoveryScope
    task: Task
    root: Path
    inspected: list[tuple[RecoveryScope, str, str]]
    source: native.NativeRecoverySource

    def route(
        self,
        run_id: str = "run_current_terminal",
        *,
        task_id: str | None = None,
        attempt: int = 5,
        route_index: int = 1,
        fallback: bool = False,
    ) -> ModelRouteAttempt:
        request = _coder_request().model_copy(
            update={
                "task_id": task_id or self.task.id,
                "run_id": run_id,
                "attempt": attempt,
                "source_revision": self.task.base_ref,
            }
        )
        return ModelRouteAttempt.create(
            request=request,
            route_index=route_index,
            provider="offline",
            model="offline",
            started_at=NOW,
            completed_at=NOW,
            fallback=fallback,
            result=AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.TIMED_OUT if fallback else AgentRunStatus.FAILED,
                error=AgentFailure(
                    code=AgentErrorCode.TIMEOUT if fallback else AgentErrorCode.POLICY_VIOLATION,
                    message="offline terminal result",
                    transient=fallback,
                ),
            ),
        )

    def discover(self) -> native.NativeRecoverySource:
        return self.reader.discover_failed_coder(self.scope)


@pytest.fixture
def discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DiscoveryFixture:
    scope = RecoveryScope(
        team_id="team_discovery",
        repository_id="repository_discovery",
        delivery_id="delivery_discovery",
        repository_root=str(tmp_path / "project"),
    )
    task = make_task().model_copy(
        update={
            "repository": scope.repository_root,
            "base_ref": "a" * 40,
            "status": TaskStatus.BLOCKED,
            "max_attempts": 6,
            "attempts": 5,
            "branch_name": "ai/feature/retained-discovery",
        }
    )
    sidecar = tmp_path / "sidecar"
    root = model_route_root(sidecar)
    root.mkdir(parents=True)
    project = SimpleNamespace(
        requirements_root=tmp_path / "requirements",
        manifest=SimpleNamespace(project_id="project_discovery"),
    )
    team = SimpleNamespace(
        project_registry=lambda: SimpleNamespace(
            locate_repository=lambda _: (project, SimpleNamespace(root=sidecar))
        )
    )
    checkpoint = ProjectDeliveryCheckpoint.model_construct(
        delivery_id=scope.delivery_id,
        task_id=task.id,
        task_status=task.status,
        task_revision=6,
    )
    monkeypatch.setattr(TeamWorkspace, "initialize", lambda *args, **kwargs: team)
    monkeypatch.setattr(native, "_require_native_active", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        native,
        "FileProjectDeliveryCheckpointStore",
        lambda *args, **kwargs: SimpleNamespace(list=lambda _: (checkpoint,)),
    )
    reader = native.NativeRecoverySourceReader(
        ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            team_id=scope.team_id,
            model_routes=(
                ProviderRouteConfig(
                    provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        {},
    )
    monkeypatch.setattr(reader, "_parent_journal", lambda _: None)
    monkeypatch.setattr(reader, "_sql", lambda *args, **kwargs: (task, 6, None, None, ()))
    inspected: list[tuple[RecoveryScope, str, str]] = []
    # This test owns discovery only. The selected identity still must pass the
    # unchanged native source/Context/stop/workspace gates in the real composition.
    source = cast(native.NativeRecoverySource, object())

    def inspect(scope: RecoveryScope, run_id: str, context_id: str) -> native.NativeRecoverySource:
        inspected.append((scope, run_id, context_id))
        return source

    monkeypatch.setattr(reader, "_inspect", inspect)
    return DiscoveryFixture(reader, scope, task, root, inspected, source)


def snapshot(root: Path) -> tuple[tuple[str, bytes | None], ...]:
    return tuple(
        (str(path.relative_to(root)), path.read_bytes() if path.is_file() else None)
        for path in sorted(root.rglob("*"))
    )


@pytest.mark.parametrize("empty_count", [0, 1, 3])
def test_empty_run_containers_do_not_hide_the_unique_current_terminal_route(
    discovery: DiscoveryFixture, empty_count: int
) -> None:
    for number in range(empty_count):
        (discovery.root / f"run_unsealed_{number:02d}").mkdir()
    current = discovery.route()
    FileModelRouteAttemptStore(discovery.root).append(current)
    before = snapshot(discovery.root)

    assert discovery.discover() is discovery.source

    assert discovery.inspected == [
        (discovery.scope, current.run_id, current.result.context_manifest_id)
    ]
    assert snapshot(discovery.root) == before


@pytest.mark.parametrize("current", [False, True])
def test_empty_containers_do_not_supply_a_missing_or_fallback_only_terminal_route(
    discovery: DiscoveryFixture, current: bool
) -> None:
    (discovery.root / "run_unsealed_empty").mkdir()
    if current:
        FileModelRouteAttemptStore(discovery.root).append(discovery.route(fallback=True))
    with pytest.raises(RecoveryRejected, match="missing, unsafe or ambiguous"):
        discovery.discover()
    assert discovery.inspected == []


@pytest.mark.parametrize(
    "problem",
    ["unknown_file", "temporary_file", "subdirectory", "corrupt_json", "foreign_run", "symlink"],
)
def test_nonempty_unsealed_or_corrupt_run_directory_is_still_rejected(
    discovery: DiscoveryFixture, problem: str
) -> None:
    FileModelRouteAttemptStore(discovery.root).append(discovery.route())
    other = discovery.root / "run_other_terminal"
    other.mkdir()
    if problem in {"unknown_file", "temporary_file"}:
        name = "unknown.txt" if problem == "unknown_file" else ".ase-route-interrupted"
        (other / name).write_text("unsealed content")
    elif problem == "subdirectory":
        (other / "unknown").mkdir()
    elif problem == "corrupt_json":
        (other / "01.json").write_text("{}")
    elif problem == "foreign_run":
        (other / "01.json").write_text(discovery.route().model_dump_json())
    else:
        (other / "unsealed-link").symlink_to(discovery.root / "run_current_terminal/01.json")
    with pytest.raises(RecoveryRejected, match="missing, unsafe or ambiguous") as error:
        discovery.discover()
    assert discovery.inspected == []
    if problem in {"unknown_file", "temporary_file", "subdirectory", "symlink"}:
        assert str(error.value.__cause__) == "nonempty model route directory has no sealed routes"


@pytest.mark.parametrize("problem", ["invalid_run", "symlink", "not_directory"])
def test_empty_container_exception_cannot_bypass_entry_identity_checks(
    discovery: DiscoveryFixture, problem: str
) -> None:
    FileModelRouteAttemptStore(discovery.root).append(discovery.route())
    if problem == "invalid_run":
        (discovery.root / "not_a_run").mkdir()
    elif problem == "symlink":
        empty = discovery.root.parent / "empty"
        empty.mkdir()
        (discovery.root / "run_empty_symlink").symlink_to(empty, target_is_directory=True)
    else:
        (discovery.root / "run_empty_file").touch()
    with pytest.raises(RecoveryRejected, match="missing, unsafe or ambiguous"):
        discovery.discover()
    assert discovery.inspected == []


def test_multiple_current_terminal_runs_are_still_ambiguous(discovery: DiscoveryFixture) -> None:
    store = FileModelRouteAttemptStore(discovery.root)
    store.append(discovery.route())
    store.append(discovery.route("run_duplicate_terminal"))
    (discovery.root / "run_unsealed_empty").mkdir()
    with pytest.raises(RecoveryRejected, match="missing, unsafe or ambiguous"):
        discovery.discover()
    assert discovery.inspected == []


def test_old_attempts_and_other_tasks_do_not_replace_current_terminal_identity(
    discovery: DiscoveryFixture,
) -> None:
    store = FileModelRouteAttemptStore(discovery.root)
    store.append(discovery.route("run_old_attempt", attempt=4))
    store.append(discovery.route("run_foreign_task", task_id="task_other_delivery"))
    current = discovery.route()
    store.append(current)
    (discovery.root / "run_unsealed_empty").mkdir()
    assert discovery.discover() is discovery.source
    assert discovery.inspected == [
        (discovery.scope, current.run_id, current.result.context_manifest_id)
    ]


def test_discovery_preserves_the_selected_native_inspection_failure(
    discovery: DiscoveryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    FileModelRouteAttemptStore(discovery.root).append(discovery.route())
    (discovery.root / "run_unsealed_empty").mkdir()

    def refuse(*args: object) -> native.NativeRecoverySource:
        raise ValueError("selected source stop or Context is not verified")

    monkeypatch.setattr(discovery.reader, "_inspect", refuse)
    with pytest.raises(RecoveryRejected, match="missing, unsafe or ambiguous") as error:
        discovery.discover()
    assert isinstance(error.value.__cause__, ValueError)
    assert str(error.value.__cause__) == "selected source stop or Context is not verified"
