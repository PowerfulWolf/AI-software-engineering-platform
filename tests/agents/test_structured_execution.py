"""The structured CLI bridge preserves ownership and local timeout classification."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents.execution import bind_execution_guard, current_execution_guard
from ai_software_engineer.agents.structured_execution import run_structured_command


@pytest.mark.parametrize("expired", [False, True])
def test_owned_structured_cli_returns_output_or_explicit_local_timeout(
    tmp_path: Path, expired: bool
) -> None:
    guard = Mock()
    guard.inherited_fds = ()
    source = "import time; time.sleep(3)" if expired else "print('local fixture')"
    with bind_execution_guard(guard):
        if expired:
            with pytest.raises(subprocess.TimeoutExpired):
                run_structured_command(
                    (sys.executable, "-c", source),
                    cwd=tmp_path,
                    env={},
                    input="",
                    capture_output=True,
                    text=True,
                    timeout=1,
                    check=False,
                )
        else:
            result = run_structured_command(
                (sys.executable, "-c", source),
                cwd=tmp_path,
                env={},
                input="",
                capture_output=True,
                text=True,
                timeout=1,
                check=False,
            )
            assert result.returncode == 0 and result.stdout == "local fixture\n"
    assert guard.check.call_count >= 4
    assert current_execution_guard() is None


def test_rejected_guard_does_not_leak_to_next_invocation() -> None:
    guard = Mock()
    guard.check.side_effect = RuntimeError("owner lost")
    with pytest.raises(RuntimeError, match="owner lost"), bind_execution_guard(guard):
        pytest.fail("unowned model call admitted")
    assert current_execution_guard() is None
