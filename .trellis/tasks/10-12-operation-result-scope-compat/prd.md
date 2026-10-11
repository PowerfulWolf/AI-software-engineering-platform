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
