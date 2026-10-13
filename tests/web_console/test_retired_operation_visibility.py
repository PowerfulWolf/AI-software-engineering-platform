"""Deletion changes normal history, pagination and ETag while exact audit stays complete."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from ai_software_engineer.multi_directory.service import CreateRequirement, DeleteRequirement
from ai_software_engineer.web_console.core import ProjectConsole
from ai_software_engineer.web_console.models import (
    ConsoleCommandResult,
    CreateRequirementIntent,
    ProductReplyIntent,
)
from ai_software_engineer.web_console.requirement_visibility import (
    ProductionRequirementOperationVisibility,
)
from ai_software_engineer.web_console.store import FileConsoleOperationStore
from ai_software_engineer.web_console.summary_models import (
    OperationSummaryQuery,
    StaleOperationCursor,
)
from ai_software_engineer.web_console.transport import create_console_app
from tests.manager.test_requirement_retirement import _service
from tests.web_console.test_transport import _Reader


def test_retirement_invalidates_pages_and_removes_create_active_and_count_without_erasing_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, root = _service(tmp_path, monkeypatch)
    first = service.create(
        CreateRequirement(name="First", repository_roots=(str(root),))
    ).checkpoint
    other = service.create(
        CreateRequirement(name="Other", repository_roots=(str(root),))
    ).checkpoint
    store = FileConsoleOperationStore(
        tmp_path / "operations",
        team_id=service.team.manifest.team_id,
        visibility=ProductionRequirementOperationVisibility(service.team),
    )
    operations = []
    for index, checkpoint in enumerate((first, other)):
        queued = store.submit(
            intent=CreateRequirementIntent(
                name=checkpoint.title,
                project_id=checkpoint.project_id,
                repository_roots=(str(root),),
            ),
            idempotency_key=f"create-{index}",
            requested_at=datetime.now(UTC),
        )
        running = store.claim_next(at=datetime.now(UTC))
        assert running is not None
        operations.append(
            store.succeed(
                queued.operation_id,
                expected=running.operation_sha256,
                result=ConsoleCommandResult(
                    project_id=checkpoint.project_id,
                    delivery_id=checkpoint.delivery_id,
                    checkpoint_sha256=checkpoint.checkpoint_sha256,
                    stage="READY_FOR_DISCUSSION",
                    next_action="Discuss",
                ),
                at=datetime.now(UTC),
            )
        )
    active = store.submit(
        intent=ProductReplyIntent(
            project_id=first.project_id,
            delivery_id=first.delivery_id,
            expected_checkpoint_sha256=first.checkpoint_sha256,
            message="Read only fixture",
        ),
        idempotency_key="active-first",
        requested_at=datetime.now(UTC),
    )
    query = OperationSummaryQuery(project_id=first.project_id, page_size=1)
    before = store.summary_page(query)
    assert before.total_count == 3 and before.next_cursor and before.active
    client = TestClient(
        create_console_app(
            ProjectConsole(store=store, executor=Mock()),
            _Reader(),
            team_id=service.team.manifest.team_id,
        ),
        base_url="http://127.0.0.1:8765",
    )
    response = client.get(
        "/api/v1/operation-summaries", params={"project_id": first.project_id, "page_size": 1}
    )
    service.delete_requirement(
        DeleteRequirement(
            delivery_id=first.delivery_id, expected_checkpoint_sha256=first.checkpoint_sha256
        )
    )
    after = store.summary_page(query)
    assert after.total_count == 1 and not after.active and not after.next_cursor
    assert after.items[0].operation_id == operations[1].operation_id
    assert after.inventory_sha256 != before.inventory_sha256
    with pytest.raises(StaleOperationCursor):
        store.summary_page(query.model_copy(update={"cursor": before.next_cursor}))
    changed = client.get(
        "/api/v1/operation-summaries",
        params={"project_id": first.project_id, "page_size": 1},
        headers={"If-None-Match": response.headers["etag"]},
    )
    assert changed.status_code == 200 and changed.json()["total_count"] == 1
    assert client.get("/api/v1/operations/" + operations[0].operation_id).status_code == 200
    assert store.get(active.operation_id) == active
    assert store.list_current() == (operations[1],)
    path = store.root / operations[0].operation_id / "000001.json"
    path.write_bytes(path.read_bytes().replace(b"team_test", b"team_fail"))
    assert client.get("/api/v1/operation-summaries").status_code == 503
