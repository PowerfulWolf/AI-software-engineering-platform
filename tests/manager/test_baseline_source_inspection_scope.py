"""Real baseline reads share bounded pure scans without reusing authorization or files."""

import ast
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pytest

from tests.orchestration.test_native_continuation_v2 import denied_paths as denied_paths
from tests.orchestration.test_native_continuation_v2 import transient_limit as transient_limit
from tests.orchestration.test_native_continuation_v2 import v2_fixture as v2_fixture
from tests.orchestration.test_native_continuation_v2 import work_limit as work_limit

LARGE_SOURCE = "VALUE = 2\nEXTRA = 3\n" + "".join(
    f"def value_{index}():\n    token=settings.token\n    return token\n\n" for index in range(300)
)


@contextmanager
def parsed_sources(monkeypatch: pytest.MonkeyPatch) -> Iterator[Counter[str]]:
    original = ast.parse
    calls: Counter[str] = Counter()

    def counted(source: str, filename: str = "<unknown>", mode: str = "exec") -> ast.AST:
        calls[source] += 1
        return cast(ast.AST, original(source, filename, mode))

    monkeypatch.setattr(ast, "parse", counted)
    yield calls
