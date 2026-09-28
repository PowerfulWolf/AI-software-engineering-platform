# Release, delivered App integration and retrospective

## Goal and authorization

User requests four outcomes: commit/tag the current ASE fixes; merge the codex Project's delivered
branch into its actual repository main and rebuild/install the App; enumerate bugs and solutions
across ASE platform delivery; enumerate remaining ASE work. User approved creating this task and
continuing, then clarified that retrospective/backlog cover ASE only, not business App defects.

## Confirmed facts

- ASE main is at pushed baseline `321f15e`; the only current source changes are the verified Project
  navigation repair and its tests/spec/task records. Latest existing release tag is `v0.1.1`.
- Read-only ASE API confirms original delivery DONE at `f22850f7…`, accepted candidate
  `9ac7c9ee830df548571db55ec5cf809e613467ba`, independent final verification VERIFIED.
- Actual App repository is `/Users/zhangjunshuai/workspace/codex/codex-quota-monitor`, not ASE or
  the logical Project name. Main is clean at `6d05fef…`, an ancestor of the exact accepted candidate.
- Candidate branch is `ai/task_continue_3619e92f73a4f2794610c76cbdd24bb8/attempt-1`.

## Acceptance criteria

1. Commit verified navigation changes; create an immutable annotated next patch tag `v0.1.2` and
   publish the ASE commit/tag to the configured origin. Do not move existing tags.
2. Verify repository, candidate and acceptance lineage; merge only the exact accepted candidate
   into clean main. Test/build/sign using repository instructions; install recoverably at the
   established App destination and verify launch. Preserve account data and credentials.
3. Produce an evidence-backed Chinese retrospective of ASE platform bugs and solutions. Environment
   prerequisites explain Manager coordination needs but are not counted as platform bugs; business
   App defects are excluded. Historical platform failures remain recorded.
4. Produce prioritized remaining-work list with clear current status, owner and acceptance checks.

## Boundaries

No new business implementation, mock acceptance verdict, model run, approval replay, Task/Operation
rewrite, source-worktree cleanup, credential inspection, external distribution or notarization.
If main diverged or merge conflicts arise, inspect before deciding; never force/reset user work.
Existing Mock evidence is labeled Mock; launch smoke does not claim real OAuth acceptance.
