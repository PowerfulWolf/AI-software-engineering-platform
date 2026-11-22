"""Structured Responses calls stream so long generations survive gateway limits."""

from __future__ import annotations

import json

import pytest

from ai_software_engineer.agents.structured import (
    ResponsesStreamFailed,
    responses_provider_payload,
)


def _sse(*events: dict[str, object]) -> bytes:
    return (
        "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        ).encode()
        + b"data: [DONE]\n\n"
    )


COMPLETED = {
    "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"a":1}'}]}],
    "usage": {"input_tokens": 3, "output_tokens": 2},
}


def test_plain_json_is_unchanged() -> None:
    assert responses_provider_payload(json.dumps(COMPLETED).encode()) == COMPLETED


def test_completed_event_carries_the_final_response() -> None:
    body = _sse(
        {"type": "response.created", "response": {"output": []}},
        {"type": "response.output_text.delta", "delta": '{"a"'},
        {"type": "response.output_text.delta", "delta": ":1}"},
        {"type": "response.completed", "response": COMPLETED},
    )
    assert responses_provider_payload(body) == COMPLETED


def test_deltas_are_used_when_completed_event_has_no_output() -> None:
    body = _sse(
        {"type": "response.output_text.delta", "delta": '{"a"'},
        {"type": "response.output_text.delta", "delta": ":1}"},
        {"type": "response.completed", "response": {"output": [], "usage": {"x": 1}}},
    )
    provider = responses_provider_payload(body)
    assert provider["output"][0]["content"][0]["text"] == '{"a":1}'
    assert provider["usage"] == {"x": 1}


@pytest.mark.parametrize("kind", ["response.failed", "response.incomplete", "error"])
def test_failed_stream_is_typed(kind: str) -> None:
    with pytest.raises(ResponsesStreamFailed):
        responses_provider_payload(_sse({"type": kind}))


def test_empty_stream_is_invalid() -> None:
    with pytest.raises(ValueError, match="no output"):
        responses_provider_payload(_sse({"type": "response.created"}))


def test_client_streams_and_falls_back_when_gateway_rejects_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Mapping

    from ai_software_engineer.agents import (
        AgentErrorCode,
        HttpResponse,
        ResponsesStructuredModelClient,
        StructuredModelError,
        structured,
    )

    monkeypatch.setitem(structured._RESPONSES_STREAMING, "enabled", True)
    sent: list[dict[str, object]] = []

    class Gateway:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
        ) -> HttpResponse:
            request = json.loads(body)
            sent.append(request)
            if request.get("stream"):
                return HttpResponse(status_code=400, body=b'{"error":"stream not supported"}')
            return HttpResponse(status_code=200, body=json.dumps(COMPLETED).encode())

    client = ResponsesStructuredModelClient(
        endpoint="https://example.invalid/v1/responses",
        credential="k",
        model="test",
        transport=Gateway(),
    )
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    assert raised.value.code is AgentErrorCode.PROVIDER_UNAVAILABLE and raised.value.transient
    result = client.complete(
        instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1
    )
    assert result.payload == {"a": 1}
    assert [request.get("stream") for request in sent] == [True, None]


def test_client_parses_a_streamed_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections.abc import Mapping

    from ai_software_engineer.agents import HttpResponse, ResponsesStructuredModelClient, structured

    monkeypatch.setitem(structured._RESPONSES_STREAMING, "enabled", True)

    class Gateway:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
        ) -> HttpResponse:
            assert json.loads(body)["stream"] is True
            assert "text/event-stream" in headers["Accept"]
            return HttpResponse(
                status_code=200,
                body=_sse({"type": "response.completed", "response": COMPLETED}),
            )

    client = ResponsesStructuredModelClient(
        endpoint="https://example.invalid/v1/responses",
        credential="k",
        model="test",
        transport=Gateway(),
    )
    result = client.complete(
        instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1
    )
    assert result.payload == {"a": 1}


def test_quota_exhausted_gateway_falls_back_to_the_next_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Mapping

    from ai_software_engineer.agents import (
        AgentErrorCode,
        FallbackStructuredModelClient,
        HttpResponse,
        ResponsesStructuredModelClient,
        StructuredModelError,
        StructuredModelResult,
        StructuredModelRoute,
        structured,
    )

    monkeypatch.setitem(structured._RESPONSES_STREAMING, "enabled", False)

    class Gateway:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
        ) -> HttpResponse:
            return HttpResponse(
                status_code=403,
                body=b'{"error":{"message":"Insufficient user quota, remaining quota: -0.01"}}',
            )

    primary = ResponsesStructuredModelClient(
        endpoint="https://example.invalid/v1/responses",
        credential="k",
        model="gpt",
        transport=Gateway(),
    )
    with pytest.raises(StructuredModelError) as raised:
        primary.complete(instructions="x", input_payload={}, output_schema={}, timeout_seconds=1)
    assert raised.value.code is AgentErrorCode.QUOTA_EXHAUSTED
    assert raised.value.transient is False

    class Local:
        calls = 0

        def complete(self, **_: object) -> StructuredModelResult:
            Local.calls += 1
            return StructuredModelResult(payload={"a": 1}, duration_ms=1)

    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute(provider="codex", model="gpt", client=primary),
            StructuredModelRoute(provider="claude", model="opus", client=Local()),
        )
    )
    result = client.complete(
        instructions="x", input_payload={}, output_schema={}, timeout_seconds=1
    )
    assert result.payload == {"a": 1} and Local.calls == 1


def test_invalid_output_does_not_fall_back() -> None:
    from ai_software_engineer.agents import AgentErrorCode, StructuredModelError
    from ai_software_engineer.agents.structured import _allows_fallback

    assert not _allows_fallback(
        StructuredModelError(AgentErrorCode.INVALID_OUTPUT, "bad", transient=False)
    )
    assert _allows_fallback(
        StructuredModelError(AgentErrorCode.AUTHENTICATION_ERROR, "denied", transient=False)
    )
