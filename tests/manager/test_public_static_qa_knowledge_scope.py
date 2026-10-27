"""The public static-QA recovery consults its exact proof-only scope."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import StructuredModelResult
from tests.manager import test_public_static_qa_missing_entry as static_qa_case
from tests.manager.test_production_backend import _ScriptedStructuredClient
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn


@pytest.mark.mysql
def test_public_static_qa_knowledge_consultation_is_proof_only(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _ScriptedStructuredClient.complete
    scoped_calls: list[Mapping[str, object]] = []

    def assess(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        task_payload = input_payload.get("task")
        if output_schema.get("title") == "KnowledgeIntent" and isinstance(task_payload, dict):
            scope = task_payload.get("run_scope")
            if isinstance(scope, dict):
                assert scope["original_acceptance_status"] == "NOT_RUN"
                assert scope["missing"][0]["path"] == "tests/browser.test.cjs"
                assert "acceptance_criteria" not in task_payload
                assert "context" not in task_payload
                assert "browser, MySQL and live A-to-B" in instructions
                scoped_calls.append(task_payload)
                return StructuredModelResult(payload={"queries": []}, duration_ms=1)
        return original(
            self,
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", assess)
    static_qa_case.test_public_static_qa_decision_yields_proof_bound_fail_and_coder_retry(
        tmp_path, mysql_dsn, monkeypatch, False
    )
    assert len(scoped_calls) == 1
