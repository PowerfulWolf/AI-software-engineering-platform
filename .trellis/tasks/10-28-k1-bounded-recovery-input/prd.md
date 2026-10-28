# K1 bounded recovery input

## Goal

Resume the already approved K1 successor Task on the same Requirement when three complete,
independently approved `coder_reapply` patches exceed the single Coder Context window.
Preserve the original Plan, Task, source revision, patch bytes, audit history, Coder write policy,
and independent QA/Review gates.

## Current facts

- Requirement `delivery_multi_bb78e2316afca47d005384542f685174535b69db` has an approved
  RecoveryPlan `b06bffe70284000da954ea92ef7196a282f2ac1c99d795964715cc1ab80bc037`.
- Successor Task `task_recovery_b06bffe70284000da954ea92ef7196a2` has dispatch, seed and
  SQL `IMPLEMENTING` facts, but no Coder Context, native invocation or model call. Its WorkItem
  is waiting for `CONTEXT_CAPACITY`. The old UNKNOWN execution remains unknown.
- The three complete required patches are 225,678, 317,764 and 314,791 UTF-8 bytes, with
  SHA-256 respectively `26710e71e0bf31c26b61b35daa749c4575671fbc7d9e2f4aff8f23c4a9c1cfb7`,
  `11b653010f105c2c0c2ad1205a023b5130d3e5b3b5e38fc45754392a037595cc` and
  `0f9d3c7a7e0a331642a46b4bf5986aa2e1b4d7261966911e8036b4a35e5e4013`.
  Together they require about 214,410 input tokens before other required context. The
  configured limit is 256,000 tokens; all locally available Codex models advertise the same
  272,000-token context window.

## Acceptance criteria

- [ ] A current ENGINEERING principal can approve one exact, versioned input schedule bound to
  the existing approved Plan, Task, source revision, three complete patch digests and the current
  no-model-start capacity wait. No implicit approval is inferred from the previous Plan.
- [ ] One new claimed Coder Run receives one complete required patch and a manifest naming all
  three. The next source is selected only after a valid CoderProgress artifact was accepted.
  A failed or rejected Run cannot advance the schedule.
- [ ] The final candidate is forbidden until trusted accepted Coder run/Context evidence covers
  all three complete patches in order. The original full bytes remain immutable and independently
  validated on every admission; a manifest or model assertion alone is insufficient.
- [ ] Worktree, Task, Plan, branch, permissions, frozen work budget and old UNKNOWN history stay
  unchanged. QA and Reviewer remain independent Agents using the final candidate SHA.
- [ ] Crash/restart and stale claim/approval/source/patch/Context/WorkItem negative paths fail
  closed without a duplicate provider start or fabricated receipt.
- [ ] A guarded isolated MySQL public Continue fixture completes the same Requirement through
  three bounded Coder runs, QA PASS, Reviewer APPROVE and an exact handoff.

## Scope / rollback

Implement the smallest typed engineering decision, Context selection, accepted-progress coverage,
and public continuation path. No new Requirement, automatic merge, database rewrite, patch
truncation, or arbitrary source-file access. Before decision consumption, rollback may disable
activation at an idle service boundary. After consumption, retain compatible readers and roll
forward rather than removing the decision or old history.
