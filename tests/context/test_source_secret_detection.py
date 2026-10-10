"""Source snapshot validation never expands generic log/URI redaction."""

import pytest

from ai_software_engineer.redaction import (
    patch_secret_occurrences,
    redact_text,
    source_secret_occurrences,
)


@pytest.mark.parametrize(
    "source",
    [
        "password=settings.password,\n",
        'secret = foreign / "secret.json"\n',
        "return connect(password=settings.password, host=settings.host)\n",
        "token = context.token\n",
    ],
)
def test_source_references_preserve_bytes_but_generic_text_stays_conservative(source: str) -> None:
    assert not source_secret_occurrences(source, source_path="src/app.py")
    assert redact_text(source).occurrences


@pytest.mark.parametrize(
    "source",
    [
        "token=my.jwt.secret\n",
        "password=foo.bar\n",
        "password=hunter2\n",
        'password="clear-text-value"\n',
        'password=settings.password; token="actual-value"\n',
        'secret=foreign / "clear-text-value"\n',
        'secret=foreign / "sk-' + "x" * 24 + '.json"\n',
        'secret=foreign / "Bearer abcdefghijkl.json"\n',
        'secret=foreign / "ghp_' + "x" * 24 + '.json"\n',
    ],
)
def test_literal_and_ambiguous_values_remain_sensitive(source: str) -> None:
    assert source_secret_occurrences(source, source_path="src/app.py")


@pytest.mark.parametrize(
    "source",
    [
        'payload = "password=settings.password;"\n',
        'path = "src/password=settings.password;file.py"\n',
        '"""password=settings.password;"""\n',
        "# password=settings.password\n",
        'password="settings.password"\n',
        'f"password=settings.password;"\n',
        'rf"password=settings.password;{name}"\n',
        'f"""password=settings.password;{name}"""\n',
    ],
)
def test_source_syntax_cannot_grant_exceptions_inside_text(source: str) -> None:
    assert source_secret_occurrences(source, source_path="src/app.py")


@pytest.mark.parametrize("path", [None, ".env", "settings.toml", "src/app.txt", "config.json"])
def test_unknown_and_configuration_paths_never_get_source_reference_exceptions(
    path: str | None,
) -> None:
    assert source_secret_occurrences("token=my.token\n", source_path=path)


@pytest.mark.parametrize(
    "metadata",
    [
        "diff --git a/password=settings.password; b/password=settings.password;\n",
        "--- a/password=settings.password;\n",
        "+++ b/password=settings.password;\n",
        "@@ -1,1 +1,1 @@ password=settings.password\n",
    ],
)
def test_diff_metadata_does_not_get_source_exceptions(metadata: str) -> None:
    assert patch_secret_occurrences(metadata)


def test_diff_source_path_and_string_boundaries_are_preserved() -> None:
    header = (
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -0,0 +1 @@\n"
    )
    assert not patch_secret_occurrences(header + "+password=settings.password,\n")
    assert patch_secret_occurrences(header + '+payload = "password=settings.password;"\n')
    assert patch_secret_occurrences(header + '+f"password=settings.password;"\n')
    config = header.replace("src/app.py", ".env")
    assert patch_secret_occurrences(config + "+token=my.token\n")


@pytest.mark.parametrize("range_text", ["-0,0 +0,0", "-1,2 +1,2", "-0,0 +1,2"])
def test_malformed_hunk_counts_never_grant_source_exceptions(range_text: str) -> None:
    patch = (
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
        f"@@ {range_text} @@\n+password=settings.password;\n"
    )
    assert patch_secret_occurrences(patch)


def test_source_parser_resource_limit_remains_a_conservative_check() -> None:
    content = "token=settings.token\nx=" + "-" * 8000 + "1\n"
    assert source_secret_occurrences(content, source_path="src/app.py")


def test_patch_count_resource_limit_remains_a_conservative_check() -> None:
    content = (
        "diff --git a/src/app.py b/src/app.py\n"
        "@@ -1," + "9" * 5000 + " +1 @@\n+password=settings.password;\n"
    )
    assert patch_secret_occurrences(content)


@pytest.mark.parametrize(
    "source",
    [
        "token: str\n",
        "token: str | None = None\n",
        "token: object = row['token_hash']\n",
        "token: str = settings.token\n",
        'secret: Path = foreign / "secret.json"\n',
        "from dataclasses import field\nclass Session:\n    token: str = field(repr=False)\n",
        "import dataclasses\nclass Session:\n    token: str = dataclasses.field(repr=False)\n",
        "import secrets\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\ntoken: str = secrets.token_hex(32)\n",
        "from secrets import token_bytes\ntoken = token_bytes(32)\n",
        "def validate(token: str) -> None:\n    return None\n",
        "def validate(*, token: str | None = None) -> None:\n    return None\n",
        "标记 = None; token: object = row['token_hash']\n",
    ],
)
def test_python_declarations_and_proven_runtime_generators_are_not_literal_values(
    source: str,
) -> None:
    assert not source_secret_occurrences(source, source_path="src/session.py")
    assert redact_text(source).occurrences


@pytest.mark.parametrize(
    "source",
    [
        'token: str = "clear-text-value"\n',
        'token: str | None = "clear-text-value"\n',
        'def validate(token: str = "clear-text-value"):\n    return None\n',
        'def validate(*, token: str = "clear-text-value"):\n    return None\n',
        'from dataclasses import field\ntoken: str = field(default="clear-text-value")\n',
        'from dataclasses import field\ntoken: str = field(default_factory=lambda: "clear-text")\n',
        'from dataclasses import field\ntoken: str = field(metadata={"value": "clear-text"})\n',
        'from dataclasses import field\ntoken: str = field("clear-text-value")\n',
        "from dataclasses import field\ntoken: str = field(**options)\n",
        "from dataclasses import field as safe_field\ntoken: str = safe_field(repr=False)\n",
        "from unknown import field\ntoken: str = field(repr=False)\n",
        "from dataclasses import field\nfield = factory\ntoken: str = field(repr=False)\n",
        "from dataclasses import field\ndef build(field):\n    token: str = field(repr=False)\n",
        "import dataclasses\ndataclasses.field = factory\ntoken: str = dataclasses.field()\n",
        "from dataclasses import field\nfield_alias = field\ntoken: str = field()\n",
        "token: str = field(repr=False)\n",
        "import secrets as safe_secrets\ntoken = safe_secrets.token_urlsafe(32)\n",
        "import secrets\nsecrets = factory\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\ndef build(secrets):\n    token = secrets.token_urlsafe(32)\n",
        "import secrets\nsecrets.token_urlsafe = factory\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\nalias = secrets\nalias.token_urlsafe = factory\n"
        "token = secrets.token_urlsafe(32)\n",
        'import secrets\nsetattr(secrets, "token_urlsafe", factory)\n'
        "token = secrets.token_urlsafe(32)\n",
        "import secrets\nmatch value:\n    case {'value': value, **secrets}:\n        pass\n"
        "token = secrets.token_urlsafe(32)\n",
        "import secrets\nexec(code)\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\nnamespace = globals()\ntoken = secrets.token_urlsafe(32)\n",
        "token = secrets.token_urlsafe(32)\n",
        "token = secrets.token_urlsafe(32)\nimport secrets\n",
        "import secrets\ndel secrets\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\ntoken = secrets.token_urlsafe(amount)\n",
        "import secrets\ntoken = secrets.token_urlsafe(True)\n",
        "import secrets\ntoken = secrets.token_urlsafe(0)\n",
        "import secrets\ntoken = secrets.token_urlsafe(4097)\n",
        'import secrets\ntoken = secrets.token_urlsafe("clear-text-value")\n',
        "import secrets\ntoken = secrets.token_urlsafe(nbytes=32)\n",
        "import secrets\ntoken = secrets.token_urlsafe(32, extra)\n",
        "import secrets\ntoken = secrets.token_urlsafe(**options)\n",
        "token = arbitrary.token_urlsafe(32)\n",
        "token: object = row['unknown_value']\n",
        "token: object = row[lookup()]\n",
        "token: object = get_row()['token_hash']\n",
        'token: object = row["sk-' + "x" * 24 + '"]\n',
        'token: "clear-text-value"\n',
        'token: str = field(repr=False); password="actual-value"\n',
        'import secrets\npayload = "token = secrets.token_urlsafe(32)"\n',
        "import secrets\n# token = secrets.token_urlsafe(32)\n",
        'import secrets\npayload = f"token = secrets.token_urlsafe(32); {name}"\n',
        'import secrets\ntoken: str = secrets.token_urlsafe(32)\nkey = "sk-' + "x" * 24 + '"\n',
    ],
)
def test_source_type_and_stdlib_exceptions_cannot_hide_credentials_or_unknown_calls(
    source: str,
) -> None:
    assert source_secret_occurrences(source, source_path="src/session.py")


@pytest.mark.parametrize("path", [None, ".env", "settings.toml", "src/session.txt"])
def test_type_and_stdlib_exceptions_are_restricted_to_python_source(path: str | None) -> None:
    source = "import secrets\ntoken: str = secrets.token_urlsafe(32)\n"
    assert source_secret_occurrences(source, source_path=path)


def test_partial_patch_cannot_assume_an_unobserved_stdlib_import() -> None:
    patch = (
        "diff --git a/src/session.py b/src/session.py\n"
        "--- a/src/session.py\n+++ b/src/session.py\n"
        "@@ -4 +4 @@\n-token = arbitrary(32)\n+token = secrets.token_urlsafe(32)\n"
    )
    assert patch_secret_occurrences(patch)


@pytest.mark.parametrize(
    "source",
    [
        "import secrets\ndef mutate(mod):\n"
        "    mod.token_urlsafe = lambda n: 'clear-text-value'\n"
        "mutate(secrets)\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\nmutate(module=secrets)\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\nmodules = [secrets]\nmutate(modules[0])\n"
        "token = secrets.token_urlsafe(32)\n",
        "import secrets\ncallbacks = {'generate': secrets.token_urlsafe}\n"
        "mutate(callbacks)\ntoken = secrets.token_urlsafe(32)\n",
        "from dataclasses import field\nmutate(field)\ntoken: str = field(repr=False)\n",
        "from secrets import token_urlsafe\nmutate(token_urlsafe)\ntoken = token_urlsafe(32)\n",
        "import secrets\nexecute = exec\nexecute(code)\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\nexecute = eval\nexecute(code)\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\nfrom builtins import exec as execute\nexecute(code)\n"
        "token = secrets.token_urlsafe(32)\n",
        "import builtins\nimport secrets\nexecute = builtins.exec\nexecute(code)\n"
        "token = secrets.token_urlsafe(32)\n",
        "import builtins as runtime\nimport secrets\nexecute = getattr(runtime, 'exec')\n"
        "execute(code)\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\nnamespace = globals\nnamespace()['secrets'] = factory\n"
        "token = secrets.token_urlsafe(32)\n",
        "import secrets\nexecute = __builtins__['exec']\nexecute(code)\n"
        "token = secrets.token_urlsafe(32)\n",
        "import secrets\nexecute = vars(__builtins__)['exec']\nexecute(code)\n"
        "token = secrets.token_urlsafe(32)\n",
    ],
)
def test_trusted_constructor_bindings_cannot_escape_or_use_dynamic_execution(source: str) -> None:
    assert source_secret_occurrences(source, source_path="src/session.py")
