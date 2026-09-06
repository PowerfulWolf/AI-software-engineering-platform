# T035 implementation slices

Confirmed refinement: create a named Requirement Project, prepare its code scope, then discuss.
One Company sidecar owns shared knowledge, project modules, and Requirement Project journals.
Agents remain owned by the platform organization. No forced business project-group hierarchy.

## Current slice: company ownership

- Define Company/Project Knowledge Module/Requirement Project vocabulary and executable contracts.
- Add immutable company manifest, scoped project registry, selected knowledge loading.
- Bind production configuration and Team Host to one Company; namespace shared database identities.
- Place the draft joint journal under company requests and bind company identity.
- Verify company isolation and existing runtime regression, synchronize Schema and README.

## Joint delivery implementation

Implemented the four remaining slices: named request create/discuss/approve/status/resume CLI and
Host entry; deterministic projections of one approved joint Product/Design/Plan into native
deliveries; actual test execution over pinned complete candidates; restart/replay E2E tests.
Each child still uses native dispatch, MySQL, separate Coder/QA/Reviewer and exact SHA evidence.

Visualization's accepted next scope is Agent → tasks/stages → selected directories → blocking
reason. Existing static dashboard components are not yet wired to this joint request aggregate.

## Bug Analysis: completed tasks still occupied Agent capacity

### 1. Root Cause Category
- B / D / E: cross-layer contract, coverage gap and implicit assumption.
- MySQL authority aggregated immutable dispatch leases without consulting terminal Task outcomes.
  Completed tasks occupied capacity until the 15-minute lease expired. Single runs passed; enough
  tasks in a full suite hit the Agent's eight-slot limit and raised PlanningPreviewRejected.

### 2. Why isolated verification missed it
- A two-repository run stayed below eight slots; repeating later sometimes passed after fixture
  cleanup or lease expiry. Increasing capacity or sleeping would only hide the resource leak.

### 3. Prevention Mechanisms
| Priority | Mechanism | Action | Status |
|---|---|---|---|
| P0 | Runtime | Derive active leases from typed MySQL Task terminal state, preserve commits/assignments | DONE |
| P0 | Tests | DONE/BLOCKED/FAILED release slots, unfinished reservations retained, restart keeps history | DONE |
| P0 | E2E | One Host executes five joint deliveries / ten native Tasks without waiting for expiry | DONE |

### 4. Systematic Expansion
- Preview and commit-under-lock share authority.current_snapshot, so both use the same rule.
- No inference from parent status or Agent prose; missing/nonterminal Task still reserves capacity.
- SQLite compatibility authority has no production Task-store binding; do not imply this MySQL
  fix adds a generic WorkQueue release/heartbeat service. Expired-running-task protection remains
  an existing separate lease-lifecycle concern, not permission to remove in-flight reservations.

### 5. Knowledge Capture
- Updated production-team-host.md and multi-directory-delivery.md with executable contracts/tests.
- This repository has no generated spec templates; no template synchronization is applicable.
- Keep these updates with the implementation changes; no standalone spec commit while the
  related code remains uncommitted.

## Company slice verification — 2026-09-05

Implemented the company manifest, scoped project registry, selected/redacted company knowledge,
production Host namespace and baseline binding, and company-bound draft Requirement Project journal.
Verified same-company replay, cross-company lookup rejection, copied foreign journal rejection,
same-process and restarted-Host knowledge drift rejection, path/symlink/encoding/size boundaries,
and unchanged source checkout contents. README, architecture, glossary, config Schema, manifest
Schema, and executable specs are synchronized.

- Full pytest with the running local MySQL enabled: **676 passed**, no skips.
- Ruff check and format check: passed.
- Strict mypy: passed, 238 source files.
- `uv build --offline`: sdist and wheel passed after filling the missing build dependency cache.
- `git diff --check`: passed.
- No live model calls, merges, pushes, data migrations, or source project modifications.

Changes are not yet committed; stage archive should be added after merge according to
`docs/archive/README.md`. At that company-only checkpoint, the joint production flow remained open;
the following final record supersedes that progress status.

## Final T035 verification — 2026-09-05

- All four remaining slices are implemented and verified: request entry, native delivery bridge,
  actual pinned integration, restart recovery/E2E.
- Full `pytest -q` with explicit local `ASE_TEST_MYSQL_DSN`: **698 passed in 87.03s**, no skips.
- Includes five sequential two-repository deliveries on one Host (10 native Tasks), exceeding
  the eight-slot Agent capacity without expiry waits or profile capacity changes.
- Ruff check: passed; Ruff format check: 429 files already formatted.
- Strict mypy: passed, 241 source files.
- `uv build --offline`: sdist and wheel built successfully.
- `git diff --check`: passed; request/create CLI help manually inspected.
- Executable specs, five joint/request Schemas, company Schema, config, README and CLI/setup
  documentation are synchronized. Cross-layer check covered CLI → Host → joint journal → native
  dispatch/Task → candidate/evidence and the read/recovery path.
- Real MySQL/Git and offline scripted model providers were used. No live model calls, source
  business project changes, merges or pushes. Changes remain uncommitted.
- Known boundaries: CLI is synchronous, no resident queue daemon; upstream response-publication
  windows can repeat model calls; integration commands can rerun after crash; application guards
  are not an OS sandbox; no auto merge or repair DAG. Reporter paused. Live joint/team dashboard
  aggregation is the next scoped work, not claimed complete here.
- Rollback: preserve the current diff, then review/revert only this task's files. Do not reset the
  entire dirty worktree or delete company facts/candidate branches. Stage archive follows merge.
