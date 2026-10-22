# Verification and original K1 treatment

## Code and contracts

Shared Coder system guidance now distinguishes explicit Coder obligations and genuine
implementation dependencies from independent QA/Reviewer execution prerequisites. Both
request and persisted Context prompt builders use it; native compilation inherits it.
Final-slice prose specifies required Coder verification. Native tooling no longer implies
that every unavailable independent verifier blocks other permitted implementation.

No Task/Plan/Context/artifact/output schema, permissions, candidate acceptance, retry,
queue or QA/Review gate changed. No production SQL was written. This fixes ambiguous
platform prose; it does not prove that a model will complete the remaining K1 work.

## Executed checks

Interpreter: main checkout `.venv/bin/python`, PYTHONPATH=src in maintenance worktree.

```sh
python -m pytest -q -p no:cacheprovider --tb=short \
  tests/agents/test_coder_slice_output_guidance.py \
  tests/agents/test_negative_credential_prompt_guidance.py \
  tests/agents/test_codex_cli.py tests/planning/test_execution_window.py
```

- Before implementation: six new request/context/native guidance cases failed; seven
  negative/compatibility/native-NOT_RUN cases passed. This establishes the missing prose
  and existing honest-NOT_RUN candidate behavior, not a causal proof of every old delay.
- New focused file after implementation:33 passed.
- Full command inside outer sandbox:104 passed;10 real owned-process observations failed
  because OS observation was denied. No test was skipped or changed to bypass this.
- Same full command through the authorized sandbox-external execution: **114 passed**.
- Scoped Ruff, format, strict Mypy and git diff check passed.
- Independent review covers the unchanged machine gates and retained Coder obligations.

## 存量数据处置

Original K1 attempt7 produced coder-progress `art_coder_9cfe2ac47d2452336216cec6f045ade4`;
26 retained changed files, only steps01/02 completed,03–08 remaining. It is not a candidate.
At `2026-10-22T08:03Z` public observation, attempt8 was waiting on real knowledge gap
`8e7a2b186c78c96d41972b6e57927bbfd4111da4cf919437d405fbd03feaa14e`;
both knowledge subcalls returned, no main invocation had started. Parent checkpoint
`7f7b1b187dd7a679ab8f3b80683f0b054c7626052fb9f5a331dc375b86b79a30`.

The gap asks whether isolated SQL, real browser and actual ASE A-to-B verification are
all ready. They have not all been demonstrated. A separately reviewed factual resolution
must say so, clarify the original role boundary and preserve actual implementation
dependencies. Use the existing exact knowledge-resolution approval and public Continue;
do not fabricate a gap, inject a prompt or reset the Task. The frozen source remains
`5547815464a04991f50a2e0532d6f2f13d8daa69`; old records stay unchanged.

Deploy only after the service's controlled drain and real exit, then reconstruct the
Host. Future prompts consume the fix. Preserve the current original knowledge wait,
progress, approvals, counters and failure history. Browser fixture execution and live
A-to-B are still separate missing prerequisites, never replaced by this maintenance test.

## Rollback

Revert the maintenance commit only at a verified controlled stop and reconstruct Host.
No record reader/version migration is required. Preserve K1 and its worktree; do not
delete a resolution, pretend NOT_RUN was PASS or roll back source/budget/history.
