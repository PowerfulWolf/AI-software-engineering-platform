"""Keep real Product checkpoints when structured execution fails before its reply."""

import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.agents import (
    CodexCliStructuredModelClient,
    FallbackStructuredModelClient,
    StructuredModelClient,
    StructuredModelRoute,
)
from ai_software_engineer.domain import TeamRole
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.web_console import (
    ConsoleOperationStatus,
    ContinueDeliveryIntent,
    CreateRequirementIntent,
    FileConsoleOperationStore,
    ProductReplyIntent,
)
from tests.manager.test_directory_scope import repository
from tests.web_console.test_git_baseline import _console


class _Clients:
    def for_project(
        self, repository_root: Path, role: TeamRole = TeamRole.PRODUCT
    ) -> StructuredModelClient:
        assert role is TeamRole.PRODUCT
        return FallbackStructuredModelClient(
            (
                StructuredModelRoute(
                    "codex",
                    "test-product",
                    CodexCliStructuredModelClient(
                        repository_root=repository_root,
                        model="test-product",
                        executable="offline-codex",
                        reasoning_effort="high",
                    ),
                    "high",
                ),
            )
        )


@pytest.mark.parametrize("failure_phase", ["auth", "intent_schema", "reply_schema"])
def test_failed_product_reply_explains_cause_and_resumes_retained_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_phase: str
) -> None:
    code = repository(tmp_path / "code")
    console, entry = _console(tmp_path)
    monkeypatch.setattr(entry.backend, "clients", _Clients())
    console.submit(
        CreateRequirementIntent(
            project_id="project_test", name="Settings", repository_roots=(str(code),)
        ),
        idempotency_key="create-product-failure",
    )
    created = console.run_once()
    assert created is not None and created.result is not None
    cursor = created.result
    assert cursor.delivery_id is not None and cursor.checkpoint_sha256 is not None
    failed = True
    calls: list[str] = []
    original_run = subprocess.run

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] != "offline-codex":
            return original_run(command, **kwargs)  # type: ignore[call-overload,no-any-return]
        schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text())
        calls.append(schema["title"])
        if failed and failure_phase == "auth":
            return subprocess.CompletedProcess(
                command, 1, "PRIVATE PROMPT CONTENT", "Error: authentication expired; login again"
            )
        payload = (
            {"queries": []}
            if schema["title"] == "KnowledgeIntent"
            else {"action": "clarify", "summary": "Confirm scope", "questions": ["Which tab?"]}
        )
        if failed and (
            (failure_phase == "intent_schema" and schema["title"] == "KnowledgeIntent")
            or (failure_phase == "reply_schema" and schema["title"] == "ProductDraft")
        ):
            payload = {"unexpected": "PRIVATE PROMPT CONTENT"}
        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("ai_software_engineer.agents.structured.subprocess.run", run)
    console.submit(
        ProductReplyIntent(
            project_id="project_test",
            delivery_id=cursor.delivery_id,
            expected_checkpoint_sha256=cursor.checkpoint_sha256,
            message="Remove the account filter label.",
        ),
        idempotency_key="reply-product-failure",
    )
    result = console.run_once()
    assert result is not None and result.status is ConsoleOperationStatus.FAILED
    expected_code = (
        "MODEL_AUTHENTICATION_ERROR" if failure_phase == "auth" else "MODEL_INVALID_OUTPUT"
    )
    assert result.error_code == expected_code, result.error_summary
    assert result.error_summary is not None
    if failure_phase == "auth":
        assert "authentication expired" in result.error_summary
        assert "test-product" in result.error_summary and "high" in result.error_summary
        assert "知识检索意图" in result.error_summary
    else:
        assert "未通过结构校验" in result.error_summary
    assert "PRIVATE PROMPT CONTENT" not in result.error_summary
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/console-operation.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(result.to_wire())
    persisted = entry.journal.current(cursor.delivery_id)
    assert persisted is not None and persisted.stage is JointStage.PRODUCT_DISCOVERY
    assert len(persisted.dialogue) == 1
    baseline = persisted.scope
    assert calls == (
        ["KnowledgeIntent", "ProductDraft"]
        if failure_phase == "reply_schema"
        else ["KnowledgeIntent"]
    )

    failed = False
    console.submit(
        ContinueDeliveryIntent(
            project_id="project_test",
            delivery_id=cursor.delivery_id,
            expected_checkpoint_sha256=persisted.checkpoint_sha256,
        ),
        idempotency_key="resume-product-failure",
    )
    resumed = console.run_once()
    assert resumed is not None and resumed.status is ConsoleOperationStatus.SUCCEEDED
    current = entry.journal.current(cursor.delivery_id)
    assert current is not None and current.stage is JointStage.WAITING_PRODUCT_REPLY
    assert current.scope == baseline
    assert [turn.speaker for turn in current.dialogue] == ["user", "product"]
    assert current.dialogue[0] == persisted.dialogue[0]
    assert current.approval is None and current.children == ()
    reopened = FileConsoleOperationStore(
        tmp_path / "operations", team_id=entry.team.manifest.team_id
    )
    assert reopened.get(result.operation_id) == result
