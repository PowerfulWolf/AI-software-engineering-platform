# Verification

## Independent review and measurements

Root reviewed the render helper and all call sites. Canonical operation identity and
SHA are used only for DOM invalidation. Complete operation payloads remain available;
exact approval/control signatures are unchanged. Missing or invalid keys retain full
fact comparisons, and requirement progress remains a separate history-row input.

Root independently ran `/tmp/ase-operation-signature-bench-20261011.cjs` against the
preserved 309-operation response and frozen HEAD/current assets in isolated Chrome.
Unchanged polls serialized 26,625,456 → 108,360 characters; a requirement-text change
serialized 69,741,463 → 223,263 characters. Signatures over one million characters
fell from three/eleven to zero. All 309 operations and 8,874,259 characters of original
facts remained available. Root observed CPU reductions, but concurrent browser tests
made timings noisy; character counts establish the allocation change. This does not
reduce API bytes or establish a fix for independent server Team-read delays.

## Final incremental checks

```sh
NODE_PATH=/tmp/ase-rescue-ui-test-deps/node_modules node --test \
 tests/team_view/browser/operation-render-signatures.test.cjs \
 tests/team_view/browser/product-execution.test.cjs \
 tests/team_view/browser/polling-state.test.cjs \
 tests/team_view/browser/execution-history.test.cjs \
 tests/team_view/browser/task-detail-reading.test.cjs
```

**28 passed, zero skipped**, 20.92 seconds. The four new regressions cover complete
heavy history, digest invalidation, invalid/missing digest and identity fallback,
and revoked checkpoint/plan approval closures with zero mutation requests.

```sh
node --test tests/team_view/product-execution.test.cjs \
 tests/team_view/delivery-status.test.cjs tests/team_view/readiness.test.cjs \
 tests/team_view/operation-progress.test.cjs tests/team_view/stale-operation-notice.test.cjs
```

**136 passed, zero skipped**. `node --check src/ai_software_engineer/team_view/app.js`
and `git diff --check` passed. No Python runtime/schema change or full suite was needed.

The pre-existing execution-history browser fixture produced multiple attention
notices and acknowledged only one. Worker and root independently reproduced the
same overlay interception with frozen HEAD production assets. The fixture now
acknowledges each notice after opening details, with a bounded loop and visible-state
assertion; original history assertions remain intact. No force click, hidden overlay
or production notification logic change was introduced.

## Existing data, deployment and rollback

No database/history mutation, digest rewrite, new requirement or migration. Valid
historical operation hashes already seal complete facts. Deploy while globally idle,
then refresh the same requirement/task pages. Rollback restores full serialization;
all execution, artifact, approval, candidate and complete history facts stay intact.
