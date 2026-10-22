"""Preserve the structured CLI seam while enforcing owned Manager cancellation."""

import hashlib
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ai_software_engineer.agents._codex_events import CodexEventClassifier
from ai_software_engineer.agents.codex_cli import (
    CodexCliError,
    CodexExecutionUnconfirmed,
    CodexInvocationResult,
    CodexProcessNotStarted,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.execution import current_execution_guard
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured_observation import (
    StructuredNativeNotStartedReceipt,
    StructuredNativeStopReceipt,
    StructuredObservationRejected,
    admit_structured_execution,
    observation_digest,
    record_structured_native_not_started,
    record_structured_native_stop,
)


class _StructuredCommandResult(subprocess.CompletedProcess[str]):
    def __init__(self, argv: tuple[str, ...], invocation: CodexInvocationResult) -> None:
        super().__init__(argv, invocation.returncode, invocation.stdout, invocation.stderr)
        self.invocation = invocation


class _StructuredCommandTimeout(subprocess.TimeoutExpired):
    def __init__(
        self,
        argv: tuple[str, ...],
        timeout: int,
        invocation: CodexInvocationResult,
    ) -> None:
        super().__init__(argv, timeout, output=invocation.stdout, stderr=invocation.stderr)
        self.invocation = invocation


def structured_native_invocation(
    outcome: subprocess.CompletedProcess[str] | subprocess.TimeoutExpired,
) -> CodexInvocationResult | None:
    return (
        outcome.invocation
        if isinstance(
            outcome,
            (_StructuredCommandResult, _StructuredCommandTimeout),
        )
        else None
    )


def run_structured_command(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input: str,
    capture_output: bool,
    text: bool,
    timeout: int,
    check: bool,
    output_protocol: Literal["codex_json"] | None = None,
    event_classifier: CodexEventClassifier | None = None,
    diagnostic_secret: str | None = None,
    diagnostic_secret_required: bool = False,
) -> subprocess.CompletedProcess[str]:
    guard = current_execution_guard()
    if not capture_output or not text:
        raise ValueError("structured commands require captured text output")
    admission = admit_structured_execution(
        execution_kind="native",
        transport_request_sha256=observation_digest(
            {
                "argv": argv,
                "cwd": str(cwd),
                "stdin_sha256": hashlib.sha256(input.encode()).hexdigest(),
            }
        ),
        timeout_seconds=timeout,
    )

    stop_recorded = False

    def observed(result: CodexInvocationResult) -> None:
        nonlocal stop_recorded
        if admission is None:
            return
        stop = result.process_stop
        if stop is None:
            raise CodexExecutionUnconfirmed("结构化执行缺少实际进程停止记录")
        try:
            if stop.returncode != result.returncode or (
                result.timed_out != (stop.kind == "local_execution_limit")
            ):
                raise ValueError("structured runner stop differs from process result")
            receipt = StructuredNativeStopReceipt.create(
                admission=admission,
                process_stop=stop,
                stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
                stderr_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),
            )
            record_structured_native_stop(receipt)
            stop_recorded = True
        except StructuredObservationRejected:
            raise
        except Exception as error:
            raise StructuredObservationRejected("结构化执行停止事实不一致; 暂停后续执行") from error

    try:
        runner = SubprocessCodexCommandRunner(
            guard,
            process_kind="structured",
            output_protocol=output_protocol,
            event_classifier=event_classifier,
            diagnostic_secret=diagnostic_secret,
            diagnostic_secret_required=diagnostic_secret_required,
        )
        if admission is None:
            result = runner.run(
                argv, cwd=cwd, environment=env, stdin=input, timeout_seconds=timeout
            )
        else:
            result = runner.run_observed(
                argv,
                cwd=cwd,
                environment=env,
                stdin=input,
                timeout_seconds=timeout,
                observer=observed,
            )
            if not stop_recorded:
                raise CodexExecutionUnconfirmed("结构化执行未保存实际进程停止记录")
    except CodexExecutionUnconfirmed:
        raise
    except CodexProcessNotStarted as error:
        if admission is not None:
            receipt = StructuredNativeNotStartedReceipt.create(
                admission=admission,
                failure_kind=error.failure_kind,
                failed_at=datetime.now(UTC),
            )
            record_structured_native_not_started(receipt)
        if error.failure_kind == "service_pause_admission_closed":
            from ai_software_engineer.agents.structured import StructuredModelError

            raise StructuredModelError(
                AgentErrorCode.SERVICE_PAUSED, "服务暂停已拒绝新进程, 未启动执行。", transient=False
            ) from error
        raise OSError("owned Codex process was not started") from error
    except CodexCliError as error:
        raise OSError("owned Codex process could not start") from error
    if result.process_stop is not None and result.process_stop.kind == "service_pause":
        from ai_software_engineer.agents.structured import StructuredModelError

        raise StructuredModelError(
            AgentErrorCode.SERVICE_PAUSED,
            "服务重启已受控暂停结构化执行, 真实停止记录已保存。",
            transient=False,
        )
    if result.timed_out:
        raise _StructuredCommandTimeout(argv, timeout, result)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, argv, output=result.stdout, stderr=result.stderr
        )
    return _StructuredCommandResult(argv, result)
