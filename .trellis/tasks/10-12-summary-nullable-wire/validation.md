# Validation and existing data

Root observed real HTTP 200 summary but the browser rejected canonical omitted nullable fields.
RED: actual Python TeamSummary/TaskDetail.to_wire fixtures (not handwritten nulls) reproduced
TeamReadFailure at shipped verifiedTeamSummary line 114. GREEN after only six symmetric `?? null`
comparisons: 1 cross-language pytest passed, covering five variants and exact mismatch rejection.
Existing team-summary-reading Node suite: 21 passed. Ruff/diff check passed.
Independent review by maintenance_successor_boundary: no remaining blocker; independently ran
cross-language test successfully. Added legacy remediation coverage and re-ran successfully.
Offline actual saved production summary /tmp/team-summary.json: all 2 requests and 25 tasks accepted.
The production payload is not committed. No live HTTP, restart, model or requirement mutation here.

Existing data: no migration required; source records are valid. Reload the corrected browser asset
from a controlled successor to read them. Exact source/body/owner/checkpoint checks remain in place.
Rollback: revert this six-comparison change and tests; historical facts are untouched but UI failure
would return. Full suite not run, per user's incremental-test constraint.
