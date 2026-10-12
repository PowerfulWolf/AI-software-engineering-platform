# Reading retained Coder progress without repeating its full source

## Scope and signatures

`orchestration/continuation_input.py::preserved_continuation_prompt(receipt: ExecutionInterruptionReceipt) -> str` renders only a v2 `CapturedMutations` receipt already fully verified by `NativeCoderContinuation._prepare`. This is a prompt-only, internal typed reading projection, not a durable Schema, execution admission or a replacement for the original capture. Historical v1 continuation keeps its original full inline patch.

`PreservedWorktreeContinuationInput` has `kind=preserved_worktree_continuation_input`, `schema_version=v1`, full `scope`, `original_request_sha256`, `source_revision`, `base_revision`, `receipt_sha256`, `capture_sha256`, `inventory_after_sha256`, full `patch_sha256/patch_bytes`, and ordered `mutations`. Each mutation has `path`, nullable `before/after` with exact `sha256/size/mode`, and explicit `deleted`. Nulls are explicitly serialized. No before/after source body is retained by the DTO.

## Contracts and data flow

The original full immutable receipt/capture/patch and before/after bodies are reopened and validated on every preview and admission. The existing Task intent/revision, actual stopped execution, current exact request/claim/lease/parent work item, source, policy, accepted-output absence, original worktree, complete twice-observed Git mutation capture and full current inventory gates all run unchanged. Only after these checks may the service render the reading projection. It renders before publishing the existing one-use admission, so a rendering error cannot consume that admission. Preview writes nothing; prepare must equal the exact preview checked by native/Responses final preflight.

Coder uses existing scoped read_file or allowed read-only Git tools to inspect retained current files. A deletion stays absent and a rename is deletion plus addition. Before hashes cannot reconstruct old bodies; the prompt does not claim an audit/replay or a new tool path into the sidecar. All full capture bodies remain in their immutable original store. The original clean-baseline `coder_reapply` recovery patch remains a separate required complete Context source throughout, with unchanged bytes/SHA; it is not removed as a duplicate of the current draft.

Both native and Responses adapters already append the continuation reading and then apply the unchanged final serialized input capacity gate, including complete Context, wrapper, tooling and output Schema. No capacity increase, required-text truncation, candidate acceptance, permission expansion, verdict, refund or new Requirement is introduced.

## Validation matrix

| Case | Required result |
| --- | --- |
| Large lawful v2 draft, same source/branch/worktree and a new real claim | Bounded reading manifest, complete capture retained and verified, normal one-use admission |
| Historical v1 | Original full inline patch, unchanged wire and digest |
| Legitimate deletion, rename or mode-only change | Exact paths, explicit nulls, deletion and before/after SHA/bytes/mode |
| Current content, mode, symlink, binary or owner drift | Refuse before rendering/admission/provider |
| Original process group remains live, or stop/claim/scope/source cannot be proven | Refuse; no manifest or fabricated stop |
| Complete old reapply patch plus current reading fits final input | Same original complete patch, actual Schema and policy reach preflight; zero provider call during preparation |
| Actual final serialized input still too large | Original capacity receipt/wait behavior, no one-use admission consumption or provider start |

Good: same-worktree verified continuation reads actual preserved files, with the complete historical recovery patch still supplied. Base: v1 and accepted CoderProgress paths retain their contracts. Bad: treat a digest as missing source text, trim the required historical patch, increase a frozen limit or waive a workspace/stop check.

## Incremental verification

`tests/orchestration/test_preserved_continuation_input.py` exercises real Git capture and SQLite state, restart, preview no-write, exact prepare, large current draft, complete original reapply input plus native wrapper/Schema, deletion/rename/mode-only, full current inventory drift and a real live process-group refusal. Existing `test_native_continuation.py`, `test_native_continuation_v2.py`, `tests/agents/test_responses_continuation.py` and `test_model_input_preflight.py` cover existing claim, policy, missing stop, output, one-use and final-size boundaries. No full test run is required for this change.

## Existing data and rollback

No SQL, approval, Task, retry budget, Context or capture migration. The existing K1 capacity wait keeps its original no-start receipt and full draft. Use the public exact same-Task execution-baseline PAUSE and separate RESUME with a new claim after idle controlled deployment; do not reset a terminal Task or rewrite the old run. A PAUSE binding explicitly resolving the old interruption receipt uses the existing BaselineInitialWorkspaceAdmission for its preserved worktree. A later unresolved v2 interruption uses this reading projection.

Rollback only prompt generation while idle. Retain every original receipt/admission/capture/Context and compatible readers; never delete the retained workspace or introduce a synthetic outcome. Production input replay is read-only and cannot prove new execution authorization or final K1 acceptance.
