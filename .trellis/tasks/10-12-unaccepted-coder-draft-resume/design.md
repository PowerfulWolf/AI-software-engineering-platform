# Design

Use the existing complete stopped-output proof and execution-baseline flow. Keep its wire kind,
fields and canonical digest behavior; add only a typed, nonserialized derived reason. INVALID_OUTPUT
and WORK_INTERRUPTED remain different immutable failures, paired with different reservation causes.
No repaired result or independent allow flag is accepted.

The same stopped/claim/scope/source/permissions/no-adoption gates apply. A new INVALID_OUTPUT input
requires human engineering PAUSE for either same-base rescue or SOURCE_REBIND. SOURCE adds the
existing optional proof digest and validates the rebased actual after workspace; historical SOURCE
WORK_INTERRUPTED bindings without the digest retain policy/RESUME compatibility. The database
consumes one normal work reservation, creates one paused successor and releases only the latest
exact successor under a separate decision. Normal claimed Coder, candidate, QA and Review remain.

Validation is at real collector, Git service, store and production pre-SQL publication seams;
published and freshly regenerated Schema guards agree. The isolated public Host fixture invokes
the real native adapter over a test-owned completed process whose {} report is rejected, and
then exercises same-source/updated-source PAUSE/RESUME and independent delivery. Root owns exclusive
MySQL execution and production maintenance; this worktree runs only offline incremental checks.

The frontend and shipped JS checks are owned by root, as are integration, independent review,
public production existing-data handling and deployment. No production stores/services are accessed
from this worktree.
