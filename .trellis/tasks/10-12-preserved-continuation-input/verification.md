# Verification

Red: `.venv/bin/python -m pytest tests/orchestration/test_preserved_continuation_input.py -q -x` failed with a 176421-character inline prompt, versus bounded same-worktree reading requirement. This exercised real Git capture, restart, fresh current workspace checks and preview.

First focused compatibility batch: 92 passed in 251.02s across preserved-input, native v2, native v1, Responses continuation and final model input preflight. Additional deletion/rename/mode-only and complete old-patch final-input tests were then added; final focused and independent review results follow below.

Production exact input was reopened read-only from ContextCapacityReceipt 7881f233..., Context ctx_f40fc856... and full original continuation receipt run_e197336.... No production prompt/source was copied into this repository, no model was invoked, and no production durable fact was written. Recorded old final estimate 285444 > 256000; pure prompt replay gave approximately 251902 with the preserved-worktree reading and complete original historical reapply patch. The later actual native tooling/output-Schema replay is recorded in the production observation report. These are the platform deterministic estimates, not provider tokenizer measurements or delivery acceptance.

Actual native `_compile_input` replay includes manager-provisioned Python tooling and output Schema: old **285444** exactly matches the stored original final-input receipt; new **252481** <= **256000**. No provider invocation, production durable write or Context modification. Temporary native preparation resources were closed normally.

Final owned regression: 11 passed in37.60s; includes real live-group refusal. Ruff, strict mypy(--follow-imports=silent,3ownedfiles), git diff --check PASS. The earlier92-test batch is overlapping and is not added to11 as a unique test total.

Independent reviewer PASS: new preserved-input + native v2 + one exact v1 stopped-draft case,30passed in87.61s. Ruff/strictmypy4/diffcheck PASS. Reviewer verified full read/write authorization still runs for every mutation and before-body hashes do not claim reconstruction.
