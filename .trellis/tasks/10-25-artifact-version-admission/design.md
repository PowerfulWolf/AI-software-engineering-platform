# Contract

`domain.artifact.SUPPORTED_ARTIFACT_SCHEMA_VERSION` is the single version used by live admission and the immutable store; the previous store constant remains an alias. Historical Artifact.SchemaVersion remains a syntax type so intact rejected records remain readable.

`validate_current_artifact_version(artifact)` is pure. `AgentResult.validate_current_output()` converts a mismatch to AgentOutputContractError with a fixed schema_version diagnostic and a derived FAILED/INVALID_OUTPUT result, without mutating the original result. Codex validates immediately after typed decoding, before CandidateCommitSkill; Responses validates the typed current result after actual stop capture and before candidate finalization. SerialOrchestrator already runs current admission before fresh outcome and artifact publication, and keeps replay immutable.

`bind_artifact_schema_version(schema)` constrains every Artifact envelope in freshly generated Codex/Responses transport schemas to const v0.1. No historical persisted schema/model is narrowed.

Good: v0.1 candidate/progress follows normal delivery. Base: v1.0 historical SUCCEEDED can be read and hashed, but not accepted. Bad: unsupported version creates a candidate, changes history, refunds work, or reaches generic SchemaVersionError instead of typed failure control.

Tests: adapter real-Git dirty draft tests; four-role/two-transport JSON Schema negatives; generic live/replay publication tests; immutable historical-result roundtrip; existing worker wait integration. Run focused pytest modules, Ruff and strict mypy.

Existing run10 already created clean candidate 308bf36b7e225e875e5e84c1eb893fdd6e52f360 before rejection. This fix does not repair or rewrite it. No existing public recovery contract admits this SUCCEEDED unsupported candidate; a separately tested, exact engineering recovery capability is required before K1 can continue.
