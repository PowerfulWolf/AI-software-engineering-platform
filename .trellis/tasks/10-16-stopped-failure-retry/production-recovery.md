# K1 existing-data recovery — 2026-10-16

Maintenance is general platform behavior; the K1 draft is owned by its native Coder.
No direct production SQL write, Task reset, source patch or historical record rewrite was used.
Maintenance commits `eccee3a` and `2bee873` were merged and pushed to main, then loaded by a
controlled idle restart. Console contract version is 10.

## Exact original scope

- Project: `project_ai-project_034252eb3595`.
- Requirement: `delivery_multi_bb78e2316afca47d005384542f685174535b69db`.
- Task: `task_recovery_622f711324450abfffedc2a8d696e2de`.
- Approved execution source remains `774e0a6fcc920d9a6ce3738e80b9cc43045be7eb`.
- Original failed Run: `run_1d8a8ff39dbe4d9b8a6451b27736c752`.
- Failed outcome: `c09e52fc50406b5dab43c8125d6e2623b8847a2a038a1aa43b16c604b77cd8b2`.

The real rc1/empty-output/provider-unavailable/nontransient failure remains unchanged. Its
historical stderr body was not saved, so the original cause remains unknown; a digest cannot
reconstruct it. This recovery accepts that uncertainty and spends one ordinary work attempt.

## Public PAUSE, then independent RESUME

1. Public proposal `operation_77fccebed075b2bc9e1f7a3352acbfd7` sealed plan
   `c7f7b42d0c0ee5198f8f8da4a29cb5b5cf0e13fb5ab2be252d16b28f664816df`.
   Proof is `b3a6ef62a52df18e3dec51f08c98d0d2a1c888b33d81d8606a8b7048865a1371`.
   The complete 107474-byte retained patch SHA256 is
   `9e84a2c89ce16f0ccb8171f963794c57e894949f8fb6669419ae34e0c3e6f07c`,
   byte-identical to the prior approved recovery input: 16 source files, 2806 inventory items.
2. Exact public EXECUTE in PAUSE mode, `operation_ef5296bd36889588e1c85598aac4b2a4`,
   succeeded at `2026-10-16T03:34:02.428727Z`. Binding is
   `a083d42474371a706fd69944075c8c4a22a29d6fd846b6d734b4b640f03808a2`;
   authority is `681084250c2ad736ebea27e02e4e123a25832079eb928e5e7f6ee3dbb6c020cf`.
   Same Task/source/revision5, ordinary attempt2→3, WAITING_HUMAN, no new Coder invocation.
3. A fresh public summary selected that exact hold, current disposition, Task intent/revision
   and checkpoint. Separately authorized RESUME was submitted as
   `operation_8ff51443bd6d8bf80cd13b83d098463e` at `2026-10-16T03:37:48Z`.
   It obtained a live claim, performed normal knowledge preparation, then started native Coder
   `run_ea0c39c1908e447d9efbafc66b68c4a7` at `2026-10-16T03:40:51.553031Z`.
   New lease: `lease_9efcfaaa2f6477058bc8f964`; new Context:
   `ctx_799c3dae734b75081903130278deb9d9dbafc9956c6a0bbe5945bd576a383bc7`.

## Independent preservation and audit verification

The independent read-only verifier matched all 195 pre-existing immutable files by SHA256,
revalidated plan/binding/authority/proof, and matched exactly one new HumanActionEvent:
`evalevt_failure_a083d42474371a706fd69944075c8c4a`. Its action is SUPPLY_EVIDENCE;
Task, evaluation case, authority-file URI, authority time and unknown-cause/ordinary-work note
match the immutable operator authority. The old failure is not relabeled or refunded.

Local detailed report: `/tmp/ase-k1-stopped-failure-independent-audit-20261016.json`, SHA256
`60c9f12ba4044a500cbcf75d194bd591687eb7d0e7aa56ed29e8cc0edbad6259`.
The native Console shows the original K1 under active requirements and distinguishes knowledge
preparation from Coder execution. These checks do not assert candidate, QA/Review or DONE.

## Preserved attempt3 boundary

The real attempt3 ended at `2026-10-16T03:41:48.689490Z`, rc1 after 57727ms, with no stdout
or structured output. Outcome is
`b6fa8b31a0173affe61d76ca611e894dda9b624e41ac4224d281eaff0ffeb120`,
FAILED/PROVIDER_UNAVAILABLE/transient=false, cause UNKNOWN_EXIT. stderr SHA256 is
`ee156b2dd807d4c57a44a3584dfa06577d2d42dcdd869c23faf3a4959543d4b2`.
The native stop includes a real owned_session_empty proof. RESUME operation succeeded at
`2026-10-16T03:41:54.526605Z`, checkpoint
`16b3149e6d50ed0fb790c6d9c610401a94cb11434debde664b08d81aeca63f70`.
At the attempt3 boundary, the Task remained IMPLEMENTING revision5, attempt3,
NONTRANSIENT_INFRA/WAITING_DEPENDENCY with
released ownership. Operation success is not K1 success: no candidate or QA/Review exists.

Do not repeat unknown execution without improving diagnosis. The subsequent maintenance task,
`10-16-native-safe-failure-detail`, preserves only safe selected main diagnostics in future
ordinary provider failures. Both historical stderr bodies remain unavailable. Any further attempt
requires a new current exact decision and remaining frozen ordinary work budget.

## Diagnostic retry after controlled compatible deployment

The exact second proposal `operation_8031a2b86fa9037751a0ab55e151772c` sealed plan
`41534f677a136e40bc9d78c7c833e8cda888b2825bc5c52845c4a36288d1a3bd` and stopped-failure
proof `7af60c5b41a27d2f1afdbae3dd4600ee97f173f574f41b4aa219c532a244643e` against the
unchanged attempt3 failure. Public PAUSE operation `operation_2d25eb7e03912034ae9976c69a804a16`
succeeded at `2026-10-16T03:55:41.455305Z`, reserving ordinary attempt4 on the same Task,
revision5 and frozen source. Binding is
`7b48620462dd6f1cc5369499b4239c5a89f0e022908f2513f14506d76381ea67`, sequence2;
authority is `3cfb3547466291f80c897d86817c5924d9ba0fd3109b386a9e9b4e91beb0d942`.
The full 107474-byte patch SHA remains `9e84a2c89ce16f0ccb8171f963794c57e894949f8fb6669419ae34e0c3e6f07c`.

Independently reviewed diagnostic commit `1c7a5e1` was merged/pushed to main and loaded by
controlled idle restart (PID99829→14732). A fresh summary selected the unique exact pause;
public independent RESUME `operation_abe521ca402b857ad21aa1a55fcf0c18` was accepted at
04:13 UTC. The resume authority was sealed at `2026-10-16T04:13:18.175574Z`.
Read-only SQL verified Task IMPLEMENTING/revision5/attempt4 and unchanged source774e0a6.

The new claimed knowledge Run `run_knowledge_731795fdc664daf49c2cb144cc6014bb` completed
intent and assessment in 106519ms/181452ms, with native completed/rc0 stops, within their
separate 1800-second windows. Repository knowledge gaps permitted subsequent repository
inspection. Normal claimed main Coder invocation then began at
`2026-10-16T04:19:03.443598Z`: `run_0d6c5798f57b4c309acaa5d8d531bc08`,
Context `ctx_12bf600e4820c0de0a5cb66d71acc44c0a68bab4e81f40cf3fd0678f6f20417d`,
lease `lease_cd17229ad0cf2eb207114e05`, start SHA
`1068e95f07cc5119e8e8c4325e693cc8b8753ac9fef9103676fc9ea29d23ded7`.
The knowledge phase and main execution are separate facts; this start is not a final result.

Independent file audit `/tmp/ase-k1-diagnostic-retry-independent-audit-20261016.json`, SHA
`2caf1c8de5919a26b8ea88b1da1db086d2d3f94bafed01954d864035d068bda5`, matches all195
original files, both binding links and the exact new
`evalevt_failure_7b48620462dd6f1cc5369499b4239c5a` HumanActionEvent. The audit verifies the
current authority/source/inventory/patch and independent resume record; it does not infer
candidate completion or QA/Review from authorization or Operation state.

## Accepted successor and normal continued delivery

The diagnostic retry returned actual coder-progress in1090808ms, outcome
`55ea2730d1c75aa6b1ee50e9289cf4325cc6a4fb128a153aeb9c5e469179a3b9`.
New sealed artifact `art_coder_05714ae8093596356e007b54dc42490b`, SHA
`640daf6e30813ee954265873f7dffae0ff73dee44edab7598fc52de25cd89b5f`, completes01/02,
retains03–08 and supersedes the old accepted checkpoint. Its test summaries include both
NOT_RUN and FAIL entries, so it is not a full verification success or candidate.

Actual SQL StateEvents—not just the SUCCEEDED adapter result or publication receipt—confirm:

- `evt_f89c355628964a32872b8fbe2d418c15` at `04:37:14.394368Z`,
  IMPLEMENTING→CONTINUE_REQUIRED, attempt4, referencing the new artifact;
- `evt_f74504f6c005422c8f36e06036ed484d`, CONTINUE_REQUIRED→QUEUED;
- `evt_9015b0a389e7406f84f408ca32ec6410`, QUEUED→IMPLEMENTING, attempt5.

Task revision is now8, attempts5, still the same source774e0a6. The next real Coder call,
`run_411785d71edc4be4896a7f04d5f46b3b`, began at `2026-10-16T04:41:30.508236Z`, Context
`ctx_a2d3245dc8e63356fc409dea02be73e96db5b3bf64e301a8cf9267e44361c62a`.
Its sealed request includes the original plan and new progress, completed01/02, selected03/04,
and deferred05–08. Authorized work remaining is6; no extra recovery reservation was made.

Independent audit `/tmp/ase-k1-progress-successor-independent-audit-20261016.json`, SHA
`fb306bf6e62a9b43ccf04898a1033bb097bf624d125501384ba05585f31b46e0`, rechecks all195
original-file SHAs unchanged and validates the new artifact and actual successor request.
No historical retirement declaration was edited or reinterpreted. A separate forward-only
fix in `10-16-retry-progress-continuity` prevents new same-base failed retries from causing
this redundant completed-step selection in future. Current K1 has recovered continuity
through its legitimate new artifact. Candidate, independent QA/Review and DONE remain pending.

New immutable records are published. Preserve additive readers, all drafts and audit history;
if maintenance is needed, use controlled pause and a forward repair. An incompatible old
runtime must not be started by deleting new records or altering old approvals.
