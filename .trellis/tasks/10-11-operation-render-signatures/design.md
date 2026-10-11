# Contract

Render invalidation may use `(operation_id, operation_sha256)` for a complete current
operation received from the existing validated Console API. It is not a replacement
for the operation result, approval signature, scope, control freshness or authorization.
The helper must require an appropriate operation identity and a complete 64-hex digest;
otherwise it returns the original full source facts. It must not memoize across polls
or expose payloads in DOM attributes.

Apply the helper to page/detail/operation history source signatures, not to functional
state such as `operations`, `latestApproval`, action payloads or copied reports.
All history rows remain present; there is no eight-entry or payload truncation.

## Validation matrix
| Input | Expected |
| --- | --- |
| Valid unchanged operation identity/digest with large result | Stable small render source |
| Same identity and changed digest | Row and dependent current controls update |
| Missing/invalid digest or identity | Full-fact changes remain observable |
| Changed scope/checkpoint/readiness | Existing exact approval gates revoke stale callback |
| Complete heavy history | Original body remains available and expanded DOM survives |

Browser measurements must distinguish CPU/serialization allocations from backend
read duration and network bytes. No claim of reduced API bytes or fixed Team busy
admission is permitted from this frontend-only change.
