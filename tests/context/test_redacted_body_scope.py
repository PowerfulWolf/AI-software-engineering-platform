"""Repeated sealed bodies keep bounded pure detection facts after small fields."""

import pytest

from ai_software_engineer import redaction
from ai_software_engineer.domain.execution_native_rules import NativeRuleEpochBody
from tests.context.test_generic_redaction_scope import _subn_count


def test_sealed_body_clean_fact_has_priority_over_opportunistic_small_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_ENTRIES", 4)
    content = "Complete sealed organizational guidance.\n" * 100
    with redaction.source_inspection_scope(), _subn_count(monkeypatch) as calls:
        for i in range(4):
            redaction.redact_text(f"small field {i}")
        before = calls[0]
        assert redaction.redact_body_text(content).text == content
        once = calls[0]
        assert once > before
        for _ in range(3):
            assert redaction.redact_body_text(content).text == content
        assert calls[0] == once
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None
        assert len(cache.facts) <= 4
        assert cache.bytes == sum(cache.sizes.values())


def test_body_priority_keeps_source_capacity_and_never_retains_sensitive_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_ENTRIES", 1)
    with redaction.source_inspection_scope():
        redaction.redact_body_text("complete clean body")
        redaction.source_secret_occurrences("def verified():\n    return 1\n", source_path="app.py")
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        assert cache is not None and len(cache.facts) == 1
        assert all(key[0] == "source" for key in cache.facts)
        dirty = "api_key = 'secret-example'"
        assert redaction.redact_body_text(dirty) == redaction.redact_text(dirty)
        assert all(key[2] != dirty for key in cache.facts)


def test_sealed_native_body_validator_still_rejects_unredacted_content() -> None:
    import hashlib

    from pydantic import ValidationError

    from ai_software_engineer.repository_profile import NativeRuleKind, NativeRuleSource

    content = "api_key = 'secret-example'"
    payload = content.encode()
    source = NativeRuleSource(
        kinds=(NativeRuleKind.README,),
        relative_path="README.md",
        uri="project://repository_fixture/README.md",
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
    )
    with redaction.source_inspection_scope(), pytest.raises(ValidationError):
        NativeRuleEpochBody(
            source=source,
            content=content,
            content_sha256=hashlib.sha256(payload).hexdigest(),
            content_bytes=len(payload),
        )
