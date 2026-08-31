# T005 — Immutable ArtifactStore with Integrity and Lineage

## Goal

Persist the four typed v0.1 Artifacts through a small filesystem-backed store. Every accepted artifact must be schema-valid, sealed with a reproducible SHA-256 digest, atomically written, and linked only to existing same-Task parents.

## Requirements

- Define a typed `ArtifactStore` Protocol and `ArtifactRef` value object.
- Provide `seal_artifact`/`artifact_digest` helpers using canonical JSON with the `integrity` field excluded from the digest to avoid circularity.
- Write one immutable JSON file per artifact ID using temporary-file + fsync + atomic rename.
- Validate producer/output policy through the existing typed Artifact union and require `integrity.validated=true` with a matching digest.
- Make exact re-submission of an existing artifact ID idempotent; reject changed content under the same ID.
- Require `parent_artifact_ids` and `supersedes` references to exist, belong to the same Task, and keep `supersedes` kind-compatible.
- Detect malformed, missing, tampered, or unsupported artifacts on read with stable typed errors.

## Acceptance Criteria

- [x] A sealed plan can be stored, read back, and represented by an `ArtifactRef`.
- [x] Unsealed artifacts, digest mismatches, unsupported schema versions, and invalid typed payloads are rejected before persistence.
- [x] Exact duplicate writes are no-ops; changed payloads with an existing ID are rejected and the original remains unchanged.
- [x] Missing, cross-Task, and cross-kind lineage references are rejected.
- [x] A truncated or tampered file is reported as corruption; no partial temporary file remains after a successful write.
- [x] The store has no SQLite, Docker, subprocess, model SDK, network, or PostgreSQL dependency.
- [x] Ruff, strict mypy, pytest, JSON Schema contract tests, and build checks pass.

## Out of Scope

- Cross-artifact verdict rules such as required acceptance criteria, QA PASS, Review APPROVE, or candidate revision equality; those belong to the Orchestrator guard.
- Remote object storage, database indexing, garbage collection, encryption at rest, and multi-process locking.
- Git worktrees, Context Builder, Agent adapters, retries, DAGs, or parallel execution.

## Rollback

Revert the single T005 commit. Artifact files created during manual experiments are local data and are not part of the repository.
