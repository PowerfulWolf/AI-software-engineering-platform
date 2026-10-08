"""Preserve the structured CLI seam while enforcing owned Manager cancellation."""

import subprocess
from collections.abc import Mapping
from pathlib import Path

from ai_software_engineer.agents.codex_cli import (
    CodexCliError,
    CodexExecutionUnconfirmed,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.execution import current_execution_guard


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
) -> subprocess.CompletedProcess[str]:
    guard = current_execution_guard()
    if not capture_output or not text:
        raise ValueError("structured commands require captured text output")
    try:
        result = SubprocessCodexCommandRunner(guard, process_kind="structured").run(
            argv,
            cwd=cwd,
            environment=env,
            stdin=input,
            timeout_seconds=timeout,
        )
    except CodexExecutionUnconfirmed:
        raise
    except CodexCliError as error:
        raise OSError("owned Codex process could not start") from error
    if result.timed_out:
        raise subprocess.TimeoutExpired(argv, timeout, output=result.stdout, stderr=result.stderr)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, argv, output=result.stdout, stderr=result.stderr
        )
    return subprocess.CompletedProcess(argv, result.returncode, result.stdout, result.stderr)
