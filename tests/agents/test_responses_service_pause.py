"""A returned HTTP call is real; pause rejects its subsequent tools and turns."""

from collections.abc import Mapping

from jsonschema import Draft202012Validator

from ai_software_engineer.agents import AgentErrorCode, HttpResponse
from ai_software_engineer.service_pause import ServicePauseControl
from tests.agents.test_responses_continuation import _adapter, _call, _tools
from tests.agents.test_responses_continuation import native as native
from tests.contracts.test_continuation_schema import _schema
from tests.orchestration.test_native_continuation_v2 import V2Fixture


def test_pause_after_http_return_preserves_draft_and_rejects_next_tool(native: V2Fixture) -> None:
    control = ServicePauseControl(grace_seconds=0)

    class Transport:
        calls = 0

        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            self.calls += 1
            if self.calls == 1:
                return _tools(_call("write_file", path="src/app.py", content="VALUE = 2\n"))
            control.request()
            return _tools(_call("write_file", path="src/blocked.py", content="MUST NOT RUN\n"))

    transport = Transport()
    with control.operation_scope("operation_http_pause"):
        result = _adapter(native, transport).run(native.request)
    assert transport.calls == 2
    assert result.error is not None and result.error.code is AgentErrorCode.SERVICE_PAUSED
    assert not result.error.transient and result.artifact is None
    assert (native.worktree.path / "src/app.py").read_text() == "VALUE = 2\n"
    assert not (native.worktree.path / "src/blocked.py").exists()
    receipt = native.store.get_receipt(native.request.run_id)
    assert receipt.cause == "service_pause" and receipt.process_stop.kind == "service_pause"
    Draft202012Validator(_schema("execution-continuation.schema.json")).validate(receipt.to_wire())
    # The existing frozen policy cannot gain new automatic continuation authority.
    before = native.repository.get(native.task.id)
    assert native.service().next_attempt(before, result, native.repository) is None
    assert native.repository.get(native.task.id) == before


def test_pause_before_first_http_call_has_no_provider_or_tool_side_effect(
    native: V2Fixture,
) -> None:
    control = ServicePauseControl(grace_seconds=0)

    class Transport:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            raise AssertionError("paused invocation admitted a new HTTP call")

    with control.operation_scope("operation_http_no_start"):
        control.request()
        result = _adapter(native, Transport()).run(native.request)
    assert result.error is not None and result.error.code is AgentErrorCode.SERVICE_PAUSED
    receipt = native.store.get_receipt(native.request.run_id)
    assert not receipt.mutation_paths and receipt.cause == "service_pause"
