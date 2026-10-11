# Implementation record

## Root cause and change

Native recovery intentionally performs multiple current source/facts observations. Within
each observation, SQL baseline epochs, v2 Context resolution and snapshot verification
repeatedly call the same file-backed Plan/Start consumers. The repeated full typed model and
nested integrity decoding is distinct from the required fresh original-byte reads and live
facts checks. Public exact approval adds authorization and offline Task derivation observations.

Added a synchronous, aggregate-bounded immutable decode scope. Baseline and Context reading
ports still reopen all original bytes; only exact full-byte matches share fixed complete raw
decoding and integrity/key validation. Authority, binding, native epoch and live SQL/Git/process
facts stay outside reuse. Ordinary generic get/list/writes keep their existing paths; writer
baseline ports explicitly disable reuse. Private deep copies isolate historical nested maps.

Public recovery preparation/current/approval and source/facts readers own short scopes. The
controller closes its shared preparation/approval scope before execution admission; the native
execution gate owns another short scope and closes before the delivery backend/model call.
Thread and asyncio Task ownership prevents inherited ContextVars from reusing/closing a parent.

## Independent review changes

Root and native recovery reviewers inspected the work. Generic caller validators and decoders
were removed, so valid in-memory models cannot register corrupted raw envelope bytes. Context
UTF-8 behavior was preserved explicitly. An unsupported new 8 MB total Context refusal was
removed; overflow fully decodes without retention. Added strong corruption, current-facts,
authority, lifetime and real public authorization/builder/sealing regressions. The test's
fixed-date Human adapter was replaced with the real exact-decision adapter, retaining the
production rule that a decision cannot predate its command.

## Boundaries

All implementation and verification occurred in the isolated maintenance worktree based on
1769977. No production SQL, Host, service, registered source checkout, original K1 worktree,
approval, counter, stop proof or verdict was changed. No requirement was duplicated or delivered
by this task. Schema and persisted record bytes remain unchanged. Detailed contract, existing
data procedure and rollback are in the new core specification and verification document.
