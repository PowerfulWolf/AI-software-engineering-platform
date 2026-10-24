"""Full Python source distinguishes runtime handles from embedded credentials."""

from pathlib import Path

import pytest

from ai_software_engineer.redaction import (
    patch_secret_occurrences,
    redact_text,
    source_inspection_scope,
    source_secret_occurrences,
)

CONTEXT_IMPORT = "from contextvars import ContextVar\n"
CONTEXT_BINDING = (
    '_WRITE_LEASE: ContextVar[object | None] = ContextVar("write_lease", default=None)\n'
)
CONTEXT_USE = (
    "def execute(lease):\n"
    "    token = _WRITE_LEASE.set(lease)\n"
    "    try:\n        return _WRITE_LEASE.get()\n"
    "    finally:\n        _WRITE_LEASE.reset(token)\n"
)
CONTEXT_SOURCE = CONTEXT_IMPORT + CONTEXT_BINDING + CONTEXT_USE
CLAIM_SOURCE = (
    "class Indexer:\n"
    "    def tick(self):\n"
    "        for _ in range(4):\n"
    "            claimed = self.store.claim(now=self.clock())\n"
    "            if claimed is None:\n                break\n"
    "            job, source, token = claimed\n"
    "            self.store.finish(job, token)\n"
)


@pytest.mark.parametrize("source", [CONTEXT_SOURCE, CLAIM_SOURCE])
def test_full_source_proves_runtime_handle_without_changing_generic_scan(source: str) -> None:
    assert not source_secret_occurrences(source, source_path="src/runtime.py")
    assert redact_text(source).occurrences
    for path in (None, "settings.toml", "runtime.txt"):
        assert source_secret_occurrences(source, source_path=path)


@pytest.mark.parametrize(
    "source",
    [
        CONTEXT_SOURCE.replace(CONTEXT_IMPORT, ""),
        CONTEXT_SOURCE.replace("from contextvars", "from unknown"),
        CONTEXT_SOURCE.replace("from contextvars", "from .contextvars"),
        CONTEXT_SOURCE.replace(
            CONTEXT_IMPORT, "from contextvars import ContextVar as ContextVar\n"
        ),
        CONTEXT_SOURCE.replace(CONTEXT_IMPORT, "from contextvars import ContextVar as Factory\n")
        .replace("ContextVar[", "Factory[")
        .replace("= ContextVar(", "= Factory("),
        CONTEXT_SOURCE + "ContextVar = factory\n",
        CONTEXT_SOURCE + "def ContextVar(value):\n    return value\n",
        CONTEXT_SOURCE + "del ContextVar\n",
        CONTEXT_SOURCE + "alias = ContextVar\n",
        CONTEXT_SOURCE + "mutate(ContextVar)\n",
        CONTEXT_SOURCE + "ContextVar.__new__ = factory\n",
        CONTEXT_SOURCE + "_WRITE_LEASE = factory\n",
        CONTEXT_SOURCE + "del _WRITE_LEASE\n",
        CONTEXT_SOURCE + "alias = _WRITE_LEASE\n",
        CONTEXT_SOURCE + "mutate(_WRITE_LEASE)\n",
        CONTEXT_SOURCE + "_WRITE_LEASE.set = factory\n",
        CONTEXT_SOURCE.replace("    token =", "    def _WRITE_LEASE():\n        pass\n    token ="),
        CONTEXT_SOURCE.replace("    token =", "    import unknown as _WRITE_LEASE\n    token ="),
        CONTEXT_SOURCE.replace(CONTEXT_BINDING, "") + CONTEXT_BINDING,
        CONTEXT_SOURCE.replace("def execute(lease):", "def execute(lease, _WRITE_LEASE):"),
        CONTEXT_SOURCE.replace("    token =", "    global _WRITE_LEASE\n    token ="),
        CONTEXT_SOURCE.replace("_WRITE_LEASE.set(lease)", '_WRITE_LEASE.set("fixed-credential")'),
        CONTEXT_SOURCE.replace("_WRITE_LEASE.set(lease)", "_WRITE_LEASE.set(factory())"),
        CONTEXT_SOURCE.replace("_WRITE_LEASE.set(lease)", "_WRITE_LEASE.set(lease, extra)"),
        CONTEXT_SOURCE.replace("_WRITE_LEASE.set(lease)", "_WRITE_LEASE.set(value=lease)"),
        CONTEXT_SOURCE.replace("_WRITE_LEASE.set(lease)", "_WRITE_LEASE.set(*values)"),
        CONTEXT_SOURCE.replace("_WRITE_LEASE.set(lease)", "foreign.set(lease)"),
        CONTEXT_SOURCE + "namespace = globals()\n",
        CONTEXT_SOURCE + "lookup = getattr\n",
        CONTEXT_SOURCE + 'monkeypatch.setattr(ContextVar, "__new__", factory)\n',
        CONTEXT_SOURCE + "import contextvars as alternate\n",
        CONTEXT_SOURCE + "import sys\n",
        CONTEXT_SOURCE.replace("default=None", 'default="fixed-credential"'),
        CONTEXT_SOURCE.replace('ContextVar("write_lease", default=None)', 'factory("write_lease")'),
        CONTEXT_SOURCE.replace(CONTEXT_BINDING, "if enabled:\n    " + CONTEXT_BINDING),
        CONTEXT_SOURCE.replace("    token =", "    token = factory\n    token ="),
        CLAIM_SOURCE.replace(" = claimed", ' = (job, source, "fixed-credential")'),
        CLAIM_SOURCE.replace(" = claimed", " = factory()"),
        CLAIM_SOURCE.replace(" = claimed", " = claimed.value"),
        CLAIM_SOURCE.replace(
            "claimed = self.store.claim(now=self.clock())",
            'claimed = (job, source, "fixed-credential")',
        ),
        CLAIM_SOURCE.replace("claimed = self.store.claim(now=self.clock())", "claimed = unknown()"),
        CLAIM_SOURCE.replace(
            "            job, source, token = claimed",
            "            claimed = other\n            job, source, token = claimed",
        ),
        CLAIM_SOURCE.replace("job, source, token", "job, *source, token"),
        CLAIM_SOURCE.replace("job, source, token", "(job, source), token"),
        CLAIM_SOURCE.replace("job, source, token", "job, source, token, token"),
        CLAIM_SOURCE.replace("    def tick(self):", "    def tick(self, claimed):"),
        CLAIM_SOURCE.replace(
            "            job, source, token = claimed",
            "            global claimed\n            job, source, token = claimed",
        ),
        CLAIM_SOURCE + "namespace = globals()\n",
        CLAIM_SOURCE.replace("now=self.clock()", 'now="fixed-credential"'),
        CLAIM_SOURCE.replace("now=self.clock()", "**settings"),
        CLAIM_SOURCE.replace(
            "            claimed =", "            self = replacement\n            claimed ="
        ),
        CLAIM_SOURCE.replace(
            "            claimed =", "            self.store = replacement\n            claimed ="
        ),
        CLAIM_SOURCE.replace(
            "            job, source, token = claimed",
            "            alias = claimed\n            job, source, token = claimed",
        ),
        CLAIM_SOURCE.replace(
            "            job, source, token = claimed",
            "            def nested():\n                return claimed\n"
            "            job, source, token = claimed",
        ),
    ],
)
def test_ambiguous_literal_rebound_and_forged_handles_remain_sensitive(source: str) -> None:
    assert source_secret_occurrences(source, source_path="src/runtime.py")


@pytest.mark.parametrize(
    "prefix",
    [
        "class Store:\n"
        "    def claim(self, **kwargs):\n"
        '        return object(), object(), "fixed-credential"\n',
        'claim = lambda **kwargs: (object(), object(), "fixed-credential")\n',
        "Store.claim = replacement\n",
        "Store.claim: object = replacement\n",
        "del Store.claim\n",
        "from provider import Store as Store\n",
    ],
)
def test_observable_local_or_rebound_claim_provider_remains_sensitive(prefix: str) -> None:
    source = prefix + CLAIM_SOURCE
    if prefix.startswith("from provider"):
        source = source.replace(
            "    def tick(self):",
            "    def __init__(self):\n        self.store = Store()\n    def tick(self):",
        )
    assert source_secret_occurrences(source, source_path="src/runtime.py")


@pytest.mark.parametrize(
    "replacement",
    [
        "replacement",
        "Store()",
        "factory()",
        'namespace(claim=lambda **kw: (object(), object(), "fixed-credential"))',
    ],
)
def test_store_replacement_in_another_method_does_not_prove_claim_source(
    replacement: str,
) -> None:
    source = CLAIM_SOURCE + "    def replace(self):\n        self.store = " + replacement + "\n"
    assert source_secret_occurrences(source, source_path="src/runtime.py")


def test_one_external_store_constructor_is_runtime_reference_provenance() -> None:
    source = "from provider import Store\n" + CLAIM_SOURCE.replace(
        "    def tick(self):",
        "    def __init__(self):\n        self.store = Store()\n    def tick(self):",
    )
    assert not source_secret_occurrences(source, source_path="src/runtime.py")
    repeated = source.replace(
        "        self.store = Store()\n", "        self.store = Store()\n" * 2
    )
    assert source_secret_occurrences(repeated, source_path="src/runtime.py")
    assert source_secret_occurrences(source + "alias = Store\n", source_path="src/runtime.py")


@pytest.mark.parametrize(
    "arguments",
    [
        '"fixed-credential"',
        'credential="fixed-credential"',
        "*values",
        "**settings",
        "factory()",
        "scope=factory()",
        "[workspace]",
        'workspace.root / "token=fixed-credential"',
    ],
)
def test_external_store_constructor_cannot_hide_literal_or_unknown_arguments(
    arguments: str,
) -> None:
    source = "from provider import Store\n" + CLAIM_SOURCE.replace(
        "    def tick(self):",
        "    def __init__(self, workspace):\n"
        f"        self.store = Store({arguments})\n    def tick(self):",
    )
    assert source_secret_occurrences(source, source_path="src/runtime.py")


def test_external_store_constructor_allows_only_nonliteral_reference_and_path_grammar() -> None:
    source = "from provider import Store\n" + CLAIM_SOURCE.replace(
        "    def tick(self):",
        "    def __init__(self, workspace):\n"
        '        self.store = Store(workspace.root / "knowledge" / "index", '
        "scope=self.documents.scope)\n    def tick(self):",
    )
    assert not source_secret_occurrences(source, source_path="src/runtime.py")
    defaulted = source.replace("self, workspace", 'self, workspace="fixed-credential"')
    rebound = source.replace(
        "        self.store =", '        workspace = "fixed-credential"\n        self.store ='
    )
    assert source_secret_occurrences(defaulted, source_path="src/runtime.py")
    assert source_secret_occurrences(rebound, source_path="src/runtime.py")


@pytest.mark.parametrize("source", [CONTEXT_SOURCE, CLAIM_SOURCE])
@pytest.mark.parametrize(
    "extra",
    ['other = "password=clear-text"\n', 'other = "sk-' + "x" * 24 + '"\n', "# token=hard-coded\n"],
)
def test_handle_reference_does_not_exempt_other_literals(source: str, extra: str) -> None:
    assert source_secret_occurrences(source + extra, source_path="src/runtime.py")


@pytest.mark.parametrize(
    "body",
    ["    token = _WRITE_LEASE.set(lease)\n", "    job, source, token = claimed\n"],
)
def test_partial_patch_cannot_borrow_handle_provenance(body: str) -> None:
    patch = (
        "diff --git a/src/runtime.py b/src/runtime.py\n"
        "--- a/src/runtime.py\n+++ b/src/runtime.py\n@@ -20 +20 @@\n-    pass\n+" + body
    )
    assert patch_secret_occurrences(patch)


@pytest.mark.parametrize("relative", ["knowledge/index.py", "web_console/transport.py"])
def test_complete_real_platform_source_is_safe_after_classification(relative: str) -> None:
    package = Path(__file__).parents[2] / "src/ai_software_engineer"
    source = (package / relative).read_text()
    assert redact_text(source).occurrences
    assert not source_secret_occurrences(source, source_path="src/" + relative)


def test_exact_module_contextvars_import_is_equivalent_to_direct_constructor() -> None:
    source = CONTEXT_SOURCE.replace(CONTEXT_IMPORT, "import contextvars\n").replace(
        "ContextVar", "contextvars.ContextVar"
    )
    assert not source_secret_occurrences(source, source_path="src/runtime.py")
    assert redact_text(source).occurrences


@pytest.mark.parametrize("source", [CONTEXT_SOURCE, CLAIM_SOURCE])
def test_parseable_partial_hunk_cannot_claim_to_be_a_complete_module(source: str) -> None:
    patch = (
        "diff --git a/src/runtime.py b/src/runtime.py\n"
        "--- a/src/runtime.py\n+++ b/src/runtime.py\n"
        + f"@@ -20,0 +21,{len(source.splitlines())} @@\n"
        + "".join("+" + line for line in source.splitlines(keepends=True))
    )
    assert patch_secret_occurrences(patch)


@pytest.mark.parametrize("source", [CONTEXT_SOURCE, CLAIM_SOURCE])
def test_complete_body_cache_never_supplies_handle_provenance_to_patch_hunks(source: str) -> None:
    patch = (
        "diff --git a/src/runtime.py b/src/runtime.py\n"
        "--- a/src/runtime.py\n+++ b/src/runtime.py\n"
        + f"@@ -20,0 +21,{len(source.splitlines())} @@\n"
        + "".join("+" + line for line in source.splitlines(keepends=True))
    )
    with source_inspection_scope():
        assert not source_secret_occurrences(source, source_path="src/runtime.py")
        assert patch_secret_occurrences(patch)
        assert not source_secret_occurrences(source, source_path="src/runtime.py")
