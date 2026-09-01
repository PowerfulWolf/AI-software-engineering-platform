# T007 — Deterministic Context Builder and Router

## Goal

Compile organization knowledge, project facts, Task intent, role instructions, candidate revision, and declared upstream evidence into a minimal, deterministic, redacted, budget-bounded `ContextBundle` for one Agent Run.

## Requirements

- Define typed `ContextSource`, `ContextSection`, `ContextRedaction`, `ContextBudget`, and `ContextBundle` contracts plus the `ContextBuilder`/`ContextRouter` seams.
- Route only sources applicable to the requested role; keep policy before project/task/role/evidence sections and never accept implicit Agent-to-Agent messages.
- Read file sources relative to a configured project/worktree root through the T006 path policy; reject traversal, `.git`, symlink escape, missing required sources, and denied paths.
- Include Task, effective machine permissions, role instructions, optional candidate revision, and explicitly declared source/evidence content with URI, SHA-256, token count, and deterministic ordering.
- Redact common API keys, bearer tokens, private keys, and password/secret assignments before hashing and counting; record only redaction kind/count, never secret values.
- Enforce `max_input_tokens`; omit or deterministically truncate optional sections, but raise a stable budget error when required policy/task/role content cannot fit.
- Derive a stable `ctx_<sha256>` identity from the manifest payload excluding `built_at` and the identity itself; identical input yields the same ID while timestamp remains observational metadata.
- Treat repository files, Task prose, and command output as data; context rendering must preserve the policy section as a non-overridable instruction boundary.

## Acceptance Criteria

- [x] Same Task, role, attempt, sources, policy, and budget produce the same `context_id`, section order, hashes, and token counts.
- [x] Role-specific sources are routed correctly and all sections carry URI, SHA-256, content, and token count.
- [x] Secrets are replaced before persistence/counting and only typed redaction metadata is exposed.
- [x] Context never exceeds `max_input_tokens`; optional content truncates/omits deterministically and required overflow raises `ContextBudgetExceeded`.
- [x] File sources are root-bound and policy-checked; traversal, `.git`, symlink escape, missing required files, and denied paths fail closed.
- [x] Candidate revision is propagated as the exact `source_revision`; prompt-injection text remains data and cannot change role/policy routing.
- [x] ContextBundle Python wire payload satisfies a new `schemas/context.schema.json` contract.
- [x] Ruff, strict mypy, pytest, lock, build, and diff checks pass.

## Out of Scope

- Vector databases, embeddings, semantic retrieval, remote context services, prompt template files, model calls, artifact persistence, or parallel routing.
- Git diff generation itself; the builder accepts an exact candidate revision and declared evidence/source content from the Repository Plane.

## Rollback

Revert the single T007 commit. Context bundles are immutable run metadata; no existing Task, Artifact, SQLite, or Git state is mutated by this module.
