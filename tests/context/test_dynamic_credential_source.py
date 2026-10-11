"""Only proven runtime generation can exempt an exact source interpolation."""

import pytest

from ai_software_engineer.redaction import (
    patch_secret_occurrences,
    redact_text,
    source_secret_occurrences,
)


@pytest.mark.parametrize("generator", ["token_hex", "token_urlsafe", "token_bytes"])
@pytest.mark.parametrize("prefix", ["token=", "https://example.invalid/check?token="])
def test_exact_dynamic_credential_interpolation_is_source_only(generator: str, prefix: str) -> None:
    source = (
        "import secrets\n"
        "def test_negative():\n"
        f"    credential = secrets.{generator}(32)\n"
        f'    payload = f"{prefix}{{credential}}"\n'
    )
    assert not source_secret_occurrences(source, source_path="tests/security.py")
    assert redact_text(source).occurrences
    assert source_secret_occurrences(source, source_path="security.txt")


@pytest.mark.parametrize(
    "body",
    [
        'credential = "fixed-value"\nreturn f"token={credential}"',
        'credential = unknown(32)\nreturn f"token={credential}"',
        'credential = settings.token\nreturn f"token={credential}"',
        'credential = secrets.token_urlsafe(32)\ncredential = value\nreturn f"token={credential}"',
        'credential = secrets.token_urlsafe(32)\nreturn f"token={credential}"\ncredential = value',
        'credential = secrets.token_urlsafe(32)\ndel credential\nreturn f"token={credential}"',
        'if flag:\n    credential = secrets.token_urlsafe(32)\nreturn f"token={credential}"',
        'return f"token={credential}"\ncredential = secrets.token_urlsafe(32)',
        'global credential\ncredential = secrets.token_urlsafe(32)\nreturn f"token={credential}"',
        'credential = secrets.token_urlsafe(32)\nreturn f"token={credential!s}"',
        'credential = secrets.token_urlsafe(32)\nreturn f"token={credential:>10}"',
        'credential = secrets.token_urlsafe(32)\nreturn f"token={str(credential)}"',
        'credential = secrets.token_urlsafe(32)\nreturn f"token={credential}suffix"',
        'credential = secrets.token_urlsafe(32)\nreturn f"token=prefix{credential}"',
        'credential = secrets.token_urlsafe(32)\nreturn "token={credential}"',
        'credential = secrets.token_urlsafe(32)\nreturn f"token={{credential}}"',
        'credential = secrets.token_urlsafe(32)\nreturn [f"token={credential}" for x in items]',
        'credential = secrets.token_urlsafe(32)\nreturn lambda: f"token={credential}"',
        'credential = secrets.token_urlsafe(32)\ndef inner():\n    return f"token={credential}"',
        "credential = secrets.token_urlsafe(32)\ndef inner():\n    nonlocal credential\n"
        '    credential = value\ninner()\nreturn f"token={credential}"',
        'credential = secrets.token_urlsafe(32)\nexec(code)\nreturn f"token={credential}"',
        'credential = secrets.token_urlsafe(32)\nlocals()["credential"] = value\n'
        'return f"token={credential}"',
        "credential = secrets.token_urlsafe(32)\n"
        'return f"token={credential}; password=fixed-value"',
        "credential = secrets.token_urlsafe(32)\n"
        'return f"Bearer abcdefghijklmnop token={credential}"',
    ],
)
def test_unproven_or_ambiguous_interpolation_remains_sensitive(body: str) -> None:
    source = (
        "import secrets\ndef test_negative():\n"
        + "\n".join("    " + line for line in body.splitlines())
        + "\n"
    )
    assert source_secret_occurrences(source, source_path="tests/security.py")


def test_parameter_cannot_be_proven_by_a_later_assignment() -> None:
    source = (
        "import secrets\ndef test_negative(credential):\n"
        "    credential = secrets.token_urlsafe(32)\n"
        '    return f"token={credential}"\n'
    )
    assert source_secret_occurrences(source, source_path="tests/security.py")


def test_complete_patch_needs_import_and_binding_on_each_side() -> None:
    source = (
        'import secrets\ncredential = secrets.token_urlsafe(32)\npayload = f"token={credential}"\n'
    )
    header = (
        "diff --git a/tests/security.py b/tests/security.py\n"
        "--- a/tests/security.py\n+++ b/tests/security.py\n"
    )
    complete = header + "@@ -0,0 +1,3 @@\n" + "".join("+" + s for s in source.splitlines(True))
    assert not patch_secret_occurrences(complete)
    partial = header + '@@ -0,0 +3 @@\n+payload = f"token={credential}"\n'
    assert patch_secret_occurrences(partial)


@pytest.mark.parametrize(
    "writer",
    [
        "credential += value",
        "(credential := value)",
        "credential, other = values",
        "for credential in values:\n    pass",
        "with handle() as credential:\n    pass",
        "try:\n    unknown()\nexcept Exception as credential:\n    pass",
        "match value:\n    case {'credential': credential}:\n        pass",
        "import foreign as credential",
        "def credential():\n    pass",
    ],
)
def test_every_observed_binding_form_denies_provenance(writer: str) -> None:
    body = "credential = secrets.token_urlsafe(32)\n" + writer + '\nreturn f"token={credential}"\n'
    source = "import secrets\ndef test_negative():\n" + "".join(
        "    " + s for s in body.splitlines(True)
    )
    assert source_secret_occurrences(source, source_path="tests/security.py")


@pytest.mark.parametrize(
    "reflection",
    [
        "import importlib\nimportlib.import_module('secrets').token_urlsafe = factory\n",
        "import sys\nsys.modules['secrets'].token_urlsafe = factory\n",
        "import inspect\ninspect.currentframe().f_globals['credential'] = value\n",
        "import sys as runtime\nruntime._getframe().f_locals['credential'] = value\n",
        "vars()['credential'] = value\n",
        "from unittest.mock import patch\npatch('secrets.token_urlsafe', factory).start()\n",
        "from unittest.mock import patch\npatch('se' + 'crets.token_urlsafe', factory).start()\n",
        "monkeypatch.setattr('se' + 'crets.token_urlsafe', factory)\n",
        "from unittest.mock import patch as change\n"
        "change('se' + 'crets.token_urlsafe', factory).start()\n",
        "from unittest import mock\nchange = mock.patch\n"
        "change('se' + 'crets.token_urlsafe', factory).start()\n",
        "change = monkeypatch.setattr\nchange('se' + 'crets.token_urlsafe', factory)\n",
    ],
)
def test_observed_reflective_entrances_revoke_dynamic_proof(reflection: str) -> None:
    source = (
        "import secrets\n"
        + reflection
        + ('credential = secrets.token_urlsafe(32)\npayload = f"token={credential}"\n')
    )
    assert source_secret_occurrences(source, source_path="tests/security.py")


def test_class_namespace_and_closure_are_not_ordinary_name_bindings() -> None:
    source = (
        "import secrets\nclass C(metaclass=Foreign):\n"
        "    credential = secrets.token_urlsafe(32)\n"
        '    header = f"token={credential}"\n'
    )
    assert source_secret_occurrences(source, source_path="tests/security.py")


def test_separate_methods_and_utf8_positions_prove_their_own_local_values() -> None:
    source = (
        "import secrets\nclass Tests:\n"
        "    def test_first(self):\n"
        "        credential = secrets.token_urlsafe(32)\n"
        '        标记 = f"token={credential}"\n'
        "    def test_second(self):\n"
        "        credential = secrets.token_hex(32)\n"
        '        标记 = f"token={credential}"\n'
    )
    assert not source_secret_occurrences(source, source_path="tests/security.py")
