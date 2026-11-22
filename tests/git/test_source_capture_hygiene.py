"""Platform source must stay recordable in continuation drafts.

Interrupted Coder work is preserved only when every touched file passes the
conservative secret detector. A false positive in platform source (for example
``token = context_var.set(...)``) makes every interrupted change to that file
unrecoverable, so new ones are caught here instead of in a live delivery.
"""

from pathlib import Path

from ai_software_engineer.redaction import source_secret_occurrences

# Files whose flagged lines are intentional: detector documentation, a test-database
# password field and a bearer header template.
_ALLOWED = {
    "src/ai_software_engineer/redaction.py",
    "src/ai_software_engineer/agents/openai_compatible.py",
    "src/ai_software_engineer/manager/python_mysql_execution.py",
    "src/ai_software_engineer/manager/python_mysql_resources.py",
}


def test_platform_source_is_recordable_by_the_continuation_capture() -> None:
    root = Path(__file__).resolve().parents[2]
    flagged = {
        path.relative_to(root).as_posix()
        for path in sorted((root / "src").rglob("*.py"))
        if source_secret_occurrences(
            path.read_text(encoding="utf-8"), source_path=path.relative_to(root).as_posix()
        )
    }
    assert flagged <= _ALLOWED, sorted(flagged - _ALLOWED)
