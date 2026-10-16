# Verification and existing K1 treatment — in progress

## Independent production facts

The preceding maintenance229eabd is deployed and origin/main matches. The original Host
stopped with exact READY; new instance console_instance_69a6aab47708df27e2aa5547fffb9311,
PID17458, is normal and delivery_ready=true. Independent deployment audit
/tmp/ase-k1-postdeploy-independent-20261016-065224.json SHA
e823727517cb279d410fe4e17c6f777c127829067c9b3c9ddb9cc85d9a9ccf54.

Public Continue operation_04b806b5df43944929dcea7567bca9c7 succeeded at07:00:16.897601Z.
Original lease_df833d81c8ef27886117029e became EXPIRED. Fresh guard lease
lease_7faff06db78c2b861a00277f became RELEASED at07:00:01.150653Z. The WorkItem is now
WAITING_DEPENDENCY/EXECUTION_UNCERTAIN. Original Task full payload/revision8/attempt6/source
is unchanged; main invocation starts/outcomes remain6/4 and Run6 still has no outcome. No
ACTIVE claim exists. Original195-file manifest remains unchanged.
Independent SQL and history reports:
- /tmp/ase-k1-wait-sql-independent-20261016-070422.json,
  SHA0e2d60c7629934ee78978a46eb132f4324914c9f4c3f37e2f8726d595180c48e.
- /tmp/ase-k1-wait-history-independent-20261016-070451.json,
  SHA8919e9eba9b1f01aae93f35368619887b44d53b5691c5a4028129acafeb18a06.

Public rescue proposal operation_f6d082a9289ebe26fb04d9ac47a2b09f failed COMMAND_REJECTED
at07:03:19.657124Z with the exact historical-admission scanner error. No plan was executed.

The incoming admission SHA06b49d093e5527e4d8a52c7cf188bca58de8a44c3e61b0dbcb21d1b3ae233b84
and predecessor receipt SHAc91c406531e953a88b9e5e5b7179da422d4a96929deab66eca3ad5be399d8482
match original Run6 request/WorkItem/old lease/scope exactly. The actual ordered times are
invocation-start05:43:45.283082Z, admission05:44:18.528438Z,
capture-start05:44:31.965994Z, fresh claim06:53:15.058358Z.
Audit /tmp/ase-k1-incoming-native-boundary-independent-20261016-070724.json SHA
8606f5114976118acb6c3262bf3c5f7c04a47233c7ccb759cc033d13af9d7c76 records the typed chain.

The six Run5/Run6 native files are outside the old195-file manifest. Their existence before the
fresh claim has separate independent audit support: the05:47:35.860921Z admission audit SHA
2960b6e0c5556051c66c65fde8165a7368d312a2e52f571e6b03d146e3999916 and06:05:57.913895Z
Run6 failure audit SHA4037b910cdff394806b07691c81d698f2e423b2f52266fdfdc7424bf42bca6f7
both record these exact admission/receipt identities. Do not use the old195 manifest alone
to assert preservation or chronology of those six files.

## Tests and independent review

The focused incoming-admission regression reproduces the exact production scanner rejection:
1 failed in0.63s at capacity_input_reader.py:619, before production code changes. Initial fixture
claim chronology/directory preconditions were corrected so this RED is the intended failure.
The public fixture now uses a real predecessor local-limit process to create a native receipt,
normal continuation to create the incoming admission, then a second genuinely stopped unknown
execution before fresh guarded recovery. The fixed reviewer confirms it does not fabricate
the prior stop/claim/admission. The new public [incoming-admission] parameter also reproduces
the exact production rejection:1 failed in14.61s, at the public proposal assertion with the
same native-recovery error. The minimal source fix then passes the exact unit case and the
real public repeated-history case (1 passed in35.94s). The latter reaches exact PAUSE/RESUME
and independent QA/Review DONE while retaining old UNKNOWN and immutable record bytes.
The fixed read-only reviewer independently runs the repeated public history case:1 passed
in35.02s. The actual predecessor stop/receipt, incoming admission, unknown stop, fresh guard,
exact PAUSE/RESUME and independent QA/Review DONE all pass with old bytes retained and no
duplicate main call. Independent generic no-start refusals (alternate-run native receipt and
admission, aliases, current output/capture and unfinished knowledge) pass14 cases in0.73s.
The incoming-specific positive and26 refusal cases pass independently:27 passed in1.56s.
After the two test-only annotations are corrected, the fixed reviewer independently reruns
strict Mypy for source and both test files:all pass. Three-file Ruff/format and diff check pass.
Final independent read-only review reports no blocker. The focused full unit file passes40
cases in1.52s in the author's run. The final affected matrix passes70 cases in131.19s:

```text
PYTHONPATH=src .venv/bin/python -m pytest -q --tb=short tests/manager/test_replay_guarded_claim_observation.py tests/manager/test_stopped_execution_delivery.py tests/manager/test_verifier_capacity_input.py
```

No isolated test remains running. Production deployment and exact original-K1 recovery are
the remaining steps; these offline results are not production K1 acceptance.

Preserve honest failed proposal and unknown execution facts. Offline regression completion
does not establish the production candidate or future QA/Review verdicts.

## 存量数据处置

No production SQL, original outcome/cause/verdict, historical receipt/admission, Task reset or
business checkout edit. Original K1 remains safe in engineering wait without an active lease.
After reviewed controlled deployment, reread public facts, prepare a new proposal with a new
idempotency key, review its exact same-base/full-draft/progress proof, record delegated PAUSE
then a separate exact RESUME. Retain failed proposal and all old UNKNOWN/history records.

## Rollback

Controlled stop before code rollback. Retain all immutable facts and compatible readers; do
not delete admissions to satisfy the older scanner. No native Coder or future verdict is
authorized merely by passing this scanner.
