# Inspection-only Console

## Scope and signatures
`production_console_app(environment)` resolves `ASE_CONSOLE_MODE=normal|inspection`
and `fault_retirement.inspection_required(environment) -> bool` before any writer composition.
`create_console_app(..., inspection: bool = False)` binds immutable process mode.
`FileConsoleOperationStore(..., read_only: bool = False)` forbids all writes in read-only mode.

## Contracts
A valid durable console-inspection marker forces inspection even if environment says normal until
separate confirmed maintenance completion. The original marker/archive stay intact; the first normal
Host requires a fresh maintenance admission before writer composition. See [maintenance-completion](maintenance-completion.md).
Malformed mode or marker refuses startup. Inspection constructs only existing Team discovery,
ProductionTeamReader and read-only Operation/preparation stores. No TeamHost, ProjectConsole,
Manager adapter, knowledge/index/reconciliation/dispatch worker or database initialization.
Operation reads use O_RDONLY and LOCK_SH on existing console.lock. Missing root reads empty;
existing root without its lock refuses. No lock is created by reading.
HTTP methods other than GET/HEAD/OPTIONS return fixed Chinese SERVICE_MAINTENANCE. Administration
GET is withheld because legacy knowledge/status constructors may create stores. Manifest advertises
mode=inspection, delivery_ready=false and no supported actions. UI prominently states that saved
records are readable and demand delivery remains paused, with no setup/reconfigure instruction.
Only this new read service's shutdown may become READY; predecessor REFUSED/UNKNOWN is unchanged.

## Validation matrix
Explicit inspection / valid marker -> read-only; invalid mode / damaged marker -> startup refused;
normal/no marker -> existing normal flow. Existing histories -> complete verified reads;
corruption/missing required lock -> fixed unavailable error, no partial result. Every mutation ->
503 maintenance even for unknown URL or malformed body. Shutdown -> no historical writes.

## Test points and examples
Good: summary/detail, history and preparation read existing facts without changing file bytes.
Base: missing Operation root stays missing and reports empty history.
Bad: starting ProjectConsole merely with live_model_execution=false, which still reconciles and claims.
Tests assert production writer constructors are never reached, durable inventory is byte-identical,
all methods rejected, mode boundary and maintenance banner/action blocking.

## Existing data and rollback
No migration or historical changes. This is an intentional temporary reading mode; it does not
approve K1 or establish that it can run. Keep marker across replacement/rollback until separately
authorized maintenance completion; reverting display code is not permission to start delivery.

## Maintenance boundary
The marker is scoped to the configured `ASE_SERVICE_STATE_DIR` and its maintained Console instance.
Normal/start/restart/apply and direct host composition consume that same durable marker; changing
ASE_CONSOLE_MODE to normal cannot unlock delivery. A trusted operator deliberately provisioning
another state/config root is a different Host, outside this instance-local maintenance boundary.
Environment subsets from embedded Python callers still resolve missing HOME to Path.home(), so an
omitted HOME never silently skips inspection of the default lifecycle directory.

Wire fields on `GET /api/v1/console` are additive to schema_version=v0.2: mode is normal|inspection,
maintenance_summary is the fixed Chinese message or null, delivery_ready is false during inspection,
supported_actions is empty. No domain artifact Schema or persisted record changes.

## Completion guide wire and UI
GET /api/v1/console may include maintenance_completion_guide during inspection:
`{schema_version: "v1", prepare_command: string, complete_command: string}`. The trusted Host
constructs quoted local shell instructions from its config/state/script paths; no credentials,
queue facts or authority is returned. The frontend renders textContent and a native details entry
“完成维护并恢复普通模式”. Polling preserves the same expanded guide/selection; a lost connection
withdraws current instructions. Opening the guide sends no HTTP write. Local two-step script entry
is deliberately separate from readonly HTTP and Requirement approval. Tests cover real browser
selection/DOM retention and inspection POST rejection with the guide present.
