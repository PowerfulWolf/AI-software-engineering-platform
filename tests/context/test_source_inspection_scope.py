"""Repeated capture checks reuse pure facts only within a bounded read scope."""

import ast
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import cast

import pytest

from ai_software_engineer import redaction


@contextmanager
def _parse_count(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    original = ast.parse
    calls = [0]

    def counted(source: str, filename: str = "<unknown>", mode: str = "exec") -> ast.AST:
        calls[0] += 1
        return cast(ast.AST, original(source, filename, mode))

    monkeypatch.setattr(ast, "parse", counted)
    yield calls


def test_identical_source_and_nested_scopes_reuse_scan_then_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "password=settings.password\n"
    with _parse_count(monkeypatch) as calls:
        with redaction.source_inspection_scope():
            assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
            first = calls[0]
            assert first > 0
            with redaction.source_inspection_scope():
                assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
            assert calls[0] == first
        with redaction.source_inspection_scope():
            assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
        assert calls[0] == first * 2


def test_full_text_language_and_sensitive_results_are_distinct() -> None:
    source = "token=settings.token\n"
    with redaction.source_inspection_scope():
        assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
        assert redaction.source_secret_occurrences(source, source_path=".env")
        assert redaction.source_secret_occurrences(source, source_path=None)
        changed = source + 'password="actual-private-value"\n'
        denied = redaction.source_secret_occurrences(changed, source_path="src/app.py")
        assert denied
        assert redaction.source_secret_occurrences(changed, source_path="src/app.py") == denied


def test_patch_inspection_reuses_complete_hunks(monkeypatch: pytest.MonkeyPatch) -> None:
    patch = (
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
        "@@ -0,0 +1 @@\n+token=settings.token\n"
    )
    with _parse_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.patch_secret_occurrences(patch)
        first = calls[0]
        assert first > 0
        assert not redaction.patch_secret_occurrences(patch)
        assert calls[0] == first
        assert redaction.patch_secret_occurrences(patch.replace("src/app.py", ".env"))
        assert redaction.source_secret_occurrences(patch, source_path="\0patch"), (
            "an arbitrary source path cannot borrow a patch-language exception"
        )


def test_exception_cannot_leave_inspection_scope_active(monkeypatch: pytest.MonkeyPatch) -> None:
    source = "token=settings.token\n"
    with _parse_count(monkeypatch) as calls:
        with pytest.raises(RuntimeError), redaction.source_inspection_scope():
            redaction.source_secret_occurrences(source, source_path="src/app.py")
            raise RuntimeError("read rejected")
        first = calls[0]
        redaction.source_secret_occurrences(source, source_path="src/app.py")
        redaction.source_secret_occurrences(source, source_path="src/app.py")
        assert calls[0] == first * 3


def test_cache_capacity_does_not_weaken_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_ENTRIES", 1)
    with _parse_count(monkeypatch) as calls, redaction.source_inspection_scope():
        redaction.source_secret_occurrences("token=settings.token\n", source_path="src/app.py")
        other = "password=settings.password\n"
        redaction.source_secret_occurrences(other, source_path="src/app.py")
        first = calls[0]
        redaction.source_secret_occurrences(other, source_path="src/app.py")
        assert calls[0] > first
        assert redaction.source_secret_occurrences('token="private-value"\n', source_path="a.py")


def test_byte_capacity_cannot_skip_uncached_sensitive_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "token=settings.token\n"
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_BYTES", len(source.encode("utf-8")))
    with _parse_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
        first = calls[0]
        assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
        assert calls[0] == first * 2, "the path bytes are part of the bounded cache key"
        assert redaction.source_secret_occurrences('token="private-value"\n', source_path="a.py")


def test_cache_cannot_change_non_utf8_text_inspection_semantics() -> None:
    source = "Unencodable text: \ud800"
    expected = redaction.source_secret_occurrences(source, source_path="record.txt")
    expected_patch = redaction.patch_secret_occurrences(source)
    with redaction.source_inspection_scope():
        assert redaction.source_secret_occurrences(source, source_path="record.txt") == expected
        assert redaction.patch_secret_occurrences(source) == expected_patch


def test_independent_read_thread_cannot_borrow_another_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "token=settings.token\n"

    def other_read() -> None:
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        with redaction.source_inspection_scope():
            assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
            assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None

    with _parse_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
        first = calls[0]
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(other_read).result()
        assert calls[0] == first * 2
        assert not redaction.source_secret_occurrences(source, source_path="src/app.py")
        assert calls[0] == first * 2
