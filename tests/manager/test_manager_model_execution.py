"""Real immutable ledger; only the external provider and claim authority are fakes."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Self
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured import (
    StructuredModelClient,
    StructuredModelError,
    StructuredModelResult,
)
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.retry_policy import ExecutionTimePolicy, ManagerRetryPolicy
from ai_software_engineer.manager.model_execution import (
    ManagerContext,
    ManagerExecutionRejected,
    ManagerModelExecutor,
    ManagerRunRecord,
    ManagerRunScope,
)


class Proposal(DomainModel):
    action: Literal["WAITING_HUMAN"]


class Authority:
    inherited_fds: tuple[int, ...] = ()
    owner_sha256 = "a" * 64
    calls = 0
    owned = False

    @contextmanager
    def claim(self, scope: ManagerRunScope, *, seconds: int) -> Iterator[Self]:
        assert not self.owned
        self.owned = True
        self.calls += 1
        try:
            yield self
        finally:
            self.owned = False

    def check(self) -> None:
        assert self.owned

    @contextmanager
    def write_scope(self) -> Iterator[None]:
        self.check()
        yield
        self.check()


def executor(root: Path, authority: Authority | None = None) -> ManagerModelExecutor:
    return ManagerModelExecutor(
        root=root,
        scope=ManagerRunScope(
            team_id="team_test",
            project_id="project_test",
            requirement_id="delivery_test",
            stage="PLANNING",
        ),
        authority=authority or Authority(),
        retry_policy=ManagerRetryPolicy(),
        time_policy=ExecutionTimePolicy(),
    )


def invoke(
    runner: ManagerModelExecutor,
    client: StructuredModelClient,
    payload: Mapping[str, object] | None = None,
) -> tuple[Proposal, str, str]:
    return runner.run(
        client, instructions="Propose only", payload=payload or {"source": "abc"}, model=Proposal
    )


def ok() -> StructuredModelResult:
    return StructuredModelResult(payload={"action": "WAITING_HUMAN"}, duration_ms=1)


def test_separate_provider_and_capacity_with_durable_reopen(tmp_path: Path) -> None:
    authority = Authority()
    client = Mock()
    client.complete.side_effect = [
        StructuredModelError(AgentErrorCode.PROVIDER_UNAVAILABLE, "504", transient=True),
        StructuredModelError(
            AgentErrorCode.TIMEOUT, "local", transient=False, timeout_kind="local_execution_limit"
        ),
        ok(),
    ]
    runner = executor(tmp_path, authority)
    assert invoke(runner, client)[0].action == "WAITING_HUMAN"
    assert [c.kwargs["timeout_seconds"] for c in client.complete.call_args_list] == [600, 600, 1200]
    assert authority.calls == 3
    records = runner._history()
    assert [r.state for r in records] == ["TRANSIENT", "CAPACITY", "SUCCEEDED"]
    assert len({r.run_id for r in records}) == 3
    client.complete.reset_mock()
    assert invoke(executor(tmp_path), client)[0].action == "WAITING_HUMAN"
    client.complete.assert_not_called()


def test_invalid_and_unknown_calls_are_not_free_and_raw_output_is_not_saved(tmp_path: Path) -> None:
    runner = executor(tmp_path)
    client = Mock()
    client.complete.return_value = StructuredModelResult(
        payload={"secret": "do-not-store"}, duration_ms=0
    )
    with pytest.raises(ManagerExecutionRejected, match="修正"):
        invoke(runner, client)
    assert client.complete.call_count == 2
    contexts = runner.store.list("manager-context", ManagerContext)
    assert len(contexts) == 2, "correction must have its own exact input manifest"
    assert {"ctx_manager_" + c.input_sha256 for c in contexts} == {
        r.context_manifest_id for r in runner._history()
    }
    for call in client.complete.call_args_list:
        assert any(c.payload == call.kwargs["input_payload"] for c in contexts)
    assert "do-not-store" not in "".join(p.read_text() for p in tmp_path.glob("*.json"))
    with pytest.raises(ManagerExecutionRejected):
        invoke(executor(tmp_path), client)
    assert client.complete.call_count == 2


def test_unknown_crash_retains_claim_and_counts_work(tmp_path: Path) -> None:
    client = Mock()
    client.complete.side_effect = RuntimeError("uncertain")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="uncertain"):
            invoke(executor(tmp_path), client)
    with pytest.raises(ManagerExecutionRejected):
        invoke(executor(tmp_path), client)
    assert client.complete.call_count == 2
    assert len(executor(tmp_path).store.list("manager-start", ManagerRunRecord)) == 2


def test_capacity_exhaustion_survives_new_input_and_restart(tmp_path: Path) -> None:
    client = Mock()
    client.complete.side_effect = StructuredModelError(
        AgentErrorCode.TIMEOUT, "local", transient=False, timeout_kind="local_execution_limit"
    )
    with pytest.raises(ManagerExecutionRejected, match="扩容"):
        invoke(executor(tmp_path), client)
    assert client.complete.call_count == 3
    with pytest.raises(ManagerExecutionRejected, match="扩容"):
        invoke(executor(tmp_path), client, {"source": "updated-checkpoint"})
    assert client.complete.call_count == 3


def test_distinct_advice_rounds_bounded_per_stage_not_checkpoint(tmp_path: Path) -> None:
    client = Mock()
    client.complete.return_value = ok()
    for i in range(3):
        invoke(executor(tmp_path), client, {"checkpoint": i})
    with pytest.raises(ManagerExecutionRejected, match="轮次"):
        invoke(executor(tmp_path), client, {"checkpoint": 4})
    assert client.complete.call_count == 3
