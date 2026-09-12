"""The managed runtime environment is small, strict and shell-loadable."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ai_software_engineer.config import (
    LocalRuntimeEnvironmentStore,
    RuntimeEnvironmentError,
    runtime_environment_path,
)


def test_runtime_environment_round_trip_is_atomic_and_private(tmp_path: Path) -> None:
    path = runtime_environment_path(tmp_path / "production.json")
    store = LocalRuntimeEnvironmentStore(path)

    store.save(
        {
            "ASE_MYSQL_DSN": "mysql+pymysql://user:p'ass@127.0.0.1:3307/database",
            "DEEPSEEK_API_KEY": "key-value",
        }
    )

    assert store.load() == {
        "ASE_MYSQL_DSN": "mysql+pymysql://user:p'ass@127.0.0.1:3307/database",
        "DEEPSEEK_API_KEY": "key-value",
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".ase-runtime-env-*"))


@pytest.mark.parametrize(
    "body",
    [
        b"lower='value'\n",
        b"ASE_MYSQL_DSN=value\n",
        b"ASE_MYSQL_DSN='first'\nASE_MYSQL_DSN='second'\n",
        b"ASE_MYSQL_DSN='unterminated\n",
    ],
)
def test_runtime_environment_rejects_noncanonical_or_duplicate_entries(
    tmp_path: Path, body: bytes
) -> None:
    path = runtime_environment_path(tmp_path / "production.json")
    path.write_bytes(body)

    with pytest.raises(RuntimeEnvironmentError):
        LocalRuntimeEnvironmentStore(path).load()


def test_runtime_environment_rejects_controls_and_wrong_filename(tmp_path: Path) -> None:
    with pytest.raises(RuntimeEnvironmentError, match=r"runtime\.env"):
        LocalRuntimeEnvironmentStore(tmp_path / "secrets.env")
    with pytest.raises(RuntimeEnvironmentError, match="value"):
        LocalRuntimeEnvironmentStore(tmp_path / "runtime.env").save(
            {"ASE_MYSQL_DSN": "line-one\nline-two"}
        )
