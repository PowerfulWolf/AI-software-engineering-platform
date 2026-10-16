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

## Current boundary and rollback

The real attempt3 ended at `2026-10-16T03:41:48.689490Z`, rc1 after 57727ms, with no stdout
or structured output. Outcome is
`b6fa8b31a0173affe61d76ca611e894dda9b624e41ac4224d281eaff0ffeb120`,
FAILED/PROVIDER_UNAVAILABLE/transient=false, cause UNKNOWN_EXIT. stderr SHA256 is
`ee156b2dd807d4c57a44a3584dfa06577d2d42dcdd869c23faf3a4959543d4b2`.
The native stop includes a real owned_session_empty proof. RESUME operation succeeded at
`2026-10-16T03:41:54.526605Z`, checkpoint
`16b3149e6d50ed0fb790c6d9c610401a94cb11434debde664b08d81aeca63f70`.
The Task remains IMPLEMENTING revision5, attempt3, NONTRANSIENT_INFRA/WAITING_DEPENDENCY with
released ownership. Operation success is not K1 success: no candidate or QA/Review exists.

Do not repeat unknown execution without improving diagnosis. The next maintenance task,
`10-16-native-safe-failure-detail`, preserves only safe selected main diagnostics in future
ordinary provider failures. Both historical stderr bodies remain unavailable. Another attempt
requires a new current exact decision and remaining frozen ordinary work budget.

New immutable records are published. Preserve additive readers, all drafts and audit history;
if maintenance is needed, use controlled pause and a forward repair. An incompatible old
runtime must not be started by deleting new records or altering old approvals.
