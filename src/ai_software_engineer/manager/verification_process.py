"""Bounded trusted executor/discovery commands; never an Agent command port."""

import os
import selectors
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

from ai_software_engineer.owned_processes import finish_owned_process, observe_owned_process


def bounded_verification_command(
    argv: tuple[str, ...],
    *,
    environment: Mapping[str, str],
    cwd: Path | None = None,
    stdin: bytes | None = None,
    timeout: int = 20,
    limit: int = 128_000,
) -> bytes:
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    observation = observe_owned_process(process, kind="tool")
    output_drained = False
    assert process.stdout is not None and process.stderr is not None
    deadline = time.monotonic() + timeout
    output, errors = bytearray(), bytearray()
    try:
        # Inputs are trusted short SQL, never a candidate stream.
        if stdin is not None:
            if len(stdin) > 4096:
                raise ValueError("verification command input exceeds bound")
            assert process.stdin is not None
            process.stdin.write(stdin)
            process.stdin.close()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, output)
            selector.register(process.stderr, selectors.EVENT_READ, errors)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("verification command timed out")
                for key, _ in selector.select(min(remaining, 1)):
                    buffer = key.data
                    chunk = os.read(key.fd, min(65536, limit - len(buffer) + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer.extend(chunk)
                    if len(buffer) > limit:
                        raise ValueError("verification command output exceeds bound")
        if process.wait(timeout=max(0.01, deadline - time.monotonic())):
            raise ValueError("verification command failed")
        output_drained = True
        return bytes(output)
    finally:
        try:
            finish_owned_process(process, observation, output_drained=output_drained)
        finally:
            process.stdout.close()
            process.stderr.close()
            if process.stdin is not None:
                process.stdin.close()
