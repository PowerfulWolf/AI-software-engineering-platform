# T044 D3 — Coder-owned conflict reapplication

## Why

The real approved recovery18977a93 stopped before model invocation: 14 captured files merged cleanly,
but production_host.py had an import-area conflict between interrupted edits and newer platform code.
The isolated-index preflight correctly preserved both source and target; this was an unsupported
recovery input mode, not evidence of model quota failure. No candidate or QA/Review was produced.

## Change

Explicit `--coder-reapply` proposal stores `RecoveryPlan.input_mode="coder_reapply"` under a new hash
and human approval. Absent mode retains historical hashes and strict Git seed rejection. The new Coder
starts clean and receives the entire approved patch as required, Coder-only context; initial receipt
binds the empty workspace. Exact patch content/URI/hash/non-truncation is checked before invocation.
The normal candidate, policy, at-most-once, QA/Review and original-history guards are unchanged.

Chosen over handing an unmerged index to Coder: no wider dirty/merge-state exception is needed. No
manual requirement edits by Astra, no dependency/SQL changes, no automatic merge/push/deploy.
This decision and its executable error matrix are in the D3 recovery spec (`update-spec` workflow).

## Verification

Final full regression: **890 passed /370.71s**, using only the dedicated MySQL test database and
offline providers. Includes actual strict Git conflict rejection, clean-base reapplication, missing
patch provider-admission refusal, independent QA/Review and preserved original single/joint history.
Final strengthened Schema/patch-budget tests: **3 passed /0.31s**. Ruff check/format508files, strict
Mypy286files, offline lock/sdist/wheel build and diff-check passed. Build uses /tmp cache/output;
the first home-cache attempt was denied by the desktop sandbox and made no dependency change.
Cross-layer review traced mode → plan hash/approval → seed store → context → provider admission;
default mode is not a fallback and missing patch cannot be replaced by caller-chosen context identity.
Reading the actual historical plan18977a93 with new code validated its unchanged digest and
capture955b3247 (15 files). This does not prove the actual platform-root requirement is delivered.
New exact production proposal and approval remain necessary after this commit; zero live models.

## Rollback / limits

Revert this isolated platform commit before new-mode use. Existing old-mode records retain identity;
an old reader rejects the new optional field instead of guessing its meaning. Binary/add/delete captures,
recovery-of-recovery, parent adoption, budget expansion and automatic approval remain out of scope.
