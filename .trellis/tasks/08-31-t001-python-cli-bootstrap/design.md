# T001 Technical Design

## Boundaries

```text
shell
  → console script: ase
  → ai_software_engineer.cli:main
  → Typer app
```

The CLI is a delivery adapter. T001 exposes only framework-level help and version information; later commands will invoke application services through typed ports rather than importing infrastructure directly.

## Package Layout

```text
src/ai_software_engineer/
├── __about__.py   # single source for package version
├── __init__.py    # public package surface
└── cli.py         # Typer delivery adapter
```

Hatchling reads the version from `__about__.py`, avoiding duplicate version constants between package metadata and runtime output.

## Command Contract

| Invocation | Exit | Output contract |
|---|---:|---|
| `ase --help` | 0 | Contains product description and available options |
| `ase --version` | 0 | Prints `ase <semantic-version>` |
| `ase` | 0 | Shows help instead of silently doing nothing |
| unknown option | non-zero | Typer/Click prints a usage error |

## Dependency Contract

- Runtime: Typer only.
- Development: pytest, Ruff, mypy.
- Build: Hatchling.
- Python: `>=3.12`.

Versions are constrained by compatible major ranges and locked in `uv.lock`. New dependencies require a documented failure mode they eliminate.

## Good / Base / Bad Cases

- Good: installed `ase --help` works from any directory.
- Base: tests invoke the Typer app without spawning an external process.
- Bad: CLI imports SQLite, model clients, Git adapters, or embeds orchestration logic in T001.

## Test Points

- Package exposes the same version used by the CLI.
- Help and version return zero with deterministic text.
- No-argument invocation resolves to help.
- Unknown options fail without a traceback.
