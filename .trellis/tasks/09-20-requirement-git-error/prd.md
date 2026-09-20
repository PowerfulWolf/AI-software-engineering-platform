# Requirement Git baseline error

## Goal

Creating a Requirement from a directory without a committed Git baseline must explain the
missing prerequisite instead of returning the generic Manager rejection.

## Scope and acceptance

- Validate every selected directory before repository preparation or model execution.
- Distinguish a non-Git directory from a Git repository without a valid HEAD commit.
- Return a bounded, actionable Console error, identifying the affected directory.
- Preserve the generic safe fallback for unrelated errors; do not expose tracebacks.
- Replaying historical PREPARING checkpoints with null baselines must produce the same
  actionable error without changing immutable history or invoking an Agent.
- Valid committed repositories, including selected subdirectories, remain supported.
- Preserve existing failed Operations/checkpoints. Document recovery by fixing the source
  prerequisite and creating a new Requirement with the original name and directory.

## Allowed paths

`src/ai_software_engineer/multi_directory/{errors,scope,service}.py`,
`src/ai_software_engineer/web_console/manager.py`, related tests, this task directory,
and `docs/requirement-git-baseline.md`.
Knowledge synchronization is limited to the existing `web-console.md` and
`multi-directory-delivery.md` code-specs; no safety, role, Schema or state-machine rules change.

## Contract and validation

Console uses the existing `error_code`/`error_summary` envelope (no schema change), with
`GIT_BASELINE_REQUIRED` and a summary of at most 500 characters. New intake fails before
writing a Requirement checkpoint; historical PREPARING checkpoints remain unchanged.

Good: committed repository/subdirectory prepares normally. Base: an empty non-Git
directory reports Git setup instructions. Bad: an initialized repository without a commit,
a mixed selection, or a historical missing baseline is rejected before preparation.

Run focused pytest regressions, existing scope/Requirement/Console/contract tests, Ruff,
and strict mypy. Use offline fixtures; never run production Agents or mutate user sources.

## Rollback

The change is isolated in `codex/requirement-git-error-20260920`, based on
`0c5d0bb`. Revert its code patch to roll back; no database migration or historical record
rewrite is required.
