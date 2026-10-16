# Implementation

The Request detail reader selects only native work that can contribute to the selected
Request after validating every joint/native ownership edge. Both independent observations
use this selection. Current SQL Task, engineering and verification reads remain fresh in
both; full, summary and Task detail keep their previous behavior.

Verification reservation envelopes, release/order/source/repository checks run before any
historical body is omitted. There is no authority cache, read-gate change, persistent model
change or data migration. Existing raw records and K1 execution workspaces remain untouched.
