# Chained recovery input contract

## Signatures and wire
`RecoveryPlan.inherited_reapply_inputs: tuple[InheritedReapplyInput, ...] | None` is optional,
omitted when None, including nested canonical serialization. Entries contain origin Plan SHA,
origin recovery Task ID, original Context manifest ID, original patch URI, full patch body,
UTF-8 byte length and body SHA-256. Freeze at proposal and bind to exact Plan approval.
Origin Task is the original approved Plan's successor, not its failed predecessor.

The trusted recovery module reconstructs this value from source Task metadata and immutable
recovery records. It never consumes an agent-supplied inheritance list or arbitrary host URI.
Validate approved Plan, authorization, sealed Task, dispatch, seed, invocation and actual Context
relationship, same Team/Repository/Requirement, source epochs and exact full patch section.
Reconstruct each ancestor recursively and compare prior frozen inputs when present. Historical
Plans without the new field may have real older ancestry: read compatibility does not authorize
dropping that ancestry when proposing a new Plan. Use exact immutable stores, not SQL mutation.

## Bounds and identity
At most eight ancestor Plans/unique source inputs; refuse cycles and ambiguous origins. Deduplicate
by original Plan SHA plus body SHA, never by basename, current file coverage or model completion
claims. Preserve deterministic ancestor order. Each full body and aggregate inherited body bytes
must fit the existing MAX_CAPTURE_BYTES bound; final Context/serialized model capacity remains
an additional gate. Refuse over-budget input without truncating it or calling the provider.
Current capture and inherited patches stay separate even when overlapping; no fabricated merged
capture or maintainer-authored conflict resolution. A strict-seed successor still inherits required
historical reapply inputs if its source has them.

## Context and admission
Use source IDs `recovery.inherited_patch.<origin-plan-sha>`, exact original URI/full body,
required=True and roles=(CODER,). New current `recovery.patch` retains its existing identity.
Origin instructions explain that older complete inputs describe work still to adapt and that
the current draft is the latest implementation; neither input grants extra paths or verdicts.
Initial preparation, seed/reentry and later production Context composition use the same helper.
At final provider admission independently validate every inherited section's identity, content,
bytes/hash and truncated=False. Unexpected inherited sections and lost required input reject.

## Validation matrix
| Case | Required result |
| --- | --- |
| No recovery ancestry, no field | unchanged wire/digest, no inherited sources |
| Full old patch plus newer partial draft | both complete inputs in new Coder context |
| Third generation | transitive sources once each, same original identities |
| input_mode=None with real reapply ancestry | retain inherited required inputs |
| Missing/changed approval, Task, dispatch, seed, invocation or Context | reject before provider |
| URI/content/SHA/length/truncation mismatch or injected extra section | reject before provider |
| Cross-scope, cycle, more than eight inputs or total bytes overflow | reject, preserve scene |
| QA/Reviewer construction | no historical source patches |
| Historical None nested dump | unchanged original Plan and approval digest |

## K1 scope decision and stored data
Independent full-policy comparison found exactly one omitted current path:
src/ai_software_engineer/work_queue/mysql.py. All 37 frozen write paths were transmitted
unchanged. Coder moved position scope/table initialization into the common queue class;
the original patch kept this in execution_store.py. This is an implementation scope decision,
not proven missing platform permission propagation. Under the existing engineering delegation,
root may approve this one exact ordinary source path through the public scope supplement,
then separately inspect/approve a new Plan. That approval does not retrospectively accept Run3.
No original Task, failure, progress, worktree, budget or patch is rewritten. All inherited
content remains unaccepted source data until a new candidate passes independent QA/Review.

Independent file-only preview found exactly two actual ancestor Plans:3d26 coder_reapply
followed by622f strict seed, then an ordinary Task. Both generations' original authorization,
sealed Task, seed and invocation records are present.622f's107474-byte seed had no required
recovery.patch;3d26's original Context has the complete225678-byte body. Thus the current
expected inherited tuple has exactly one origin, subject to fresh SQL claim/step validation.
Preview report `/tmp/ase-k1-inherited-file-preview-20261019.json`, SHA-256
40159a890dddcd1785823869dcc216e64f4a76147dd83fe4744b85398c2444e7.
