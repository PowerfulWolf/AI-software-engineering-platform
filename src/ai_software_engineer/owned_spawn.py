"""Private pre-exec ownership gate for trusted survey and verification queries."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ai_software_engineer.owned_processes import (
    OwnedProcessesUncertain,
    OwnedProcessObservation,
    observe_owned_process,
)

_BOOTSTRAP_VERSION = "ase-owned-query-v1"
_MAX_ENVIRONMENT_BYTES = 2 * 1024 * 1024
_ACK_TIMEOUT_SECONDS = 1.0
_BOOTSTRAP = """import json, os, sys
if len(sys.argv) < 4 or sys.argv[1] != 'ase-owned-query-v1':
    os._exit(125)
control = int(sys.argv[2])
def read_exact(length):
    result = bytearray()
    while len(result) < length:
        chunk = os.read(control, length - len(result))
        if not chunk:
            os._exit(125)
        result.extend(chunk)
    return bytes(result)
try:
    if read_exact(1) != b'1':
        os._exit(125)
    length = int.from_bytes(read_exact(4), 'big')
    if not 0 < length <= 2097152:
        os._exit(125)
    environment = json.loads(read_exact(length))
    if not isinstance(environment, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in environment.items()
    ):
        os._exit(125)
except (OSError, ValueError):
    os._exit(125)
finally:
    os.close(control)
try:
    os.execvpe(sys.argv[3], sys.argv[3:], environment)
except (OSError, ValueError):
    os._exit(127)
"""


@dataclass(frozen=True, slots=True)
class OwnedQuerySpawn:
    process: subprocess.Popen[bytes]
    observation: OwnedProcessObservation


def spawn_owned_query(
    argv: tuple[str, ...],
    *,
    environment: Mapping[str, str],
    cwd: Path | None = None,
    stdin: int = subprocess.DEVNULL,
    stdout: int | BinaryIO = subprocess.PIPE,
    stderr: int | BinaryIO = subprocess.PIPE,
) -> OwnedQuerySpawn:
    """Capture the actual blocked leader before releasing its exact target exec.

    Only trusted callers supply commands. This grants no command permission and
    preserves the original session-stop, output and durable-publication gates.
    """
    if not argv:
        raise ValueError("trusted query requires a tokenized command")
    original_environment = dict(environment)
    encoded_environment = json.dumps(original_environment, ensure_ascii=True).encode("ascii")
    if len(encoded_environment) > _MAX_ENVIRONMENT_BYTES:
        raise ValueError("trusted query environment exceeds launch bound")
    release = b"1" + len(encoded_environment).to_bytes(4, "big") + encoded_environment
    control_read, control_write = os.pipe()
    process: subprocess.Popen[bytes] | None = None
    observation: OwnedProcessObservation | None = None
    try:
        process = subprocess.Popen(
            (
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                _BOOTSTRAP,
                _BOOTSTRAP_VERSION,
                str(control_read),
                *argv,
            ),
            cwd=cwd,
            env=original_environment,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            pass_fds=(control_read,),
            start_new_session=True,
            shell=False,
        )
        os.close(control_read)
        control_read = -1
        observation = observe_owned_process(process, kind="tool")
        # A failed initial capture is retained by the registry and rejected here.
        # A second live observation also precedes permission to execute the target.
        observation.observe_session()
        os.set_blocking(control_write, False)
        deadline = time.monotonic() + _ACK_TIMEOUT_SECONDS
        position = 0
        while position < len(release):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select((), (control_write,), (), remaining)[1]:
                raise OwnedProcessesUncertain("可信探测启动确认超时")
            try:
                written = os.write(control_write, release[position:])
            except BlockingIOError:
                continue
            if written <= 0:
                raise OwnedProcessesUncertain("可信探测启动确认未完成")
            position += written
        return OwnedQuerySpawn(process, observation)
    except BaseException as error:
        if observation is not None:
            observation.uncertain()
        if process is not None:
            # No unchecked PID selector: clean only this actual unreleased Popen.
            with suppress(OSError):
                process.kill()
            with suppress(OSError, subprocess.SubprocessError):
                process.wait(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            if isinstance(error, Exception):
                raise OwnedProcessesUncertain("可信探测启动归属尚未核验") from None
        raise
    finally:
        for descriptor in (control_read, control_write):
            if descriptor >= 0:
                os.close(descriptor)
