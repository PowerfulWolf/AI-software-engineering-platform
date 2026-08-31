# T001 — Python Package and CLI Bootstrap

## Goal

Create the first executable foundation of ai-software-engineer as an installable Python 3.12+ package with a small, typed CLI entry point and reproducible development checks.

## Requirements

- Use a `src/ai_software_engineer` package layout.
- Publish an `ase` console entry point.
- Provide stable root `--help` and `--version` behavior.
- Keep business/domain logic out of the CLI module.
- Configure Ruff, strict mypy, and pytest in `pyproject.toml`.
- Lock dependencies with uv.
- Keep the runtime dependency set minimal; T001 only needs Typer.
- Update bootstrap documentation that still points to the placeholder `runtime/` package layout.

## Acceptance Criteria

- [x] `uv run ase --help` exits with code 0 and describes the platform.
- [x] `uv run ase --version` exits with code 0 and prints the package version.
- [x] `uv run pytest` discovers and passes the CLI/package tests.
- [x] `uv run ruff check .` passes.
- [x] `uv run mypy src tests` passes in strict mode.
- [x] `pyproject.toml` declares Python `>=3.12` and a reproducible build backend.
- [x] No Task, Agent, Artifact, state-machine, database, or model behavior is introduced in T001.

## Out of Scope

- Domain models and JSON Schema bindings (T002).
- SQLite persistence, Git management, Context Builder, agents, and orchestration.
- Network calls or a real model adapter.
- Parallel execution, DAGs, web UI, deployment, or plugin systems.

## Rollback

Revert the T001 commit. No persistent data, database migration, remote service, or external resource is created.
