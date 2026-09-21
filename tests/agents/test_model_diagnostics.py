from __future__ import annotations

import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.message import Message
from io import BytesIO
from pathlib import Path
from threading import Barrier
from urllib.error import HTTPError

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.agents.model_diagnostics import (
    ModelCallDiagnostic,
    capture_model_calls,
    model_call_phase,
)
from ai_software_engineer.agents.openai_compatible import HttpResponse, UrllibHttpTransport
from ai_software_engineer.agents.structured import (
    FallbackStructuredModelClient,
    ResponsesStructuredModelClient,
    StructuredModelError,
    StructuredModelResult,
    StructuredModelRoute,
)


class Transport:
    def __init__(self, status: int, request_id: str) -> None:
        self.status, self.request_id = status, request_id

    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        return HttpResponse(
            status_code=self.status,
            body=b'{"output_text":"{\\"ok\\":true}"}'
            if self.status == 200
            else b"<html>504</html>",
            request_id=self.request_id,
            correlation_id="correlation-test",
        )


@pytest.mark.parametrize("last_status", [200, 504])
def test_all_routes_keep_safe_http_diagnostics(last_status: int) -> None:
    calls: list[ModelCallDiagnostic] = []
    client = FallbackStructuredModelClient(
        tuple(
            StructuredModelRoute(
                provider="hdl",
                model=model,
                client=ResponsesStructuredModelClient(
                    endpoint="https://example.invalid/v1",
                    api_key="private-key",
                    model=model,
                    transport=Transport(status, request_id),
                ),
            )
            for model, status, request_id in (
                ("primary", 504, "req-primary"),
                ("backup", last_status, "private-key"),
            )
        )
    )
    with capture_model_calls(calls.append), model_call_phase("knowledge_intent"):
        if last_status == 200:
            client.complete(
                instructions="secret prompt", input_payload={}, output_schema={}, timeout_seconds=3
            )
        else:
            with pytest.raises(StructuredModelError):
                client.complete(
                    instructions="secret prompt",
                    input_payload={},
                    output_schema={},
                    timeout_seconds=3,
                )
    assert [call.model for call in calls] == ["primary", "backup"]
    assert [call.route_index for call in calls] == [1, 2]
    assert [call.http_status for call in calls] == [504, last_status]
    assert calls[0].request_id == "req-primary"
    assert calls[1].request_id is None
    assert calls[0].invocation_id == calls[1].invocation_id
    assert all(call.duration_ms >= 0 and call.phase == "knowledge_intent" for call in calls)
    assert calls[-1].outcome == ("SUCCEEDED" if last_status == 200 else "FAILED")
    assert "private-key" not in str(calls) and "secret prompt" not in str(calls)


def test_urllib_retains_only_allowlisted_gateway_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = Message()
    headers["X-Request-ID"] = "req-504"
    headers["X-Correlation-ID"] = "https://private.invalid/token=private-key"
    headers["Set-Cookie"] = "private-key"

    def fail(*args: object, **kwargs: object) -> None:
        raise HTTPError("https://example.invalid", 504, "Gateway timeout", headers, BytesIO(b"504"))

    monkeypatch.setattr("ai_software_engineer.agents.openai_compatible.urlopen", fail)
    response = UrllibHttpTransport().post("https://example.invalid", {}, b"{}", 1)
    assert response.status_code == 504
    assert response.request_id == "req-504"
    assert response.correlation_id is None
    assert "private-key" not in repr(response)


def test_timeout_has_no_invented_http_response_and_phase_resets() -> None:
    class TimeoutTransport:
        def post(self, *args: object, **kwargs: object) -> HttpResponse:
            raise TimeoutError("private network details")

    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute(
                provider="hdl",
                model="model-test",
                client=ResponsesStructuredModelClient(
                    endpoint="https://example.invalid",
                    api_key="private-key",
                    model="model-test",
                    transport=TimeoutTransport(),
                ),
            ),
        )
    )
    calls: list[ModelCallDiagnostic] = []
    with capture_model_calls(calls.append):
        with pytest.raises(StructuredModelError), model_call_phase("knowledge_assessment"):
            client.complete(instructions="", input_payload={}, output_schema={}, timeout_seconds=1)
        with pytest.raises(StructuredModelError):
            client.complete(instructions="", input_payload={}, output_schema={}, timeout_seconds=1)
    assert [call.phase for call in calls] == ["knowledge_assessment", "stage_reply"]
    assert all(call.http_status is None and call.request_id is None for call in calls)
    assert all(call.error_code == "TIMEOUT" for call in calls)
    assert "private network details" not in str(calls)


def test_parallel_observer_scopes_do_not_mix_calls() -> None:
    barrier = Barrier(2)

    def run(model: str) -> list[ModelCallDiagnostic]:
        calls: list[ModelCallDiagnostic] = []
        client = FallbackStructuredModelClient(
            (
                StructuredModelRoute(
                    provider="hdl",
                    model=model,
                    client=ResponsesStructuredModelClient(
                        endpoint="https://example.invalid",
                        api_key="private-key",
                        model=model,
                        transport=Transport(200, "req-test"),
                    ),
                ),
            )
        )
        with capture_model_calls(calls.append):
            barrier.wait(timeout=5)
            client.complete(instructions="", input_payload={}, output_schema={}, timeout_seconds=1)
        return calls

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(run, ("one", "two")))
    assert [call.model for call in first] == ["one"]
    assert [call.model for call in second] == ["two"]


def test_image_filter_preserves_configured_route_position(tmp_path: Path) -> None:
    class Client:
        def complete(self, **kwargs: object) -> StructuredModelResult:
            return StructuredModelResult(payload={}, duration_ms=1)

    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute(
                provider="test", model="text", client=Client(), supports_images=False
            ),
            StructuredModelRoute(provider="test", model="vision", client=Client()),
        )
    )
    calls: list[ModelCallDiagnostic] = []
    with capture_model_calls(calls.append):
        client.complete(
            instructions="",
            input_payload={},
            output_schema={},
            timeout_seconds=1,
            input_images=(tmp_path / "image.png",),
        )
    assert [(call.model, call.route_index) for call in calls] == [("vision", 2)]


def test_model_call_schema_matches_typed_contract() -> None:
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/model-call-diagnostic.schema.json").read_text()
    )
    assert {key: value for key, value in schema.items() if key not in {"$id", "$schema"}} == (
        ModelCallDiagnostic.model_json_schema()
    )
    payload = ModelCallDiagnostic(
        invocation_id="a" * 32,
        route_index=1,
        started_at=datetime.now(UTC),
        phase="stage_reply",
        provider="test",
        model="test",
        reasoning_effort="medium",
        duration_ms=42,
        outcome="SUCCEEDED",
        http_status=200,
        request_id="req-200",
    ).to_wire()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(payload)
    assert ModelCallDiagnostic.model_validate(payload).to_wire() == payload
    for key, value in (
        ("duration_ms", -1),
        ("route_index", 0),
        ("http_status", 999),
        ("request_id", "https://example.invalid/token"),
        ("phase", "unknown"),
        ("unexpected", "extra"),
    ):
        invalid = {**payload, key: value}
        assert list(validator.iter_errors(invalid)), key
        with pytest.raises(ValidationError):
            ModelCallDiagnostic.model_validate(invalid)
