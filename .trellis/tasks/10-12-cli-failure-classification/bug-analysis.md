# Bug analysis: native stderr background authentication pollution

## 1. Root cause category

**B — boundary provenance, D — missing mixed-transcript cases, E — implicit assumption.** Native
stderr is not a provider-only error stream. The old first-substring slicing then whole-tail marker
search promoted timestamp/MCP diagnostics to main execution error evidence. Seven minimal
synthetic mixed-stream cases reproduced false auth before the fix. The failed production run's
unavailable original stderr cannot establish whether this defect caused that particular failure.

## 2. Why a surface fix is insufficient

Deleting one known MCP line or using the first/last text line would still miss timestamp variants,
component messages after a true transport error and genuine multiline provider auth. Changing
AUTHENTICATION_ERROR to transient would weaken credential failures and rewrite budget meaning.
The fix therefore selects the actual main diagnostic block first, then retains existing categories
and application mutation/stop/fallback policy.

Independent review found that indentation and a sticky `json_body` flag were still implicit
provenance: authentic JSON immediately after a summary/HTTP header was omitted, while a second
JSON object or unrelated indented message could be appended. Six red counterexamples led to a
complete bounded JSON parser and explicit continuation vocabulary. Review also showed tail clipping
could manufacture a root prefix. Actual native capture compounded this at its head/tail join;
four real subprocess red cases established the defect and the missing truncation fact. Finally,
four red incomplete/oversize diagnostic cases prevented losing true auth to diagnostic bounds and
then accidentally granting transient fallback. These were root-boundary fixes, not history relabeling.

## 3. Prevention mechanisms

| Priority | Mechanism | State |
| --- | --- | --- |
| P0 | Explicit unprefixed main block provenance, component/timestamp boundaries | Implemented |
| P0 | Genuine HTTP/auth/JSON/multiline preservation and single-message legacy compatibility | Verified |
| P0 | Complete JSON boundary, typed actual capture truncation and incomplete-diagnostic denial | Implemented and focused verified |
| P0 | Real Git + durable preserved-progress fallback, auth denial, changed-workspace rejection | Verified |
| P0 | Fixed categories/exit/original-stream digests, no raw diagnostics | Retained and verified |
| P1 | Existing nontransient stopped execution needs a separate exact human ordinary-work continuation | Root-owned follow-up, outside classification scope |

## 4. Systematic expansion

Structured `--json` CLI calls have a separate existing error-event provenance reader. This task
does not alter it or Responses/HTTP/model routing. Native stdout is never error evidence. Watchdog
limits remain local TIMEOUT; unknown process stop remains uncertain; failed mutation inspection
and new effects cannot be turned into a clean route by corrected diagnostic classification.

The complete actual stderr remains bounded and ephemeral. Stream digests correlate evidence but
cannot recover lost output. Use safe shape-only probes to diagnose mixed streams; never publish
real stderr, prompt or credentials, and never relabel historical facts from a later health result.

## 5. Knowledge capture / existing data

`.trellis/spec/core/production-team-host.md` now carries the selector signature, provenance contract,
validation matrix, Good/Base/Bad examples and incremental tests. There is no generated spec-template
tree. No Schema, Task/queue, SQL, verdict, approval or old Run content is changed. Root must finish
the independent review, controlled integration/deployment and exact authorized existing Task path.
