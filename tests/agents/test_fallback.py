"""Typed provider fallback and immutable route-attempt evidence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentRequestConflict,
    AgentResult,
    AgentRunStatus,
    FallbackAgentAdapter,
    FileModelRouteAttemptStore,
    ModelRouteAttemptCorruption,
    ProviderAgentRoute,
    RouteAttemptOutcome,
)
from tests.agents.test_openai_compatible import _align, _coder_request
from tests.domain.factories import make_implementation_artifact

NOW = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self._now = NOW

    def __call__(self) -> datetime:
        current = self._now
        self._now += timedelta(milliseconds=1)
        return current


class _ResultAdapter:
    def __init__(self, result: AgentResult) -> None:
        self.result = result
        self.requests: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        return self.result


def _failed(request: AgentRequest, code: AgentErrorCode, *, transient: bool) -> AgentResult:
    status = AgentRunStatus.TIMED_OUT if code is AgentErrorCode.TIMEOUT else AgentRunStatus.FAILED
    return AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=status,
        error=AgentFailure(code=code, message="safe provider failure", transient=transient),
    )


def _success(request: AgentRequest) -> AgentResult:
    return AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.SUCCEEDED,
        artifact=_align(make_implementation_artifact(), request),
    )


def test_quota_exhaustion_falls_back_and_persists_both_routes(tmp_path: Path) -> None:
    request = _coder_request()
    primary = _ResultAdapter(_failed(request, AgentErrorCode.QUOTA_EXHAUSTED, transient=True))
    qwen = _ResultAdapter(_success(request))
    store = FileModelRouteAttemptStore(tmp_path / "routes")
    adapter = FallbackAgentAdapter(
        (
            ProviderAgentRoute("codex", "gpt-5.5", primary),
            ProviderAgentRoute("qwen", "qwen3.8-max", qwen),
        ),
        attempt_store=store,
        clock=_Clock(),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    attempts = store.list_for_run(request.run_id)
    assert tuple(item.provider for item in attempts) == ("codex", "qwen")
    assert attempts[0].outcome is RouteAttemptOutcome.FALLBACK
    assert attempts[0].error_code is AgentErrorCode.QUOTA_EXHAUSTED
    assert attempts[1].outcome is RouteAttemptOutcome.SUCCEEDED


@pytest.mark.parametrize(
    "code",
    (AgentErrorCode.RATE_LIMITED, AgentErrorCode.PROVIDER_UNAVAILABLE, AgentErrorCode.TIMEOUT),
)
def test_only_typed_transient_infrastructure_codes_fall_back(
    tmp_path: Path,
    code: AgentErrorCode,
) -> None:
    request = _coder_request()
    primary = _ResultAdapter(_failed(request, code, transient=True))
    backup = _ResultAdapter(_success(request))
    adapter = FallbackAgentAdapter(
        (
            ProviderAgentRoute("codex", "gpt-5.5", primary),
            ProviderAgentRoute("deepseek", "deepseek-v4-pro", backup),
        ),
        attempt_store=FileModelRouteAttemptStore(tmp_path / "routes"),
        clock=_Clock(),
    )

    assert adapter.run(request).status is AgentRunStatus.SUCCEEDED
    assert len(backup.requests) == 1


@pytest.mark.parametrize(
    "code",
    (
        AgentErrorCode.AUTHENTICATION_ERROR,
        AgentErrorCode.INVALID_OUTPUT,
        AgentErrorCode.POLICY_VIOLATION,
        AgentErrorCode.PROVIDER_ERROR,
    ),
)
def test_contract_and_auth_failures_never_switch_models(
    tmp_path: Path,
    code: AgentErrorCode,
) -> None:
    request = _coder_request()
    primary = _ResultAdapter(_failed(request, code, transient=False))
    backup = _ResultAdapter(_success(request))
    store = FileModelRouteAttemptStore(tmp_path / "routes")
    adapter = FallbackAgentAdapter(
        (
            ProviderAgentRoute("codex", "gpt-5.5", primary),
            ProviderAgentRoute("qwen", "qwen3.8-max", backup),
        ),
        attempt_store=store,
        clock=_Clock(),
    )

    result = adapter.run(request)

    assert result.error is not None and result.error.code is code
    assert backup.requests == []
    attempts = store.list_for_run(request.run_id)
    assert len(attempts) == 1
    assert attempts[0].outcome is RouteAttemptOutcome.FAILED


def test_exact_run_replay_does_not_call_or_persist_twice(tmp_path: Path) -> None:
    request = _coder_request()
    route = _ResultAdapter(_success(request))
    store = FileModelRouteAttemptStore(tmp_path / "routes")
    adapter = FallbackAgentAdapter(
        (ProviderAgentRoute("codex", "gpt-5.5", route),),
        attempt_store=store,
        clock=_Clock(),
    )

    first = adapter.run(request)
    assert adapter.run(request) == first
    assert len(route.requests) == 1
    assert len(store.list_for_run(request.run_id)) == 1

    with pytest.raises(AgentRequestConflict):
        adapter.run(request.model_copy(update={"attempt": 2}))


def test_process_restart_replays_durable_terminal_result_without_provider_call(
    tmp_path: Path,
) -> None:
    request = _coder_request()
    first_route = _ResultAdapter(_success(request))
    store = FileModelRouteAttemptStore(tmp_path / "routes")
    first = FallbackAgentAdapter(
        (ProviderAgentRoute("codex", "gpt-5.5", first_route),),
        attempt_store=store,
        clock=_Clock(),
    ).run(request)
    replacement = _ResultAdapter(
        _failed(request, AgentErrorCode.PROVIDER_UNAVAILABLE, transient=True)
    )

    replayed = FallbackAgentAdapter(
        (ProviderAgentRoute("codex", "gpt-5.5", replacement),),
        attempt_store=store,
        clock=_Clock(),
    ).run(request)

    assert replayed == first
    assert replacement.requests == []


def test_process_restart_rejects_changed_request_with_same_run_id(tmp_path: Path) -> None:
    request = _coder_request()
    store = FileModelRouteAttemptStore(tmp_path / "routes")
    FallbackAgentAdapter(
        (ProviderAgentRoute("codex", "gpt-5.5", _ResultAdapter(_success(request))),),
        attempt_store=store,
        clock=_Clock(),
    ).run(request)
    changed = request.model_copy(update={"timeout_seconds": request.timeout_seconds + 1})

    with pytest.raises(AgentRequestConflict):
        FallbackAgentAdapter(
            (ProviderAgentRoute("codex", "gpt-5.5", _ResultAdapter(_success(changed))),),
            attempt_store=store,
            clock=_Clock(),
        ).run(changed)


def test_tampered_route_evidence_fails_closed(tmp_path: Path) -> None:
    request = _coder_request()
    root = tmp_path / "routes"
    store = FileModelRouteAttemptStore(root)
    adapter = FallbackAgentAdapter(
        (ProviderAgentRoute("codex", "gpt-5.5", _ResultAdapter(_success(request))),),
        attempt_store=store,
        clock=_Clock(),
    )
    adapter.run(request)
    record = root / request.run_id / "01.json"
    record.write_text(record.read_text().replace("gpt-5.5", "gpt-5.4"), encoding="utf-8")

    with pytest.raises(ModelRouteAttemptCorruption):
        store.list_for_run(request.run_id)
