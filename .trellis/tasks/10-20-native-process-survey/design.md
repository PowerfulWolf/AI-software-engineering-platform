# Native identity isolation design

## Decision and evidence

The original observer performs repeated short proc_pidinfo calls on the Host interpreter.
The production five-second failure moved to the process-inventory phase after path parsing was
isolated. A real full-survey harness with three parent CPU threads reproduced two current
failures (5.150/5.160s). A probe reusing one 136-byte native response only within each inventory
halved native calls but still failed (5.081/5.167s). Its temporary result cache was cleared after
each inventory and never entered production. All CPU probe threads joined and exited.
This rejects the claim that merely reducing duplicate FFI reads solves this workload.

## Architecture and invariants

Keep ps/lsof queries, complete inventory interpretation, classification, desktop attribution,
path coverage and before/after/final ordering in the parent observer. At each native identity
sampling point call a new dedicated fixed owned interpreter. It reads only the supplied bounded
PID set through the fixed macOS libproc ABI. One record contains the matching PID and observed
microsecond birth plus requested kernel executable name, or a typed current disappearance.
The final observation remains fresh after path coverage; no earlier birth is reused as final.

Require exact request/result SHA and PID-set correspondence, correct current effective UID,
complete 136-byte native response, valid birth and strict kernel-name parsing. Disappearance,
UID mismatch, short native reads, invalid name, extra/missing/duplicate results or deadline/stop
uncertainty retain existing incomplete/refusal semantics. No PID discovered in a scan is signaled.
No discovered argv, environment, raw native data or PID set is persisted as task evidence.

The child uses fixed Python -I -S -B, adjacent owned source, private files, cwd / and three fixed
nonsecret environment values. It cannot load .pth/sitecustomize or request-controlled imports.
Every phase uses the original monotonic deadline, including serialization/spawn/result acceptance
and owned cleanup. No new model/tool authority, public schema, SQL migration or timeout extension.

The existing path-parser worker continues to interpret only already captured lsof bytes. Linux
continues to use original /proc facts. Fake OS fixtures override the explicit batch seam so tests
never probe accidentally matching real PIDs. Independent review must inspect both production
integration and refusal cases before deployment.

## Measured remaining captured-argument path work

After native batching, the real four-survey acceptance still failed at the original deadline.
All CPU probes exited. A three-thread full-survey cProfile narrowed the remaining cost:
`_processes` 1.351s (native batch 0.875s), `_desktop_sandbox_chains` 3.749s,
`_arguments_reference_worktree` twice 3.682s, 32 `_covers` / 33 Path.resolve calls 3.741s,
242 lstat calls 3.294s. The existing `process_inventory_before` phase included desktop attribution;
add distinct safe before/after desktop-attribution phase names for future diagnosis.

Add a separate captured-sandbox-argument batch family to the existing fixed path worker. Its
result must correspond exactly to each bounded input argument tuple and original root/deadline.
Preserve every relative/missing/unknown directory refusal and absolute alias resolution, including
all executable and option-value paths. Parent retains native chain/argv attribution and complete
file coverage. Prefer one batch per inventory rather than one spawn per candidate chain. Existing
lsof request/result bytes and behavior stay strict and unchanged. This is interpretation of already
captured process arguments, not a new OS query or a native worker responsibility.

## Final execution boundary: one owned interpreter for the complete survey

The second real red result rejects repeated parent-interpreter lifecycle round trips as a
sufficient performance repair. Introduce a private IsolatedLegacyLocalExecutionObserver as
the production composition default; preserve TrustedLegacyLocalExecutionObserver as the
testable complete engine. One fixed owned child performs the complete unchanged inventory,
attribution, path coverage, changed-PID supplemental coverage and fresh final identity order.
Within that interpreter the existing native/path/argument pure inspectors run directly.

All fixed ps/lsof tools inherit the already captured outer SID. They must not create another
SID, run arbitrary argv or environment, or outlive unverified outer cleanup. Query timeout
targets only the actual Popen. Parent finalization must still prove the whole outer SID empty;
local tool exit alone does not establish that proof. One original absolute five-second budget
covers all parent startup/serialization, child work, result validation and parent cleanup.

The original Host self open-file exclusion is bound to the actual parent kernel identity;
the child verifies exact getppid, current effective UID, boot and microsecond birth before,
after and at final acceptance. Only these actual two observer processes receive the original
open-file self treatment. Their argv classification is still checked, and no ancestor, child
tree or discovered PID is exempted. Fake engines remain explicit injected dependencies.
