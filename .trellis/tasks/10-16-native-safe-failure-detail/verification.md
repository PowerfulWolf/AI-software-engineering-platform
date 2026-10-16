# Verification — 2026-10-16

Baseline main: `2bee873`; maintenance worktree `/tmp/ase-fix-legacy-ignored`.
Tests use PYTHONPATH=src and the main checkout's existing .venv Python. No real provider calls.

- Actual adapter RED: selected main Error was discarded from AgentFailure.message.
- Backend initial full target suites: **162 passed / 11.59s**, covering native detail, unknown
  classification, provider contract, native CLI, fallback and durable invocation journal.
- Real offline child → real route store/outcome → fresh reopen/replay passes. Metadata SHAs,
  original stored bytes, nontransient flags and no backup call are asserted. The macOS owned
  process identity probe requires the already authorized elevated environment; its initial
  sandbox refusal was not a product failure and was not bypassed.
- Independent review reproduced synthetic proxy-key leakage through plain/nested escaped JSON.
  Six added counterexamples went RED then GREEN. Final affected detail/unknown matrix:
  **45 passed / 2.30s**; no repeat of unrelated full suites after this narrow fail-closed change.
- Display RED: Python4 failed / Node2 failed, including discarded detail and summary TIMEOUT
  contaminating old display reason. GREEN `tests/team_view/test_blocker_text.py`: **83 passed**;
  `node --test tests/team_view/native-failure-detail.test.cjs`: **4 passed**.
- Follow-up read-side review found deep non-string JSON could raise RecursionError and actual
  reader→browser double localization could reinterpret summary prose. Each went RED, then was
  repaired with a string-first decoder/exception boundary and strict already-localized native
  failure transparency. Final affected Python suite: **88 passed**; Node4 and static checks pass.
- Ruff check/format, backend targeted mypy4 files, display targeted mypy2 files and diff checks
  passed. No whole-repository typecheck/test-suite claim.
- Final safety changes add exact-key replacement after complete normalization and before bounds,
  retaining encoded-proxy fail-closed behavior. ANSI/OSC and crossing-the-500-boundary examples
  went RED→GREEN; proxy-key whitespace/control four cases also went RED→GREEN. Final authorized
  elevated command `pytest -q tests/agents/test_native_failure_detail.py
  tests/agents/test_cli_unknown_failure.py tests/agents/test_structured_models.py`:
  **88 passed / 1.97s**, including the real child/reopen and shared structured-model diagnostics.
  Five-file final targeted mypy and Ruff/format pass. An earlier sandbox run of this selection
  mistakenly included the real-child case despite a name filter: 87 passed/1 environment-owned
  process identity refusal, then the correctly elevated full selection above passed unchanged.

## Cross-layer checks

New native safe text is only ordinary provider-failure metadata. Existing typed AgentResult,
route and invocation stores preserve it through fresh readers. No Schema/SQL change. The optional
JSON-string display marker is separated before reason, Run/hash and broad old wording selection;
Python and JavaScript reject invalid/non-string markers and preserve old no-marker text. UI uses
text nodes. Dirty/timeout/abort, classifier, transient flags, budget and authority paths are unchanged.
No new duplicated redaction policy: backend/Python display reuse existing shared safe_diagnostic.
The JavaScript display only receives already redacted text, normalizes control/length and never
extracts authority from it. Summary text cannot determine retry or supply process-stop proof.

## Limits and existing data

The previous two K1 failed stderr bodies were never persisted; hashes cannot recover them.
Do not backfill. Future proxy summaries with remaining backslash encodings are conservatively
hidden, which can hide useful Windows paths. Other completed-model-call cards retain existing
fields; this change presents the safe detail in blocked-delivery text, not a new live stderr feed.
Final production recovery/deployment observations are recorded separately after independent review.

New exact proposal `operation_8031a2b86fa9037751a0ab55e151772c` sealed plan
`41534f677a136e40bc9d78c7c833e8cda888b2825bc5c52845c4a36288d1a3bd`, proof
`7af60c5b41a27d2f1afdbae3dd4600ee97f173f574f41b4aa219c532a244643e`.
Its complete patch SHA remains `9e84a2c89ce16f0ccb8171f963794c57e894949f8fb6669419ae34e0c3e6f07c`,
byte-identical to the previous two preserved inputs. It references the real attempt3 failure
and prior binding, not a guessed repaired cause. Public exact PAUSE operation
`operation_2d25eb7e03912034ae9976c69a804a16` succeeded at `2026-10-16T03:55:41.455305Z`,
binding `7b48620462dd6f1cc5369499b4239c5a89f0e022908f2513f14506d76381ea67`, sequence2,
authority `3cfb3547466291f80c897d86817c5924d9ba0fd3109b386a9e9b4e91beb0d942`.
Original Task/source/revision5 preserved; attempt3→4 is a single ordinary reservation in
WAITING_HUMAN. A fresh explicit RESUME is prepared, not submitted before tested deployment.
