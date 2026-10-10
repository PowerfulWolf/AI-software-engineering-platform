"""Generic clean facts reuse full text and rules within the shared bounded scope."""

import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import cast

import pytest

from ai_software_engineer import redaction


class _CountedPattern:
    def __init__(self, pattern: re.Pattern[str], calls: list[int]) -> None:
        self.pattern = pattern
        self.calls = calls

    def subn(self, replacement: str, content: str) -> tuple[str, int]:
        self.calls[0] += 1
        return self.pattern.subn(replacement, content)

    def search(self, content: str) -> re.Match[str] | None:
        return self.pattern.search(content)

    def findall(self, content: str) -> list[str]:
        return self.pattern.findall(content)


@contextmanager
def _subn_count(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    calls = [0]
    patterns = tuple(
        (kind, cast(re.Pattern[str], _CountedPattern(pattern, calls)))
        for kind, pattern in redaction._SECRET_PATTERNS
    )
    monkeypatch.setattr(redaction, "_SECRET_PATTERNS", patterns)
    yield calls


def test_clean_complete_body_reuses_six_scans_and_returns_fresh_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "x" * 179_583
    with _subn_count(monkeypatch) as calls:
        with redaction.source_inspection_scope():
            first = redaction.redact_text(body)
            with redaction.source_inspection_scope():
                second = redaction.redact_text((" " + body)[1:])
            third = redaction.redact_text(body)
            assert first == second == third == redaction.RedactedText(body, ())
            assert first is not second and second is not third
            assert calls[0] == 6
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        with redaction.source_inspection_scope():
            assert redaction.redact_text(body) == first
        assert calls[0] == 12


def test_calls_outside_scope_always_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    with _subn_count(monkeypatch) as calls:
        for _ in range(3):
            assert not redaction.redact_text("clean text").occurrences
        assert calls[0] == 18
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None


def test_one_changed_character_cannot_borrow_clean_fact_and_matches_are_not_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "passw0rd=actual-private-value"
    changed = body.replace("0", "o")
    expected = redaction.redact_text(changed)
    assert expected.occurrences == (redaction.RedactionOccurrence("secret_assignment", 1),)
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.redact_text(body).occurrences
        assert not redaction.redact_text(body).occurrences
        assert calls[0] == 6
        for _ in range(2):
            assert redaction.redact_text(changed) == expected
        assert calls[0] == 18
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None
        assert all(key[2] != changed for key in cache.facts)


@pytest.mark.parametrize(
    "body",
    [
        "sk-" + "a" * 24,
        "AKIA" + "A" * 16,
        "ghp_" + "a" * 24,
        "Bearer abcdefghijklmnop",
        "-----BEGIN PRIVATE KEY-----\nprivate-value\n-----END PRIVATE KEY-----",
        "password=first token=second",
    ],
)
def test_cached_and_uncached_sensitive_text_and_counts_stay_identical(
    monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    expected = redaction.redact_text(body)
    assert expected.occurrences
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert redaction.redact_text(body) == expected
        assert redaction.redact_text(body) == expected
        assert calls[0] == 12
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and not cache.facts


def test_generic_cannot_borrow_source_or_patch_language_exemption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "token=settings.token\n"
    patch = (
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
        "@@ -0,0 +1 @@\n+token=settings.token\n"
    )
    expected_body = redaction.redact_text(body)
    expected_patch = redaction.redact_text(patch)
    with redaction.source_inspection_scope():
        assert not redaction.source_secret_occurrences(body, source_path="src/app.py")
        assert not redaction.patch_secret_occurrences(patch)
        with _subn_count(monkeypatch) as calls:
            assert redaction.redact_text(body) == expected_body
            assert redaction.redact_text(patch) == expected_patch
            assert calls[0] == 12
            assert not redaction.source_secret_occurrences(body, source_path="src/app.py")
            assert not redaction.patch_secret_occurrences(patch)


def test_generic_clean_fact_still_enters_distinct_source_and_patch_scanners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "VALUE = 1\n"
    source_scanner = redaction._inspect_source
    patch_scanner = redaction._inspect_patch
    scans = {"source": 0, "patch": 0}

    def source(
        content: str, *, source_path: str | None
    ) -> tuple[redaction.RedactionOccurrence, ...]:
        scans["source"] += 1
        return source_scanner(content, source_path=source_path)

    def patch(content: str) -> tuple[redaction.RedactionOccurrence, ...]:
        scans["patch"] += 1
        return patch_scanner(content)

    monkeypatch.setattr(redaction, "_inspect_source", source)
    monkeypatch.setattr(redaction, "_inspect_patch", patch)
    with redaction.source_inspection_scope():
        assert not redaction.redact_text(body).occurrences
        for _ in range(2):
            assert not redaction.source_secret_occurrences(body, source_path="src/app.py")
            assert not redaction.patch_secret_occurrences(body)
        assert scans == {"source": 1, "patch": 1}


def test_actual_pattern_objects_and_order_bind_clean_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        patterns = redaction._SECRET_PATTERNS
        assert not redaction.redact_text("CLEAN").occurrences
        monkeypatch.setattr(redaction, "_SECRET_PATTERNS", tuple(reversed(patterns)))
        assert not redaction.redact_text("CLEAN").occurrences
        assert calls[0] == 12, "changed rule order must scan again"
        monkeypatch.setattr(redaction, "_SECRET_PATTERNS", patterns)
        assert not redaction.redact_text("CLEAN").occurrences
        assert calls[0] == 12
        changed_rule = cast(re.Pattern[str], _CountedPattern(re.compile("CLEAN"), calls))
        monkeypatch.setattr(
            redaction, "_SECRET_PATTERNS", ((patterns[0][0], changed_rule), *patterns[1:])
        )
        for _ in range(2):
            result = redaction.redact_text("CLEAN")
            assert result == redaction.RedactedText(
                "[REDACTED:private_key]", (redaction.RedactionOccurrence("private_key", 1),)
            )
        assert calls[0] == 24, "new matching rule cannot inherit or create a clean fact"


def test_exception_releases_generic_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    with _subn_count(monkeypatch) as calls:
        with pytest.raises(RuntimeError), redaction.source_inspection_scope():
            redaction.redact_text("clean text")
            redaction.redact_text("clean text")
            raise RuntimeError("read rejected")
        assert calls[0] == 6
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        redaction.redact_text("clean text")
        with redaction.source_inspection_scope():
            redaction.redact_text("clean text")
        assert calls[0] == 18


def test_source_can_reclaim_generic_entry_and_evicted_generic_scans_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_ENTRIES", 1)
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.redact_text("first").occurrences
        assert not redaction.source_secret_occurrences("second", source_path="record.txt")
        assert not redaction.source_secret_occurrences("second", source_path="record.txt")
        assert calls[0] == 12
        assert not redaction.redact_text("first").occurrences
        assert calls[0] == 18
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and len(cache.facts) == 1
        assert redaction.redact_text("password=private-value").occurrences
        assert calls[0] == 24


def test_priority_admission_reclaims_only_necessary_generic_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_ENTRIES", 3)
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        for body in ("a", "b", "c"):
            assert not redaction.redact_text(body).occurrences
        assert not redaction.source_secret_occurrences("owned", source_path="record.txt")
        assert calls[0] == 24
        assert not redaction.source_secret_occurrences("owned", source_path="record.txt")
        assert not redaction.redact_text("b").occurrences
        assert not redaction.redact_text("c").occurrences
        assert calls[0] == 24, "unneeded generic facts remain reusable"
        assert not redaction.redact_text("a").occurrences
        assert calls[0] == 30, "only the evicted generic body rescans"
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and len(cache.facts) == len(cache.sizes) == 3
        assert cache.bytes == sum(cache.sizes.values())


def test_patch_can_reclaim_generic_byte_budget_with_exact_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "你好"
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_BYTES", len(body.encode("utf-8")))
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.redact_text(body).occurrences
        assert not redaction.patch_secret_occurrences("x")
        assert not redaction.patch_secret_occurrences("x")
        assert calls[0] == 12
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and cache.bytes == 1
        assert len(cache.facts) == len(cache.sizes) == 1
        assert cache.bytes == sum(cache.sizes.values())
        assert all(key[0] == "patch" for key in cache.facts)
        assert not redaction.redact_text(body).occurrences
        assert not redaction.redact_text(body).occurrences
        assert calls[0] == 24
        assert cache.bytes == 1 and len(cache.facts) == len(cache.sizes) == 1


def test_priority_admission_preserves_source_and_generic_when_reclaim_cannot_fit_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_BYTES", 12)
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.source_secret_occurrences("source", source_path="a")
        assert not redaction.redact_text("other").occurrences
        assert not redaction.source_secret_occurrences("next", source_path="ab")
        assert calls[0] == 18
        assert not redaction.source_secret_occurrences("source", source_path="a")
        assert not redaction.redact_text("other").occurrences
        assert calls[0] == 18, "unadmittable parent cannot displace either existing fact"
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and cache.bytes == 12
        assert len(cache.facts) == len(cache.sizes) == 2
        assert cache.bytes == sum(cache.sizes.values())
        assert {key[0] for key in cache.facts} == {"source", "generic"}


@pytest.mark.parametrize("body", ["x" * 1_000, "你好你好", "text: \ud800"])
def test_unadmittable_source_cannot_evict_existing_generic_fact(
    monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_BYTES", 8)
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.redact_text("safe").occurrences
        assert not redaction.source_secret_occurrences(body, source_path="a")
        assert not redaction.source_secret_occurrences(body, source_path="a")
        assert calls[0] == 18
        assert not redaction.redact_text("safe").occurrences
        assert calls[0] == 18
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and cache.bytes == 4
        assert len(cache.facts) == len(cache.sizes) == 1
        assert all(key[0] == "generic" for key in cache.facts)


def test_utf8_body_bytes_share_budget_with_outer_source_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "你好"
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_BYTES", len(body.encode("utf-8")))
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.redact_text(body).occurrences
        assert not redaction.redact_text(body).occurrences
        assert calls[0] == 6
        assert not redaction.source_secret_occurrences(body, source_path="record.txt")
        assert not redaction.source_secret_occurrences(body, source_path="record.txt")
        assert calls[0] == 18, "source still scans when its own path/body cannot fit"
        assert not redaction.redact_text("你好!").occurrences
        assert not redaction.redact_text("你好!").occurrences
        assert calls[0] == 30
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and cache.bytes == 6 and len(cache.facts) == 1


def test_source_internal_generic_scans_preserve_parent_admission_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "token=settings.token\n"
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_BYTES", len(body.encode()) + len("src/app.py"))
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.source_secret_occurrences(body, source_path="src/app.py")
        first = calls[0]
        assert first > 6
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None
        assert cache.source_scan_depth == 0
        assert len(cache.facts) == 1
        assert not redaction.source_secret_occurrences(body, source_path="src/app.py")
        assert calls[0] == first
        assert redaction.redact_text(body).occurrences
        assert calls[0] == first + 6


def test_source_scan_exception_restores_generic_reuse_in_same_outer_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = redaction._inspect_source

    def rejected(
        content: str, *, source_path: str | None
    ) -> tuple[redaction.RedactionOccurrence, ...]:
        assert not redaction.redact_text(content).occurrences
        raise RuntimeError("source rejected")

    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert not redaction.redact_text("clean text").occurrences
        monkeypatch.setattr(redaction, "_inspect_source", rejected)
        with pytest.raises(RuntimeError, match="source rejected"):
            redaction.source_secret_occurrences("clean text", source_path="record.txt")
        assert calls[0] == 12, "internal scan cannot borrow the generic clean fact"
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and cache.source_scan_depth == 0
        monkeypatch.setattr(redaction, "_inspect_source", original)
        assert not redaction.redact_text("clean text").occurrences
        assert calls[0] == 12, "the same outer generic fact remains available after exception"


@pytest.mark.parametrize("reject_source", [False, True])
def test_nested_patch_source_guard_restores_outer_generic_facts(
    monkeypatch: pytest.MonkeyPatch, reject_source: bool
) -> None:
    body = "VALUE = 1\n"
    patch = (
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
        "@@ -0,0 +1 @@\n+VALUE = 1\n"
    )
    original = redaction._inspect_source
    depths: list[int] = []

    def source(
        content: str, *, source_path: str | None
    ) -> tuple[redaction.RedactionOccurrence, ...]:
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None
        depths.append(cache.source_scan_depth)
        result = original(content, source_path=source_path)
        if reject_source:
            raise RuntimeError("nested source rejected")
        return result

    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        redaction.redact_text(body)
        redaction.redact_text(patch)
        assert calls[0] == 12
        monkeypatch.setattr(redaction, "_inspect_source", source)
        if reject_source:
            with pytest.raises(RuntimeError, match="nested source rejected"):
                redaction.patch_secret_occurrences(patch)
        else:
            assert not redaction.patch_secret_occurrences(patch)
        assert depths == [2], "patch and source misses share a nested guard"
        assert calls[0] > 12, "nested source still executes its generic scan"
        after_scan = calls[0]
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and cache.source_scan_depth == 0
        assert sum(key[0] == "generic" for key in cache.facts) == 2
        redaction.redact_text(body)
        redaction.redact_text(patch)
        assert calls[0] == after_scan
        if not reject_source:
            assert not redaction.patch_secret_occurrences(patch)
            assert calls[0] == after_scan, "cached patch hit does not enter the guard"


@pytest.mark.parametrize("body", ["x" * 1_000, "你好你好", "text: \ud800"])
def test_over_bound_and_non_utf8_text_preserve_uncached_semantics(
    monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    expected = redaction.redact_text(body)
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_BYTES", 8)
    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        assert redaction.redact_text(body) == expected
        assert redaction.redact_text(body) == expected
        assert calls[0] == 12
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and not cache.facts


def test_independent_thread_does_not_borrow_parent_generic_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def other_read() -> None:
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        with redaction.source_inspection_scope():
            redaction.redact_text("clean text")
            redaction.redact_text("clean text")
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None

    with _subn_count(monkeypatch) as calls, redaction.source_inspection_scope():
        redaction.redact_text("clean text")
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(other_read).result()
        assert calls[0] == 12
        redaction.redact_text("clean text")
        assert calls[0] == 12
