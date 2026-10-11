# Operation result scope compatibility

The complete Operation writer permits a delivery-bound deletion to return a
project-only command result, and historical Continue operations may return a
different native delivery in the same Project. The summary reader incorrectly
rejects both before filtering, making every scoped summary return 503.

Keep the submitted intent as the Operation owner. Add explicit independent result
locators and a typed relation; no inferred parent/child association. Unknown result
relations remain readable audit records and never provide current delivery stage,
checkpoint, task/work, baseline, handling or approval facts. A missing delivery in
a delivery-bound result is a known command-only result only for DELETE_REQUIREMENT.
Foreign Project/Team and corrupt complete bytes still reject the entire read.

Acceptance: actual deletion producer → immutable store replay → summary HTTP is
200/304; all history remains paginated; complete GET bytes unchanged; different
delivery full hydration cannot produce a current approval or POST; full history
labels the independent result explicitly. Preserve ETag, digest, Team/Project,
selection, complete active and fresh write checks.

Review correction: a successful UPDATE_REQUIREMENT legitimately retires the exact
editable draft and returns its replacement. Preserve this product navigation with
a separate exact full-Operation + current-snapshot identity/checkpoint contract;
the replacement cannot provide the old draft's stage, approval or baseline.
Modern summary polling must follow this edit after Team has removed the old ID,
and must not override user Project, page or selection changes during the read.
