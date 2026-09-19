"""Focused contracts for safe candidate remediation context."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from ai_software_engineer.recovery.remediation import remediation_context
from ai_software_engineer.redaction import redact_text


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


def test_remediation_context_redacts_secret_shaped_candidate_fixture(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.email", "tests@example.invalid")
    _git(repository, "config", "user.name", "ASE Tests")
    fixture = repository / "fixture.py"
    fixture.write_text("VALUE = 'base'\n", encoding="utf-8")
    _git(repository, "add", "fixture.py")
    _git(repository, "commit", "-m", "base")
    base = _git(repository, "rev-parse", "HEAD")
    fixture.write_text("TOKEN='fixture-value'\n", encoding="utf-8")
    _git(repository, "add", "fixture.py")
    _git(repository, "commit", "-m", "candidate")
    candidate = _git(repository, "rev-parse", "HEAD")

    plan = cast(Any, SimpleNamespace(plan_sha256="a" * 64))
    completion = cast(
        Any,
        SimpleNamespace(
            completion_sha256="b" * 64,
            to_wire=lambda: {"verified": False},
        ),
    )

    sources = remediation_context(
        repository_root=str(repository),
        source_delivery_id="delivery_fixture",
        source_base_revision=base,
        candidate_revision=candidate,
        plan=plan,
        completion=completion,
    )

    patch = next(
        source.content for source in sources if source.source_id.endswith("candidate_patch")
    )
    assert patch is not None
    assert "fixture-value" not in patch
    assert "[REDACTED:secret_assignment]" in patch
    assert redact_text(patch).text == patch
