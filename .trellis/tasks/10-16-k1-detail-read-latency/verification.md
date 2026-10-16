# Verification and deployment handoff

## Results

- Author: 14 new Request projection cases passed; related reader cases 47 passed with one
  MySQL case deselected. Ruff, format and strict Mypy passed for the two Python files.
- Independent reviewer `/root/run6_owned_uncertainty`: 40 reader cases, 63 live/Console
  cases and seven temporary HTTP cases passed (110 total). Six MySQL cases were excluded;
  this read projection does not change SQL. Negative probes for final-observation current
  engineering corruption, a corrupt foreign joint journal and a corrupt foreign native
  journal all refused. Both independently fresh current Task observations were confirmed.
- Root repeated `git diff --check`, Ruff check and Ruff format check successfully before
  staging this exact change. No production write or database reset belongs to this task.

Independent review report:
`/tmp/ase-k1-request-detail-perf-independent-review-20261016.json`, SHA-256
`f71df848b85fc985e1119ba3c350f387cd73fef7255451e29a3d15aea05c05af`.
The reviewed reader body SHA-256 is
`87c89dd02196943b37334a4fae7b4388419ebd58615291a0bde6aa210c75e9d2`.

## Real read-only measurements

The complete same K1 Request detail took 11.571s wall / 10.898s CPU before the change,
including only 0.37s database time. The author measured 7.394s and root independently
measured 6.992s wall / 6.807s CPU after it. Both snapshots remain; Task detail and
engineering-history projections dropped from 24 to two. This is a measured reduction,
not a claim that frontend refresh is now fast or that the global read gate was deadlocked.

Root report `/tmp/ase-k1-request-detail-read-profile-root-after-20261016.json`, SHA-256
`744a58a1f0b97b2e97edbd39ef94751e8e3f301e3d3ae1c6ecd2f2e1b1e4c6a2`.
Remaining hotspots are current engineering history (3.62s) and joint history (2.73s).

## Existing data and rollback

存量数据处置：no data migration, authority rewrite, Task recreation or production SQL repair.
Keep original K1, accepted progress, failure/UNKNOWN history and all retained draft bytes.
Deploy together with the reviewed workspace-admission repair at a controlled idle boundary.
Rollback restores the previous reader projection cost while retaining all durable facts.
Actual browser validation and deployed timing are recorded after that controlled deployment.
