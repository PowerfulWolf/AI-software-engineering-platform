"""Complete Python source can prove a narrow runtime URL credential reference."""

import pytest

from ai_software_engineer.redaction import (
    patch_secret_occurrences,
    redact_text,
    source_secret_occurrences,
)

_IMPORT = "from urllib.parse import unquote\n"
_CALL = "def parse(parsed):\n    return Settings(password=unquote(parsed.password))\n"


@pytest.mark.parametrize(
    "body",
    [
        _CALL,
        "def parse(parsed):\n    password = unquote(parsed.password)\n    return password\n",
        "def parse(parsed):\n    password: str = unquote(parsed.password)\n    return password\n",
        "def parse(parsed):\n    return Settings(\n        password=unquote(\n"
        "            parsed.password,\n        ),\n    )\n",
        "def parse(parsed):\n    return Settings(token=unquote(parsed.token))\n",
    ],
)
def test_exact_runtime_url_field_is_safe_only_as_source(body: str) -> None:
    source = _IMPORT + body
    assert not source_secret_occurrences(source, source_path="src/config.py")
    assert redact_text(source).occurrences


@pytest.mark.parametrize(
    "source",
    [
        _CALL,
        "from unknown import unquote\n" + _CALL,
        "from .urllib.parse import unquote\n" + _CALL,
        "from urllib.parse import unquote as decode\n" + _CALL.replace("unquote(", "decode("),
        "from urllib.parse import unquote as unquote\n" + _CALL,
        "import urllib.parse\n" + _CALL.replace("unquote(", "urllib.parse.unquote("),
        "if enabled:\n    from urllib.parse import unquote\n" + _CALL,
        _CALL + _IMPORT,
        _IMPORT + _IMPORT + _CALL,
        _IMPORT + "unquote = factory\n" + _CALL,
        _IMPORT + "def parse(unquote, parsed):\n"
        "    return Settings(password=unquote(parsed.password))\n",
        _IMPORT + "def unquote(value):\n    return value\n" + _CALL,
        _IMPORT + "del unquote\n" + _CALL,
        _IMPORT + "unquote.__code__ = factory.__code__\n" + _CALL,
        _IMPORT + "import urllib.parse\nurllib.parse.unquote.__code__ = factory.__code__\n" + _CALL,
        _IMPORT + "from urllib import parse as module\nmodule.unquote = factory\n" + _CALL,
        _IMPORT + "from urllib.parse import unquote as decode\n"
        "decode.__code__ = factory.__code__\n" + _CALL,
        _IMPORT + "from urllib.parse import unquote_to_bytes\n"
        "unquote_to_bytes.__code__ = factory.__code__\n" + _CALL,
        _IMPORT + "alias = unquote\n" + _CALL,
        _IMPORT + "mutate(unquote)\n" + _CALL,
        _IMPORT + "mutate(callback=unquote)\n" + _CALL,
        _IMPORT + "callbacks = [unquote]\n" + _CALL,
        _IMPORT + "exec(code)\n" + _CALL,
        _IMPORT + "execute = eval\nexecute(code)\n" + _CALL,
        _IMPORT + "namespace = globals\nnamespace()\n" + _CALL,
        _IMPORT + "namespace = locals()\n" + _CALL,
        _IMPORT + "import sys\n" + _CALL,
        _IMPORT + "from inspect import currentframe\n" + _CALL,
        _IMPORT + "import importlib as loader\n" + _CALL,
        _IMPORT + "from unittest.mock import patch as replace\n" + _CALL,
        _IMPORT + "monkeypatch.setattr(target, member, factory)\n" + _CALL,
        _IMPORT + "patch(target)\n" + _CALL,
        _IMPORT + "namespace = object.__dict__\n" + _CALL,
        _IMPORT + _CALL.replace("unquote(parsed.password)", 'unquote("clear-text")'),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(value)"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unknown(parsed.password)"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(parsed.token)"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(parsed.user.password)"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(get().password)"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(parsed['password'])"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(parsed.password or fallback)"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(parsed.password, 'utf-8')"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(string=parsed.password)"),
        _IMPORT
        + _CALL.replace("unquote(parsed.password)", "unquote(parsed.password, errors='ignore')"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(*values)"),
        _IMPORT + _CALL.replace("unquote(parsed.password)", "unquote(parsed.password, **options)"),
        _IMPORT + "def parse(password: str = unquote(parsed.password)):\n    return password\n",
        _IMPORT + "def parse(password=unquote(parsed.password)):\n    return password\n",
        _IMPORT + 'text = "password=unquote(parsed.password)"\n',
        _IMPORT + "# password=unquote(parsed.password)\n",
        _IMPORT + _CALL + 'fixed = "sk-' + "x" * 24 + '"\n',
        _IMPORT + _CALL + 'other = "password=clear-text"\n',
    ],
)
def test_url_decoder_proof_rejects_ambiguous_or_sensitive_source(source: str) -> None:
    assert source_secret_occurrences(source, source_path="src/config.py")


@pytest.mark.parametrize("path", [None, ".env", "src/config.txt", "settings.toml"])
def test_url_decoder_exception_never_applies_to_unknown_or_configuration_text(
    path: str | None,
) -> None:
    assert source_secret_occurrences(_IMPORT + _CALL, source_path=path)


@pytest.mark.parametrize(
    "namespace_access",
    [
        'namespace = getattr(marker, "__globals__")\n',
        'attribute = "__" + "globals__"\nnamespace = getattr(marker, attribute)\n',
        'lookup = getattr\nnamespace = lookup(marker, "__globals__")\n',
        'namespace = marker.__getattribute__("__globals__")\n',
        'attribute = "__" + "globals__"\nnamespace = marker.__getattribute__(attribute)\n',
        'lookup = marker.__getattribute__\nnamespace = lookup("__globals__")\n',
        'namespace = marker.__getattr__("__globals__")\n',
        'lookup = marker.__getattr__\nnamespace = lookup("__" + "globals__")\n',
        'from operator import attrgetter\nnamespace = attrgetter("__globals__")(marker)\n',
        "from operator import methodcaller\n"
        'namespace = methodcaller("__getattribute__", "__globals__")(marker)\n',
        'from operator import attrgetter as access\nnamespace = access("__globals__")(marker)\n',
        "from operator import methodcaller as invoke\n"
        'namespace = invoke("__getattribute__", "__globals__")(marker)\n',
        'import operator\nnamespace = operator.attrgetter("__globals__")(marker)\n',
        "import operator as access\n"
        'namespace = access.methodcaller("__getattribute__", "__globals__")(marker)\n',
        'from _operator import attrgetter\nnamespace = attrgetter("__globals__")(marker)\n',
        "import _operator as access\n"
        'namespace = access.methodcaller("__getattribute__", "__globals__")(marker)\n',
    ],
)
def test_reflective_namespace_access_cannot_rebind_the_imported_decoder(
    namespace_access: str,
) -> None:
    source = (
        _IMPORT
        + "def marker():\n    pass\n"
        + namespace_access
        + 'namespace["unquote"] = lambda value: "synthetic-fixed-secret"\n'
        + _CALL
    )
    assert source_secret_occurrences(source, source_path="src/config.py")


def test_partial_url_decoder_patch_cannot_borrow_the_file_import() -> None:
    patch = (
        "diff --git a/src/config.py b/src/config.py\n"
        "--- a/src/config.py\n+++ b/src/config.py\n@@ -10 +10 @@\n"
        "-    return Settings(password=unknown(parsed.password))\n"
        "+    return Settings(password=unquote(parsed.password))\n"
    )
    assert patch_secret_occurrences(patch)


def test_complete_new_file_patch_proves_exact_url_reference_without_rewriting() -> None:
    source = _IMPORT + _CALL
    patch = (
        "diff --git a/src/config.py b/src/config.py\n"
        "--- /dev/null\n+++ b/src/config.py\n@@ -0,0 +1,3 @@\n"
        + "".join("+" + line for line in source.splitlines(keepends=True))
    )
    assert not patch_secret_occurrences(patch)
