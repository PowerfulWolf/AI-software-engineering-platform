# Command-free candidate source input

## 1. Scope / Trigger

Normal and standalone CLI QA/Reviewer, and Manager verification coordination. Read permission
over an entire repository is authority, not a declaration that every tracked file must be put
in this run's prompt. K1 demonstrated a 10 MB repository blocking QA before model invocation.

## 2. Signatures

```python
candidate_read_scope(task: Task, plan: Artifact, implementation: Artifact,
                     candidate_revision: str) -> CandidateReadScope
candidate_review_snapshot(root: Path, scope: CandidateReadScope,
                          permissions: AgentPermissions, *, max_bytes=2_000_000) -> str
BoundCandidateSource(resolver: ContextResolver).append(request: AgentRequest,
                                                      root: Path, prompt: str) -> str
estimate_input_tokens(content: str) -> int
```

`CandidateReadScope` contains `task_id`, full `base_revision` and `candidate_revision`, exact
`related_paths` from PlanStep.files, and `denied_paths` from the original Task. It is internal
composition data, not a new approval or AgentRequest wire field.

## 3. Contracts

- Original Task is parsed from the complete `task://<id>` Context section. Context identity,
  section hashes, role, attempt and revision must match the request. Sealed Plan/Implementation
  must match this Task, original base, parent chain and candidate commit, and equal their complete
  delivered Context sections after redaction. A remediation Implementation may have the original
  Plan followed by the exact persisted QA FAIL or Review REJECT feedback (and bounded Coder progress
  checkpoints) as parents, and must supersede the prior Implementation. The feedback must bind to
  that prior candidate and, for Review, to its accepted QA PASS; a first candidate keeps the Plan
  parent and may only carry Coder progress parents. No parsing of prompt prose or Coder path inventory.
- Both Git identities must be commit objects. Compare complete original base and candidate trees;
  do not use candidate parent, which loses earlier commits. Every changed path and declared plan
  dependency is required and passes read/Task deny policy before reading. Exact Plan paths only;
  directories, globs or missing dependencies require a clearer plan, not guessed closure.
- Read fixed regular UTF-8 blobs only. Required binary, symlink, submodule, non-UTF-8 and absent
  objects fail closed. Dirty/untracked bytes are not read. Checkout HEAD may differ for Manager.
  Required paths detected as secret-like are refused without echoing or renaming; exact inventory
  must not leak credentials in filenames or falsely claim a renamed source path.
- Include all base-to-candidate hunks with five context lines. Disable external diff, textconv,
  rename aggregation and relative-path effects. Renames appear as deletion/addition. New/deleted
  files have complete contents in diff; modified files explicitly have `full_content_read=false`.
  Unchanged plan dependencies have full candidate content. Unchanged regions/dependencies outside
  this view were not read; missing context/evidence requires NOT_TESTED or a knowledge gate.
- `SOURCE_PACKAGE` records path inventory, selection reason, presentation, base/candidate blobs
  and content SHA, diff frame ID/type, original diff SHA, delivered UTF-8 bytes/SHA, complete hunk
  coverage and redaction counts. `SOURCE_DIFF` is complete redacted original text, not an escaped
  JSON string. Package digest hashes canonical manifest bytes followed by delivered diff bytes.
  Consume the declared byte length; an END-like string in source is ordinary untrusted data.
- Git output is streamed with stdout limit and 64 KiB stderr limit; exceed either or timeout and
  kill/reap the process group, returning no partial package. Disable hooks/fsmonitor, global/system
  config, replace objects, lazy fetch and all Git network protocols. Each required old/new blob
  also has a conservative 2 MB safety cap even if its diff is small. Package/wrapper totals must
  fit the separate byte bound; this is not a tokenizer or permission expansion.
- Production factory always supplies BoundCandidateSource to CLI adapters. Verifiers append it
  after receipts and image descriptions, then check the entire final serialized prompt against
  the original Context `max_input_tokens` with the shared ceil(chars/4) estimator. No truncation or
  automatic expansion. Low-level adapters without typed context retain the conservative legacy
  whole-repository helper. Manager uses the same scope and snapshot constructors directly.
- CLI user JSON objects are serialized as objects with `content_format=json`, preserving every
  field/value and non-JSON message exactly; this avoids a second JSON string escape layer. Context
  stores, raw section hashes and artifact wire formats do not change. Nothing becomes a verdict.

## 4. Validation & Error Matrix

| Input | Outcome |
| --- | --- |
| Large unrelated baseline, small complete candidate difference | Complete source view; no unrelated content |
| Task/revision/parent/digest or delivered Context mismatch, including unverified remediation feedback | WorkspacePolicyError; zero model invocation |
| Denied required path, unsupported blob, missing dependency/object | Refuse complete view, no partial review |
| Tree/blob/tag identity instead of commit | Refuse before tree reading |
| Source/process/final prompt exceeds bound | Stable refusal; no truncation, retry or fabricated verdict |
| Missing unchanged function or independent test evidence | Verifier must report unmet prerequisite |

CLI maps source refusals to durable non-transient POLICY_VIOLATION using its existing failure
contract. This does not turn a source/environment precondition into a QA code verdict.

## 5. Good / Base / Bad Cases

Good: 20 K1 changes and the two declared unchanged dependencies fit while unrelated history is
outside the explicitly declared view. Base: offline real Git fixture with >2 MB unrelated file.
Bad: increase the cap, slice hunks, trust changed_files, use candidate^, or claim full-file review
from a difference-only view.

## 6. Tests Required

- `test_candidate_review_source.py`: multi-commit changes, full additions/deletions/renames/modes,
  deny rules, missing/binary/symlink/non-UTF-8/commit-object checks, output bounds and byte/hash
  roundtrip with quotes, backslashes, Unicode and pseudo frame boundaries.
- `test_candidate_source_binding.py`: real production factory/CLI seam, unchanged native read-only
  and no-command argv, mismatched artifact facts, final receipt+prompt budget, zero calls on failure,
  exact preservation of all structured and plain message values.
- `test_manager_reads_real_candidate_scope_without_unrelated_repository_bulk`: Manager's actual
  coordinate path with real Git and sealed artifacts; no source helper mock.
- Existing CLI, production factory and Manager cache/order tests remain focused compatibility gates.

## 7. Wrong vs Correct

Wrong: whole-repository read allowlist -> load every file -> arbitrary larger cap or silent omission.
Correct: original Task + sealed lineage -> complete base/candidate difference + explicit dependencies
-> total prompt budget -> controlled evidence -> independent QA/Reviewer.

## Existing data and rollback

No database migration or rewrite is needed. Keep the original terminal Task, candidate, failed
pre-model QA run, exhausted coordination budget and approvals. Load the verified platform change
only when no role is active; propose a new exact candidate-verification plan with its required
execution capability, approve it, and independently verify the same candidate. Do not rerun Coder
or reset a terminal Task. A previous approval cannot authorize new prerequisites. Roll back the
platform commit and restart when idle; retain all sidecar facts and any new execution receipts.
