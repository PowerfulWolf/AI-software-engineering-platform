# Implementation record

- Added `manager/local_path_observation.py` for strict private request/result models, complete
  lsof field parsing and owned-child launch/finalization with the original absolute deadline.
- Added fixed `manager/local_path_worker.py` to decode stdin, interpret captured paths and emit
  one complete typed result. Isolated startup directly uses trusted interpreter dependencies;
  it performs no process queries, command launch, discovered-PID signals or historical decisions.
- Routed macOS `_inspect_mac_paths` through the new adapter. Existing OS query limits,
  scanner identity, durable survey shape/digest and process classification remain unchanged.
- Made knowledge isolation reject the first non-idle survey immediately; the successful
  path still observes both roots twice and validates the same proof boundary.
- Added protocol, malformed/limit/deadline, alias/deleted-path, owned lifecycle, production
  seam, startup-hook and four-survey/fail-fast tests. No new PID exemption was introduced.

The implementation and independent static review are maintenance work. They neither create a
K1 candidate nor replace independent delivery QA/Review. No production SQL, old stop/outcome,
Task/attempt, approval or K1 draft was edited to implement this fix.
