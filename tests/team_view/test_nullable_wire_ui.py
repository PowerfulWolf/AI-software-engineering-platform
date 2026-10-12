"""Cross-language UI contract uses canonical Python wire, not handwritten JS nulls."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.team_view.models import ScopeView, TaskView
from ai_software_engineer.team_view.read_models import (
    RequestSummary,
    TaskDetail,
    TaskSummary,
    TeamDetailSource,
    TeamSummary,
)


def test_shipped_ui_reads_real_omitted_nullable_summary_and_details(tmp_path: Path) -> None:
    now = datetime(2026, 10, 12, tzinfo=UTC)
    owner = "delivery_parent"
    request_source = TeamDetailSource(
        team_id="team_test",
        project_id="project_test",
        request_id=owner,
        resource_kind="request",
        resource_id=owner,
        requirement_checkpoint_sha256="a" * 64,
        resource_checkpoint_sha256="a" * 64,
        resource_state_sha256="b" * 64,
    )
    request = RequestSummary(
        id=owner,
        project_id="project_test",
        title="Demand",
        stage="DELIVERING",
        scopes=(),
        next_action="Read records",
        checkpoint_sha256="a" * 64,
        detail_source=request_source,
    )
    tasks = []
    details = []
    for variant in (
        "legacy",
        "candidate_verification",
        "delivery",
        "remediation",
        "legacy_remediation",
    ):
        verification = variant == "candidate_verification"
        identified = variant in {"delivery", "remediation"}
        work_kind = (
            "delivery"
            if variant == "legacy"
            else "remediation"
            if variant == "legacy_remediation"
            else variant
        )
        identity = "verification_" + "c" * 32 if verification else "delivery_" + variant
        task = TaskView.model_validate(
            {
                "id": identity,
                "project_id": "project_test",
                "request_id": owner,
                "work_kind": work_kind,
                "task_id": "task_" + variant if verification or identified else None,
                "task_revision": 0 if identified else None,
                "task_intent_sha256": "d" * 64 if identified else None,
                "source_task_id": "task_original" if verification else None,
                "plan_sha256": "c" * 64 if verification else None,
                "title": variant,
                "scope": ScopeView(root="/fixture", selected_paths=(".",)),
                "status": "IMPLEMENTING",
                "checkpoint_stage": "IMPLEMENTING",
                "terminal": False,
                "last_activity": now,
                "next_action": "Read records",
            }
        )
        source = TeamDetailSource(
            team_id="team_test",
            project_id=task.project_id,
            request_id=owner,
            resource_kind="task",
            resource_id=task.id,
            requirement_checkpoint_sha256="a" * 64,
            resource_checkpoint_sha256="b" * 64,
            resource_state_sha256="e" * 64,
            work_kind=task.work_kind,
            task_id=task.task_id,
            task_revision=task.task_revision,
            task_intent_sha256=task.task_intent_sha256,
            source_task_id=task.source_task_id,
            verification_plan_sha256=task.plan_sha256,
        )
        summary = TaskSummary.model_validate(
            {key: value for key, value in task.to_wire().items() if key in TaskSummary.model_fields}
            | {"detail_source": source}
        )
        tasks.append(summary)
        details.append(TaskDetail(as_of=now, scope=source, resource=task).to_wire())
    summary = TeamSummary(
        as_of=now,
        team_id="team_test",
        team_name="Test",
        selected_project_id="project_test",
        requests=(request,),
        tasks=tuple(tasks),
    ).to_wire()
    # Establish the actual failure-triggering serializer shape before JS execution.
    assert "task_id" not in tasks[0].to_wire()["detail_source"]
    assert "task_revision" not in tasks[1].to_wire()["detail_source"]
    fixture = tmp_path / "nullable-wire.json"
    fixture.write_text(json.dumps({"summary": summary, "details": details}))
    result = subprocess.run(
        ["node", "tests/team_view/fixtures/nullable-wire.cjs", str(fixture)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
