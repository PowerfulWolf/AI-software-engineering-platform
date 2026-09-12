# Web Project Delivery Console design

## Scope

Deliver the first browser-only vertical slice for requirement projects without weakening Team View's
read-only contract or duplicating Project Manager workflow rules.

## Modules and seams

### `ProjectConsole`

The deep application module. Its interface accepts four user intents and exposes operation status:

```python
submit(CreateRequirementProjectIntent | ProductReplyIntent |
       ProductApprovalIntent | ContinueDeliveryIntent) -> ConsoleOperation
get(operation_id: str) -> ConsoleOperation
list_operations() -> tuple[ConsoleOperation, ...]
run_once() -> ConsoleOperation | None
```

It validates opaque checkpoint bindings, persists the accepted operation before execution, and
delegates to `OrganizationTeamHost`. It never implements Product, Planner, QA, Review or recovery
state transitions itself.

### `OperationStore`

Two real adapters justify this seam:

- immutable/file-backed company-sidecar adapter for production;
- in-memory adapter for focused tests.

The store owns idempotency keys and legal `QUEUED → RUNNING → SUCCEEDED | FAILED | INTERRUPTED`
transitions. A stale browser submission returns the existing operation or a safe conflict.

### `ConsoleDispatcher`

One bounded worker consumes persisted operations. HTTP handlers never run providers. A process
restart converts orphaned `RUNNING` operations to `INTERRUPTED`; the UI offers the existing unified
continue action instead of blindly replaying an at-most-once model invocation.

### Web transport

A typed loopback ASGI adapter maps JSON to intents and maps safe domain failures to stable HTTP
errors. It serves the console assets and composes the existing `ProductionTeamReader` query output.
Host/origin checks, request-size limits and JSON content-type checks are mandatory.

## Operation flow

```text
Browser action
  → validate + bind displayed checkpoint
  → persist QUEUED operation (idempotency key)
  → HTTP 202
  → dispatcher claims RUNNING
  → existing Project Manager interface
  → persist SUCCEEDED/FAILED result
  → browser polls operation + team snapshot
```

## UI flow

1. “新建需求项目”: name plus repeatable absolute directory inputs.
2. Prepared request workspace: discovered repository/modules and Product chat.
3. ProductSpec review: explicit approve button bound to the displayed checkpoint.
4. Delivery workspace: one valid continue/approve-plan action at a time, current Agent role and
   affected paths, QA/Reviewer results.
5. DONE: repository-level candidate commit/branch, evidence and copyable delivery summary.

## Failure contracts

- Duplicate idempotency key with identical intent returns the same operation; changed intent fails.
- Only one active operation per delivery is admitted.
- Invalid/stale checkpoint fails before model invocation.
- Provider/rate-limit/failure text is reduced to the existing safe summary.
- Browser disconnect changes nothing because operation acceptance is persisted first.
- Host restart never silently replays a RUNNING model call; it records `INTERRUPTED` and offers
  Project Manager `continue` from durable delivery facts.
- The console cannot merge, push, deploy, edit Agent identities or execute arbitrary commands.

## Increment plan

1. Operation domain/store/dispatcher and focused tests.
2. Project Manager intent adapter and real single/multi-directory tests with scripted providers.
3. Loopback Web transport and security/contract tests.
4. Browser UX and frontend tests.
5. README/spec sync and operator verification.

Automatic macOS/Linux login-service installation remains a later increment. It first needs a secure
Keychain/Secret Service adapter; plaintext MySQL DSN or provider credentials in plist/unit files are
not an acceptable shortcut.
