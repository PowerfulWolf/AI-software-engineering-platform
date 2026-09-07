"""Append-only recovery persistence, real filesystem and crash/race tests."""

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ai_software_engineer.recovery import (
    FileRecoveryStore,
    RecoveryAuthorization,
    RecoveryConflict,
    RecoveryPlan,
    RecoveryRejected,
)
from ai_software_engineer.recovery.models import digest
from tests.recovery.test_authorization import Human, approval, make_plan, setup_service


def test_read_only_open_does_not_initialize_and_scope_is_durable(tmp_path: Path) -> None:
    plan = make_plan(tmp_path / "project")
    root = tmp_path / "records"
    with pytest.raises(RecoveryRejected):
        FileRecoveryStore(root, scope=plan.source.scope)
    assert not root.exists()
    store = FileRecoveryStore.initialize(root, scope=plan.source.scope)
    store.put_plan(plan)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    assert FileRecoveryStore(root, scope=plan.source.scope).get_plan(plan.plan_sha256) == plan
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    foreign = plan.source.scope.model_copy(update={"company_id": "company_other"})
    with pytest.raises(RecoveryRejected):
        FileRecoveryStore(root, scope=foreign)
    with pytest.raises(RecoveryRejected):
        FileRecoveryStore.initialize(root, scope=foreign)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in root.iterdir())


@pytest.mark.parametrize(
    "problem", ["overlap", "ancestor", "symlink", "parent_symlink", "missing_parent"]
)
def test_invalid_placement_never_writes_project(tmp_path: Path, problem: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    plan = make_plan(project)
    if problem == "overlap":
        root = project / "recovery"
    elif problem == "ancestor":
        root = tmp_path
    elif problem == "missing_parent":
        root = tmp_path / "missing/recovery"
    else:
        link = tmp_path / "link"
        link.symlink_to(project, target_is_directory=True)
        root = link if problem == "symlink" else link / "recovery"
    with pytest.raises(RecoveryRejected):
        FileRecoveryStore.initialize(root, scope=plan.source.scope)
    assert list(project.iterdir()) == []
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    "tamper",
    ["hash", "inner_hash", "duplicate_key", "symlink", "fifo", "root_swap", "scope", "privacy"],
)
def test_corruption_is_not_treated_as_a_missing_record(tmp_path: Path, tamper: str) -> None:
    service, store, plan, _, _, _ = setup_service(tmp_path)
    service.propose(plan)
    root = tmp_path / "recovery"
    path = root / f"plan-{plan.plan_sha256}.json"
    if tamper == "scope":
        (root / "scope.json").write_text("corrupt scope")
    elif tamper == "privacy":
        root.chmod(0o755)
    elif tamper in ("hash", "inner_hash"):
        envelope = json.loads(path.read_text())
        envelope["record"]["target_base_revision"] = "e" * 40
        if tamper == "inner_hash":
            envelope["sha256"] = digest(envelope["record"])
        path.write_text(json.dumps(envelope))
    elif tamper == "duplicate_key":
        path.write_text('{"record":{},"record":{},"sha256":"' + "0" * 64 + '"}')
    elif tamper == "root_swap":
        root.rename(tmp_path / "original")
        root.mkdir(mode=0o700)
    else:
        path.unlink()
        if tamper == "fifo":
            os.mkfifo(path, mode=0o600)
        else:
            outside = tmp_path / "outside"
            outside.write_text("private fixture")
            path.symlink_to(outside)
    with pytest.raises(RecoveryRejected):
        store.get_plan(plan.plan_sha256)
    with pytest.raises(RecoveryRejected):
        store.find_authorization(plan.plan_sha256)


def test_concurrent_different_decisions_have_one_winner(tmp_path: Path) -> None:
    service, store, plan, _, _, _ = setup_service(tmp_path)
    service.propose(plan)

    def publish(index: int) -> str:
        command = approval(plan).model_copy(update={"operation_id": f"decision_{index:03}"})
        record = RecoveryAuthorization.create(command, Human().verify(command))
        writer = FileRecoveryStore(tmp_path / "recovery", scope=plan.source.scope)
        try:
            return writer.put_authorization(record).command.operation_id
        except RecoveryConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(publish, (1, 2)))
    assert results.count("conflict") == 1
    assert store.get_authorization(plan.plan_sha256).command.operation_id in results
    assert not list((tmp_path / "recovery").glob(".pending-*"))


def test_published_receipt_survives_interruption_without_second_human_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, plan, _, _, human = setup_service(tmp_path)
    service.propose(plan)
    original = os.link

    def interrupted_link(
        src: str, dst: str, *, src_dir_fd: int, dst_dir_fd: int, follow_symlinks: bool
    ) -> None:
        original(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )
        raise OSError("simulated crash after publication")

    monkeypatch.setattr(os, "link", interrupted_link)
    with pytest.raises(RecoveryRejected):
        service.authorize(approval(plan))
    monkeypatch.setattr(os, "link", original)
    human.fail = True
    assert service.authorize(approval(plan)) == store.get_authorization(plan.plan_sha256)
    assert human.calls == 1


def test_short_writes_are_completed_and_zero_write_leaves_no_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store, plan, _, _, _ = setup_service(tmp_path)
    original = os.write
    calls = 0

    def short_write(fd: int, data: bytes | memoryview) -> int:
        nonlocal calls
        calls += 1
        return original(fd, data[:3] if calls == 1 else data)

    monkeypatch.setattr(os, "write", short_write)
    assert store.put_plan(plan) == plan
    assert calls >= 2
    next_plan = RecoveryPlan.create(**{**plan.to_wire(), "target_base_revision": "f" * 40})
    monkeypatch.setattr(os, "write", lambda fd, data: 0)
    with pytest.raises(RecoveryRejected):
        store.put_plan(next_plan)
    assert not (tmp_path / "recovery" / f"plan-{next_plan.plan_sha256}.json").exists()
    assert not list((tmp_path / "recovery").glob(".pending-*"))
