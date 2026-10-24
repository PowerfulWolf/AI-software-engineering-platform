# Stream investigation and original K1 continuation

## Scope and actual result

As of 2026-10-24T14:57Z, the original K1 has an accepted Coder progress artifact.
No candidate, QA PASS, Review APPROVE or handoff is claimed. These observations do
not establish the historical provider/proxy root cause and do not change K1 source,
permissions or frozen budgets. No automation was created.

The original fourth main invocation reached its real 1800-second owned window;
it retained no final artifact and no prospective activity counters. Preserve its
TIMEOUT/WORK_INTERRUPTED, capture, UNKNOWN history and ordinary-work charge. Never
backfill activity from a later success or retained transcript hashes.

Fifth invocation `run_99d4815ea256466abcf8ccbaf6a07663` completed at
2026-10-24T14:48:50.561880Z with rc=0 and a real completed owned stop. Its typed
invocation outcome SHA is
`148e19ed903585fec1530759ce61054f3c18a70872528d4fab0d1b68e4b37c10`;
capture-stop SHA is
`5e7ac319b51670e934e86e095067645657ef5f32e42da9cdd022bc72d9b44c78`.
Independent read-only store reopens validated accepted progress
`art_coder_1c2bd6a0955665f3e83d7fd8c9e2e13a`, SHA
`106997e19a50910fe65c0df559a829273595af41a5d1e3d29d23ad3599a22867`:
completed steps 01/02, remaining 03–08, all 29 authorized dirty paths retained.
This checkpoint's reported NOT_RUN/errors are not independent acceptance.

Sixth invocation `run_bc7b93179eeb447e9312d37a6f0146e0` started at
2026-10-24T14:55:31.558192Z, consuming the original Plan and accepted progress.
It selected steps 03/04 and deferred 05–08. Ordinary work advanced 4→5 of10;
execution identity advanced 5→6 of40. No transient refund or budget increase occurred.
Source remains `5547815464a04991f50a2e0532d6f2f13d8daa69`. The 2992-file
continuation inventory SHA is
`6088857171809630485a3f606eedcece8ead22c731f9fecb460bb674088fb192`.
Do not interrupt an active role merely to deploy optional diagnostic statistics.

## Actual real-CLI synthetic stream matrix

This independent experiment uses the frozen installed CLI, an empty synthetic HOME,
literal fake credential, exact loopback listener, no provider, no tools and a bounded
owned runner. It is not an execution of the production proxy or its effective config.

CLI version 0.162.1, binary SHA
`74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0`.
Harness `/tmp/ase-codex-sse-time-matrix-v5-20261024.py`, SHA
`b3c095505f5f13b639c461055779d69b698541cea99ca9e8164e4d442db49502`.
Sealed results `/tmp/ase-codex-sse-time-matrix-v5-run-20261024/results.json`, SHA
`ea748a4b413849acf4d07f9b0c35f31367f071cf91eb38ec78b521673537ef52`.

| Fixed synthetic case | Requests / result | Observed elapsed |
| --- | --- | --- |
| Immediate complete | 1, rc0, exact fixture final | 0.283469s |
| Headers delayed75s, then complete | 1, rc0, exact fixture final | 75.266020s |
| Comment heartbeat10s, complete75s | 1, rc0, exact fixture final | 75.232376s |
| Partial line then complete75s | 1, rc0, exact fixture final | 75.272001s |
| Heartbeats, clean EOF75s without response.completed | 2, local110s watchdog, rc-15, no final | 110.300790s |

Every case confirmed actual owned stop, handler stop and server thread cleanup.
The EOF control retried after the first incomplete response and was locally stopped
during its second request. It did not independently produce a final native EOF error.
The complete matrix took336.533303s within480s. These results disprove a blanket60s
limit only in this exact direct-CLI wrapper; they do not identify production failure.

### Sandbox setup correction and real negative checks

Earlier v3/v4 attempts were setup failures, not stream evidence. Numeric127.0.0.1
was invalid in this SBPL syntax; the admitted profile used exact localhost:PORT.
Native libc realpath additionally required only metadata access to the exact two
synthetic ancestors `/private/tmp` and its fresh run directory. Both exceptions
were needed; either alone and the original profile failed. No ancestor enumeration,
file data access, extra network or write was granted.

Actual differential: `/tmp/ase-sse-realpath-experiment-20261024.json`.
Actual full negative report: `/tmp/ase-sse-sandbox-metadata-negative-20261024.json`;
negative harness SHA
`4210cc0098b6378b890614eba0ae55828e09333c3f3087f144be463ac10a58ea`.
The allowed port succeeded; a second port was refused without connection. External
synthetic reads, outside writes, ancestor enumeration and unrelated sibling metadata
were refused. Protected synthetic bytes remained unchanged. All attempts cleaned up.
These exact test-only allowances did not modify production role permissions.

## Verified public proxy source, without executing it

Anonymous public-source inspection matched Homebrew v7.3.5 archive SHA
`2a9e6674a1b8d5565a23c43fd2155bd3584255e20f8e112dbc89183d05bfa0ba`
and immutable commit `b681a1e0f7b89d26814f788b60bf84feaf72e912`.
Provenance manifest `/tmp/ase-cliproxyapi-7.3.5-public/source-verification-20261024.json`,
SHA `6546e787f83418dd0127b8ca8a6710ca799a1e4668456e8d382a18f4fb0bce91`.
Detailed report `/tmp/ase-cliproxyapi-7.3.5-public/source-streaming-findings-20261024.md`,
SHA `86673f6cefd171d1da5f890f0068a4ef2ce94dde4a50d1a13cd184fb7fcf95c3`.

- `internal/runtime/executor/codex_executor_terminal.go:508` uses a closed allow-list
  of bootstrap events. Reasoning and argument deltas/done, output-item done, nonempty
  tool input and server-side tool events release buffering. No inspected branch waits
  for a client tool result before releasing a ready call.
- `codex_executor_stream.go:115` waits for upstream response headers before starting
  the bootstrap clock at143. Its timeout is checked after scanner.Scan yields a line;
  it is not an independent timer for silent or unterminated-line traffic.
- `sdk/api/handlers/openai/openai_responses_handlers.go:678` adds another gate: headers
  are submitted after the first complete data frame. Comment heartbeats alone do not
  ensure that gate opens.

No public-source code was executed. No installed proxy process, production credential,
auth file or raw provider log was read or changed. The report contains a falsifiable
fake-upstream design, explicitly NOT RUN; it is not evidence of production recovery.

## Maintenance validation and stock data

Root independently ran actual no-provider runner/store/deletion tests:27 passed
in7.60s. Shared parser/CLI classification/owned timeout/continuation/purge regression:
185 passed,1 MySQL-marked test deselected in99.00s. Import paths were checked against
the isolated source mirror. Worker verification records additional pure/contract
checks; counts from overlapping suites must not be added as unique coverage.

No SQL or historical sidecar mutation is needed for the new optional diagnostics.
Existing K1 recovery already used the reviewed public PAUSE/RESUME path recorded in
the prior stable-boot task. Original success, failures, approvals, captures and budgets
remain authoritative; optional activity observations never supply continuation or
acceptance authority. Keep future read/deletion compatibility after any new records
are published. The live main checkout remains unchanged while the role is active.
