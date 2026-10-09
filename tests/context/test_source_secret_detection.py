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
