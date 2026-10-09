"""Read-only exact pending kickoff facts remain actionable after a restart."""

from contextlib import closing
from datetime import timedelta

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.domain import WorkItemStatus
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.team_view.models import ScopeView, TaskView
from ai_software_engineer.team_view.queue_reader import (
    read_pending_baseline_continuation,
    read_role_queue,
)
from ai_software_engineer.team_view.reader import _with_execution_state
from tests.work_queue.test_baseline_pause_mysql import PausedFixture
from tests.work_queue.test_baseline_pause_mysql import paused as paused
from tests.work_queue.test_mysql_queue import dispatcher

pytestmark = pytest.mark.mysql


def test_only_exact_unstarted_release_exposes_saved_continue_in_read_only_snapshot(
    paused: PausedFixture,
) -> None:
    authority = paused.authorization()
    baselines = paused.git.service.store
    baselines.records.put("baseline-continuations", paused.binding.binding_sha256, authority)
    readonly = FileExecutionBaselineStore(baselines.root, read_only=True)
    saved = {path: path.read_bytes() for path in baselines.root.iterdir() if path.is_file()}

    def read() -> bool:
        with (
            closing(open_mysql_connection(paused.queue._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            connection.begin()
            try:
                views = read_role_queue(
                    cursor,
                    task_id=authority.task_id,
                    repository_id=authority.scope.repository_id,
                    allocation_sha256="a" * 64,
                    now=paused.now + timedelta(seconds=6),
                )
                projected = read_pending_baseline_continuation(
                    cursor,
                    task=paused.repository.get(authority.task_id),
                    task_revision=paused.repository.current_revision(authority.task_id),
                    scope=authority.scope,
                    baselines=readonly,
                    views=views,
                )
                hints = tuple(
                    view.pending_baseline_continuation
                    for view in projected
                    if view.pending_baseline_continuation is not None
                )
                assert hints in ((), (authority,))
                if hints:
                    task_view = TaskView(
                        id="delivery_pending_fixture",
                        project_id=authority.scope.project_id,
                        request_id="delivery_pending_fixture",
                        task_id=authority.task_id,
                        task_revision=authority.task_revision,
                        task_intent_sha256=authority.task_intent_sha256,
                        title="Saved continuation",
                        scope=ScopeView(
                            root=authority.scope.repository_root, selected_paths=(".",)
                        ),
                        status="IMPLEMENTING",
                        checkpoint_stage="DELIVERING",
                        terminal=False,
                        last_activity=paused.now,
                        next_action="Old wait advice",
                        role_queue=projected,
                    )
                    execution = _with_execution_state(task_view).execution
                    assert execution is not None
                    assert execution.state == "WAITING"
                    assert execution.reason_code == "BASELINE_CONTINUATION_PENDING"
                    assert execution.action_required
                    assert "继续已授权执行" in execution.next_action
                return bool(hints)
            finally:
                connection.rollback()

    assert not read()  # An authorization file alone cannot fabricate SQL release.
    assert paused.queue.release_baseline_pause(paused.binding, authority)
    assert read()
    assert {path: path.read_bytes() for path in baselines.root.iterdir() if path.is_file()} == saved
    claim = dispatcher(paused.queue, "worker_read_pending").tick(
        now=paused.now + timedelta(seconds=6), work_item_id=authority.work_item_id
    )
    assert claim.claim is not None and claim.lease_owner_token is not None
    assert not read()
    paused.queue.wait(
        authority.work_item_id,
        lease_id=claim.claim.lease.id,
        owner_token=claim.lease_owner_token,
        status=WorkItemStatus.WAITING_DEPENDENCY,
        reason="new execution needs new prerequisite",
        now=paused.now + timedelta(seconds=7),
    )
    assert not read()
