# T001 Implementation Plan

1. Add `.python-version` and `pyproject.toml` with Hatchling, Typer, pytest, Ruff, and strict mypy configuration.
2. Add the `src/ai_software_engineer` package with a single-source version and a minimal Typer CLI.
3. Add package and CLI contract tests.
4. Update README and milestone paths from the placeholder `runtime/` layout to the accepted `src` layout.
5. Generate `uv.lock` with Python 3.12.
6. Run Ruff format/check, mypy, pytest, and direct CLI smoke tests.
7. Review the diff against `.trellis/spec/core/python-runtime.md` and record any new executable convention.

## Validation Commands

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run ase --help
uv run ase --version
```

## Rollback Point

Before merging the T001 branch; revert the single implementation commit if any validation gate fails after integration.
