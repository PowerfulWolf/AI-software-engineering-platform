# Codex output schema repair

## Scope and acceptance

Fix provider admission for Coder completion/checkpoint output, preserving domain Artifacts,
CandidateCommit policy, independent QA/Review, and existing recovery history. Allowed changes:
Codex CLI adapter, its tests, and this contract record. Rollback: revert the repair commit.

## Contract

`_artifact_schema(CODER)` produces a strict top-level object with one required `artifact`
property. The implementation-report/coder-progress union is nested under that property;
`$defs` remain at the root so references resolve. Codex requires an object root and rejects
the previous root union with HTTP 400 `invalid_json_schema` before running the Agent.

The adapter unwraps exactly `{"artifact": ...}` before existing domain validation. Historical
bare Artifact responses remain readable. The wrapper is a transport detail and is never
persisted as a replacement for the domain Artifact. Extra wrapper fields fail validation.

Failure classification uses stderr diagnostics after the first `ERROR:` when present.
`invalid_json_schema` is non-transient INVALID_OUTPUT; HTTP 429 must have token boundaries,
so a hexadecimal digest containing 429 cannot manufacture a rate-limit diagnosis.

## Verification

- Both Coder union alternatives validate under the emitted schema; empty or extra fields fail.
- CandidateCommit and continuation fake runners exercise wrapped responses against real Git.
- Invalid schema plus echoed prompt/hash does not become RATE_LIMITED.
- Terra/high accepted the corrected schema in a synthetic provider probe (exit 0).
  This probe is not a requirement-delivery verdict or a domain-valid Artifact.
