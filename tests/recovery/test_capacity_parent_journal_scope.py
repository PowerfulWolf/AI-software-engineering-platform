"""Capacity parent observations reuse decoding while rereading complete histories."""

from __future__ import annotations

import hashlib
import json
import os
import weakref
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ai_software_engineer.context.execution_baseline import ExecutionBaselineContext
from ai_software_engineer.context.models import ContextBudget, ContextBundle, ContextSection
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    NetworkAccess,
    ProductSpecApproval,
    TaskStatus,
)
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.multi_directory.history_observation import (
    NativeHistoryJournal,
    NativeRequirementPrefix,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.recovery import context_capacity as module
from ai_software_engineer.recovery.baseline_source import (
    LEGACY_CAPACITY_REASON,
    RecoveryBaselineEpoch,
)
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.native import NativeApprovedStages, _parent
from ai_software_engineer.team_workspace import TeamWorkspace, _read_regular
from tests.domain.factories import NOW, make_plan_artifact, make_state_event, make_task
from tests.e2e.test_delivery_checkpoint import _checkpoint, _full_fields
from tests.manager.test_contracts import stage_chain
from tests.manager.test_terminal_candidate_reconstruction import _binding
from tests.orchestration.test_native_continuation import claim
from tests.team_view.test_joint_history_snapshot import _fixture as joint_fixture


@dataclass
class Fixture:
    reader: module.LegacyContextCapacitySourceReader
    scope: RecoveryScope
    journal: JointJournal
    current: JointCheckpoint
    sql: Mock
    claims: Mock
    no_start: Mock
    captures: Mock


def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fixture:
    """Real parent/retirement stores; other recovery facts use explicit offline ports."""
    console, project, journal, current = joint_fixture(tmp_path)
    stages_root = tmp_path / "stages"
    stages_root.mkdir()
    prepared, request, product, approved, design, execution = stage_chain(stages_root)
    repository = project.repository_registry().register(prepared.repository_root)
    scope = RecoveryScope(
        team_id=project.team.manifest.team_id,
        repository_id=repository.repository_id,
        repository_root=str(repository.repository_root),
        delivery_id="delivery_capacity_parent_scope",
    )
    task = make_task().model_copy(
        update={
            "repository": scope.repository_root,
            "base_ref": "a" * 40,
            "branch_name": "ai/feature/capacity-parent-journal",
            "status": TaskStatus.BLOCKED,
            "attempts": 2,
        }
    )
    owner = claim(task, 2)
    cp = _checkpoint(
        repository.repository_root,
        **{
            **_full_fields(),
            "delivery_id": scope.delivery_id,
            "repository_id": scope.repository_id,
            "stage": DeliveryStage.BLOCKED,
            "task_id": task.id,
            "task_revision": 3,
            "task_status": TaskStatus.BLOCKED,
            "candidate_revision": None,
            "failed_stage": DeliveryStage.DELIVERING,
            "failure_code": DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
            "failure_summary": module.LEGACY_CAPACITY_SUMMARY,
        },
    )
    FileProjectDeliveryCheckpointStore(repository.root / "state/project-deliveries").put(cp)
    lock_root = repository.root / "state/queue-worker-locks"
    lock_root.mkdir(mode=0o700)
    lock = lock_root / (hashlib.sha256(task.id.encode()).hexdigest() + ".lock")
    lock.touch(mode=0o600)
    patch_body = "retained complete development\n"
    old_binding = _binding(task)
    binding_values: dict[str, object] = {
        **old_binding.to_wire(),
        "scope": {
            **old_binding.scope.to_wire(),
            "team_id": scope.team_id,
            "project_id": project.manifest.project_id,
            "repository_id": scope.repository_id,
            "repository_root": scope.repository_root,
        },
        "retained_patch": {
            "uri": "baseline://complete",
            "sha256": hashlib.sha256(patch_body.encode()).hexdigest(),
            "bytes": len(patch_body.encode()),
        },
    }
    binding = ExecutionBaselineBinding.create(**binding_values)
    permissions = AgentPermissions(
        read_paths=("src/**", "tests/**"),
        write_paths=("src/**", "tests/**"),
        commands=(),
        network=NetworkAccess.NONE,
    )
    policy = json.dumps({**permissions.to_wire(), "denied_paths": []})
    context = ContextBundle(
        context_id="ctx_" + "c" * 64,
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=2,
        source_revision=binding.execution_source_revision,
        sections=(
            ContextSection(
                name="policy",
                uri="policy://original",
                content=policy,
                sha256=hashlib.sha256(policy.encode()).hexdigest(),
                tokens=2,
                priority=0,
            ),
        ),
        budget=ContextBudget(max_input_tokens=100, reserved_output_tokens=99, used_input_tokens=2),
        built_at=NOW,
    )
    value = module.ValidatedCapacityContext(
        claim=module.CapacityContextClaim(
            task_id=task.id,
            work_item_id=owner.work_item.id,
            lease_id=owner.lease.id,
            assignment_id=owner.assignment.id,
            role=AgentRole.CODER,
            attempt=2,
            dispatch_sequence=owner.work_item.dispatch_sequence,
            checkpoint_sequence=owner.work_item.checkpoint_sequence,
        ),
        complete=ExecutionBaselineContext(
            binding=binding, instructions="Complete original input", complete_patch=patch_body
        ),
        available_input_tokens=1,
    )
    terminal = make_state_event(
        from_status=TaskStatus.IMPLEMENTING, to_status=TaskStatus.BLOCKED
    ).model_copy(update={"task_id": task.id, "reason": LEGACY_CAPACITY_REASON, "attempt": 2})
    reader = module.LegacyContextCapacitySourceReader(console.config, {})
    sql = Mock(
        return_value=(task, 3, SimpleNamespace(dispatch_sha256="d" * 64), object(), (terminal,))
    )
    claims = Mock(return_value=owner)
    no_start = Mock()
    captures = Mock(return_value=None)
    monkeypatch.setattr(reader.native, "_sql", sql)
    monkeypatch.setattr(reader, "_claim", claims)
    monkeypatch.setattr(reader, "_context", Mock(return_value=(context, value)))
    monkeypatch.setattr(reader, "_require_original_plan", Mock(return_value=make_plan_artifact()))
    monkeypatch.setattr(reader, "_require_no_start", no_start)
    monkeypatch.setattr(
        module,
        "read_recovery_baseline_epochs",
        Mock(return_value=(RecoveryBaselineEpoch(binding, 2),)),
    )
    monkeypatch.setattr(
        module,
        "read_approved_stages",
        Mock(
            return_value=NativeApprovedStages(
                prepared, product, approved, design, execution, request
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "FileExecutionBaselineStore",
        Mock(
            return_value=SimpleNamespace(
                plan=lambda _: SimpleNamespace(complete_capture=SimpleNamespace(patch=patch_body))
            )
        ),
    )
    monkeypatch.setattr(module, "GitWorktreeManager", Mock())
    monkeypatch.setattr(module, "_capacity_capture", captures)
    return Fixture(reader, scope, journal, current, sql, claims, no_start, captures)


def test_capacity_observation_decodes_parent_prefix_once_but_reads_each_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    paths = tuple(sorted(f.journal.root.glob("delivery_multi_*/*.json")))
    counts: Counter[Path] = Counter()
    preflights: Counter[Path] = Counter()
    read_bytes = Path.read_bytes

    def read(path: Path) -> bytes:
        if path in paths:
            counts[path] += 1
        return read_bytes(path)

    def preflight(path: Path, limit: int) -> bytes:
        if path in paths:
            preflights[path] += 1
        return _read_regular(path, limit)

    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr("ai_software_engineer.recovery.native._read_regular", preflight)
    monkeypatch.setattr(
        "ai_software_engineer.multi_directory.history_observation._read_regular", preflight
    )
    with patch.object(
        JointCheckpoint, "model_validate_json", wraps=JointCheckpoint.model_validate_json
    ) as decode:
        source = f.reader.discover(f.scope)
        assert source.capacity_input is not None
        assert source.capacity_input.patch == "retained complete development\n"
        assert counts == Counter({path: 3 for path in paths})
        assert preflights == counts
        assert decode.call_count == 7, "one ancestor, plus two fresh heads in three observations"
        assert (
            f.sql.call_count,
            f.claims.call_count,
            f.no_start.call_count,
            f.captures.call_count,
        ) == (2, 2, 2, 2)
        f.reader.discover(f.scope)
        assert counts == Counter({path: 6 for path in paths})
        assert preflights == counts
        assert decode.call_count == 14, "the next public observation starts cold"


@pytest.mark.parametrize("fault", ["body", "missing", "symlink", "resealed", "retirement"])
def test_capacity_second_parent_check_rejects_changed_complete_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    seen = 0

    def inspect(
        team: TeamWorkspace,
        cp: ProjectDeliveryCheckpoint,
        approval: ProductSpecApproval,
        *,
        journals: dict[Path, JointJournal] | None = None,
    ) -> tuple[str | None, str | None]:
        nonlocal seen
        result = _parent(team, cp, approval, journals=journals)
        seen += 1
        if seen == 1:
            path = f.journal.directory(f.current.delivery_id) / "000001.json"
            if fault == "body":
                before = path.stat()
                payload = path.read_bytes()
                changed = payload.replace(b"Prepare the repository", b"Prepare the repositors")
                assert changed != payload and len(changed) == len(payload)
                path.write_bytes(changed)
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            elif fault == "missing":
                path.unlink()
            elif fault == "symlink":
                external = tmp_path / "external.json"
                external.write_bytes(path.read_bytes())
                path.unlink()
                path.symlink_to(external)
            elif fault == "retirement":
                (f.journal.root / "retirement.json").write_text("{}")
            else:
                path = f.journal.root / "delivery_multi_retired_snapshot/000001.json"
                prior = JointCheckpoint.model_validate_json(path.read_bytes())
                changed_cp = JointCheckpoint.seal(
                    {**prior.to_wire(), "next_action": "Resealed changed history"}
                )
                path.write_text(changed_cp.model_dump_json())
        return result

    monkeypatch.setattr(module, "_parent", inspect)
    with pytest.raises(RecoveryRejected):
        f.reader.discover(f.scope)


@pytest.mark.parametrize("fail", [False, True])
def test_capacity_journal_decode_scope_is_cleared_even_with_a_retained_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    journals: list[weakref.ReferenceType[JointJournal]] = []
    original = JointJournal.__init__

    def initialize(store: JointJournal, root: Path, *, read_only: bool = False) -> None:
        original(store, root, read_only=read_only)
        if read_only:
            journals.append(weakref.ref(store))

    monkeypatch.setattr(JointJournal, "__init__", initialize)
    if fail:
        f.captures.side_effect = [None, ValueError("changed current capture")]
        with pytest.raises(RecoveryRejected) as rejected:
            f.reader.discover(f.scope)
        assert rejected.value.__cause__ is not None
    else:
        f.reader.discover(f.scope)
    assert journals
    for reference in journals:
        journal = reference()
        assert journal is None or not journal._verified


def test_capacity_final_parent_read_observes_a_new_valid_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    original = NativeHistoryJournal.native_prefix
    sequences: list[int] = []
    reads = 0

    def current(store: NativeHistoryJournal, delivery_id: str) -> NativeRequirementPrefix:
        result = original(store, delivery_id)
        if delivery_id == f.current.delivery_id and result.current is not None:
            sequences.append(result.current.sequence)
        return result

    def inspect(
        team: TeamWorkspace,
        cp: ProjectDeliveryCheckpoint,
        approval: ProductSpecApproval,
        *,
        journals: dict[Path, JointJournal] | None = None,
    ) -> tuple[str | None, str | None]:
        nonlocal reads
        result = _parent(team, cp, approval, journals=journals)
        reads += 1
        if reads == 1:
            appended = JointCheckpoint.seal(
                {
                    **f.current.to_wire(),
                    "sequence": 2,
                    "previous_checkpoint_sha256": f.current.checkpoint_sha256,
                    "next_action": "Fresh parent tail",
                }
            )
            f.journal.append(appended, expected=f.current.checkpoint_sha256)
        return result

    monkeypatch.setattr(NativeHistoryJournal, "native_prefix", current)
    monkeypatch.setattr(module, "_parent", inspect)
    f.reader.discover(f.scope)
    assert sequences[-1] == 2 and 1 in sequences
    assert reads == 2
