"""Only complete original trusted CLI JSONL establishes native event facts."""

import hashlib
import json
import tracemalloc
from dataclasses import replace

import pytest

from ai_software_engineer.agents._codex_events import (
    _EVENT_LINE_BYTES,
    CodexJsonEventObserver,
)
from ai_software_engineer.agents.codex_cli import (
    CodexInvocationResult,
    _classify_cli_failure,
    _classify_native_json_failure,
    _safe_cli_failure_detail,
)
from ai_software_engineer.agents.execution import ExecutionAbortReason
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured import _classify_structured_json_failure


def event(message: str = "HTTP 429 fixture", *, kind: str = "turn.failed") -> bytes:
    detail: dict[str, object] = {"message": message}
    if kind == "turn.failed":
        detail = {"error": detail}
    return json.dumps({"type": kind, **detail}, ensure_ascii=False).encode() + b"\n"


def test_split_original_utf8_has_exact_identity_and_not_a_raw_repr() -> None:
    raw = event("错误 HTTP 429 fixture")
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    for byte in raw:
        observer.feed(bytes((byte,)))
    with pytest.raises(ValueError, match="EOF"):
        observer.result()
    observer.finish()
    found = observer.result()
    assert found is not None
    assert found.event_type == "turn.failed" and found.ordinal == 1 and found.complete
    assert found.event_sha256 == hashlib.sha256(raw[:-1]).hexdigest()
    assert found.message == "错误 HTTP 429 fixture"
    assert found.classification.code is AgentErrorCode.RATE_LIMITED
    assert "错误" not in repr(found)


@pytest.mark.parametrize("kind", ["error", "turn.failed"])
def test_only_supported_root_event_messages_are_selected(kind: str) -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    observer.feed(event(kind=kind))
    observer.finish()
    assert observer.result() is not None


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize(
    "bad",
    [
        b"not JSON\n",
        b'{"type":"error","message":"\xff"}\n',
        b'{"type":"error","message":"x","message":"HTTP 401"}\n',
        b'{"type":"item.completed","item":{"a":1,"a":2}}\n',
        b'{"type":"item.completed","n":NaN}\n',
        b'{"type":"item.completed","n":Infinity}\n',
        b'{"type":"item.completed","n":1e9999}\n',
        b'{"type":"item.completed","n":' + b"9" * 5000 + b"}\n",
        b'{"x":' + b"[" * 80 + b"0" + b"]" * 80 + b"}\n",
        b'{"type":"item.completed","x":"\\ud800"}\n',
        b"[]\n",
        b"null\n",
        b"1\n",
        b'"text"\n',
        b'{"type":"error"}\n',
        b'{"type":"turn.failed","error":{"message":1}}\n',
        b'{"type":"error","message":"  "}\n',
        b"x" * (_EVENT_LINE_BYTES + 1) + b"\n",
    ],
)
def test_bad_line_permanently_poisoned_before_or_after_candidate(bad: bytes, after: bool) -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    observer.feed(event() + bad if after else bad + event())
    observer.feed(event("HTTP 401 future candidate"))
    observer.finish()
    assert observer.result() is None


@pytest.mark.parametrize("tail", [b'{"type":"error"}', b"\xe9", b"x" * 100_000])
def test_incomplete_final_line_cannot_reuse_old_complete_error(tail: bytes) -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    observer.feed(event() + tail)
    observer.finish()
    assert observer.result() is None


@pytest.mark.parametrize("kind", ["turn.completed", "turn.started", "thread.started"])
def test_success_or_new_turn_clears_intermediate_error(kind: str) -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    observer.feed(event() + json.dumps({"type": kind}).encode() + b"\n")
    observer.finish()
    assert observer.result() is None


def test_nested_tools_mcp_and_plain_json_messages_are_not_native_failures() -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    observer.feed(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "error", "message": "HTTP 401"},
            }
        ).encode()
        + b"\n"
    )
    observer.feed(json.dumps({"error": {"message": "HTTP 401"}}).encode() + b"\n")
    observer.finish()
    assert observer.result() is None


@pytest.mark.parametrize(
    "message", ["MCP: authentication 401", "RMCP::error: 401", "tool server HTTP 401"]
)
def test_native_component_prefix_cannot_classify_as_provider_auth(message: str) -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    observer.feed(event(message))
    observer.finish()
    found = observer.result()
    assert found is None
    structured = _classify_structured_json_failure(message)
    assert structured.code is AgentErrorCode.PROVIDER_UNAVAILABLE
    assert structured.transient and not structured.timeout_provider_failure
    assert not structured.main_error
    assert _classify_cli_failure(CodexInvocationResult(1, native_failure=found)) == (
        AgentErrorCode.PROVIDER_UNAVAILABLE,
        False,
    )


def test_classification_uses_full_raw_message_before_secret_cleanup_and_bound() -> None:
    secret = "synthetic-proxy-value"
    raw_message = (
        "https://example.invalid/"
        + "x" * 2000
        + " "
        + secret
        + " "
        + "-----BEGIN PRIVATE KEY-----\nprivate-value\n-----END PRIVATE KEY----- "
        + "\x1b[31mHTTP 429\x1b[0m fixture\x07"
    )
    observer = CodexJsonEventObserver(_classify_native_json_failure, exact_secret=secret)
    observer.feed(event(raw_message))
    observer.finish()
    found = observer.result()
    assert found is not None and found.classification.code is AgentErrorCode.RATE_LIMITED
    invocation = CodexInvocationResult(1, native_failure=found, stderr_truncated=True)
    assert _classify_cli_failure(invocation) == (AgentErrorCode.RATE_LIMITED, True)
    detail = _safe_cli_failure_detail(invocation, proxy_key_required=True, proxy_key=secret)
    assert "429" in detail and "[REDACTED:" in detail and len(detail) <= 500
    for private in (secret, "private-value", "https://", "\x1b", "\x07"):
        assert private not in detail and private not in repr(found)


def test_classification_preserves_marker_after_display_expands_then_truncates() -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure, exact_secret="z")
    observer.feed(event("z " * 10_000 + "HTTP 429"))
    observer.finish()
    found = observer.result()
    assert found is not None and found.classification.code is AgentErrorCode.RATE_LIMITED
    assert found.message is not None and len(found.message) <= _EVENT_LINE_BYTES
    assert "429" not in found.message
    assert _classify_cli_failure(CodexInvocationResult(1, native_failure=found)) == (
        AgentErrorCode.RATE_LIMITED,
        True,
    )


@pytest.mark.parametrize("secret", [None, "", "bad key", "bad\x07key"])
def test_unavailable_or_normalization_sensitive_required_secret_hides_message(
    secret: str | None,
) -> None:
    observer = CodexJsonEventObserver(
        _classify_native_json_failure, exact_secret=secret, secret_required=True
    )
    observer.feed(event())
    observer.finish()
    found = observer.result()
    assert found is not None and found.message is None


def test_native_signal_abort_timeout_and_zero_keep_their_original_priority() -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    observer.feed(event("HTTP 401 Unauthorized"))
    observer.finish()
    invocation = CodexInvocationResult(1, native_failure=observer.result())
    assert _classify_cli_failure(replace(invocation, returncode=-15)) == (
        AgentErrorCode.PROVIDER_ERROR,
        False,
    )
    assert _classify_cli_failure(
        replace(invocation, execution_abort_reason=ExecutionAbortReason())
    ) == (AgentErrorCode.WORK_INTERRUPTED, False)
    assert _classify_cli_failure(replace(invocation, timed_out=True)) == (
        AgentErrorCode.PROVIDER_UNAVAILABLE,
        False,
    )
    assert _classify_cli_failure(replace(invocation, returncode=0)) == (
        AgentErrorCode.PROVIDER_UNAVAILABLE,
        False,
    )


def test_different_callers_preserve_their_original_unknown_and_timeout_rules() -> None:
    native = _classify_native_json_failure("unknown native failure")
    structured = _classify_structured_json_failure("unknown native failure")
    assert native.code is None and not native.transient
    assert structured.code is AgentErrorCode.PROVIDER_UNAVAILABLE and structured.transient
    assert not structured.timeout_provider_failure
    service = _classify_structured_json_failure("unexpected status 504")
    assert service.timeout_provider_failure and service.transient


def test_overlong_stream_buffer_stays_bounded_and_never_resynchronizes_authority() -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    block = b"x" * 65536
    tracemalloc.start()
    try:
        for _ in range(128):
            observer.feed(block)
        observer.feed(b"\n" + event())
        observer.finish()
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert current < 256_000 and peak < 512_000
    assert observer.result() is None


def test_component_root_event_does_not_shadow_real_native_stderr_main_error() -> None:
    observer = CodexJsonEventObserver(_classify_native_json_failure)
    observer.feed(event("MCP: authentication 401"))
    observer.finish()
    invocation = CodexInvocationResult(
        1,
        stderr="Error: HTTP 503 Service failure",
        native_failure=observer.result(),
    )
    assert _classify_cli_failure(invocation) == (AgentErrorCode.PROVIDER_UNAVAILABLE, True)
