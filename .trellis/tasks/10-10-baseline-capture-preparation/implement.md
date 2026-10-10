# Implementation

- `BaselineProposeCommand.require_current` compares original intent/revision/work item/source
  before source preparation can publish missing invocation facts.
- Host validates exact public Requirement/Task association, normalizes only an internal typed
  command copy to the native child Requirement, and binds it to the production fact collector.
- `ProductionBaselineFactCollector` runs proposal-only fact collection within its existing
  real Task lock/SQL idle fence. SOURCE_REBIND unresolved uncertainty/platform waits reuse
  `DeliveryWaitFactCollector`; PAUSE/preflight/legacy and execute/continue skip collection.
- Existing receipt integrity, real stop/current process, full lawful source inventory,
  original outcome handling, budget accounting and exact human PAUSE/RESUME remain unchanged.
- New focused tests cover stale command rejection before publication, exact one-time sealing,
  unchanged Task/queue/budget/source, retained refusal, missing/unknown/output/scope/claim
  boundaries, success preservation and absent/nonnested execution scope.
- Public regression uses real Git/MySQL/owned subprocess through a real delivery_multi parent.
  It injects the first receipt publication failure, keeps the true stopped draft, rejects a
  foreign parent and stale revision, seals the native child receipt, adopts exact native-rule
  changes with PAUSE and explicitly continues the same Task/branch/worktree through independent
  QA/Review to DONE.

No production operations, schema fields, SQL migrations, old audit rewrites or workspace resets.
Existing users load the compatible runtime while idle and use the same exact proposal→review→
PAUSE→RESUME path after the target commit exists in the registered clone.
