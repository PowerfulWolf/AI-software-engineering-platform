# T001 Verification

## Standards Check

- Python package uses the required `src` layout and Python `>=3.12`.
- Typer is isolated to the CLI delivery adapter; no domain or infrastructure behavior exists yet.
- Version has one source in `src/ai_software_engineer/__about__.py`; Hatchling metadata and CLI agree.
- No untyped cross-layer payload, model SDK, database, subprocess, or network behavior was introduced.
- Dependencies are constrained in `pyproject.toml` and locked in `uv.lock`.

## Cross-Layer Check

- Packaging flow verified: `pyproject.toml → Hatchling → wheel metadata → console script → Typer app`.
- All placeholder `runtime/*` package paths were migrated to `src/ai_software_engineer/*`.
- Prompt resource location was moved under the installable package.
- Absolute imports are acyclic and expose only `__version__` from the package root.
- Task, Agent, Artifact, and state schemas were not changed.

## Unit-Test Coverage

- Package metadata version matches the public runtime version.
- `--help`, no-argument help, `--version`, and unknown-option behavior are covered.
- Remaining gap: none for T001. Domain/integration coverage begins with T002.

## Validation Evidence

```text
uv lock --check                         PASS
ruff format --check .                   PASS (28 files)
ruff check .                            PASS
mypy src tests                          PASS (4 source files)
pytest                                  PASS (5 tests)
uv build                                PASS (sdist + wheel)
isolated wheel install: ase --version   PASS (ase 0.1.0)
isolated wheel install: ase --help      PASS
JSON Schema parse                       PASS (7 schemas)
local Markdown links                    PASS
credential-pattern scan                 PASS
```

## Review Result

No blocking or major finding remains. T001 is scoped to the package/CLI foundation and does not prematurely implement orchestration, persistence, agents, or complex infrastructure.
