# Design and executable contract

## Interfaces
`StructuredExecutionObserver.admit(StructuredExecutionAdmission) -> None`,
`native_stopped(StructuredNativeStopReceipt) -> None`, and
`native_not_started(StructuredNativeNotStartedReceipt) -> None`, and
`http_completed(StructuredHttpRoundTripReceipt) -> None` persist facts only.
`bind_structured_execution_observer(observer)` scopes trusted composition;
`structured_call_identity(identity)` scopes each actual fallback route.
Neither changes StructuredModelClient.complete or provider/model input authority.

## Data
Each admission freezes observation ID, exact fallback invocation/route identity,
role/phase, provider/model configuration, canonical request digest, transport kind,
local timeout and timestamp, with SHA-256. Native stop receipt binds the complete
admission and the real runner's NativeProcessStop plus output byte digests. HTTP
receipt binds admission and known synchronous return/error facts; it cannot contain
NativeProcessStop or assert remote work terminated. No prompt, secret, environment,
stdout/stderr, response body or raw exception text is persisted in these records.
NOT_STARTED binds the exact admission to a typed known startup failure and time,
with no PID or process-stop record. Only CodexProcessNotStarted from the owned
runner before successful Popen may create it. Input/launch OSError classification
uses the actual runner startup boundary, not broad caller exception guessing.
Ownership registration is inside the main cleanup guard after successful Popen;
post-Popen failures stop/reap the real child and fail as execution uncertainty.

## Validation matrix
Good: admit -> owned stop -> structured output parsed. Base: no observer preserves
existing behavior. Bad: unknown process end, failed observer, absent route binding,
receipt/admission mismatch or digest tampering fails closed; no synthetic stop.
Native timeout/nonzero and HTTP response/error are recorded before translation.
Unclassified BaseException and interrupted Host have no invented completion.

## Boundaries
ContextVar is temporary binding, not execution permission. Existing ExecutionGuard
and runner/process lifecycle remain authoritative. Observer exceptions are wrapped
as StructuredObservationRejected, outside StructuredModelError/OSError fallback.
Fallback route identities are distinct, including skipped-route indexes. Production
knowledge composition must supply its own exact request/claim binding later.
