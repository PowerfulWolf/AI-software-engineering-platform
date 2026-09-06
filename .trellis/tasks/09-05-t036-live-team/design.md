# Read-side contract

`ProductionTeamReader(config, environment).snapshot() -> TeamSnapshot` reads only configured company
and organization. Open journal/checkpoint stores in explicit read-only mode; validate manifest,
hash chain and project binding. Match joint children by deterministic native delivery identity, not
by title. Read Task/events/dispatch in a MySQL consistent READ ONLY transaction after filesystem
checkpoint capture. Reuse typed decoders and projection validation. Missing materialization is
pending, corruption is an error, never an empty successful snapshot.

`create_team_server(reader, port)`: loopback only. GET `/`, `/app.js`, `/style.css`, `/api/v1/team`.
All other paths 404, write methods 405, foreign Host/Origin 403, read failures 503 with safe message.
No arbitrary filenames, shell, model calls, state transitions or automatic browser launch.

Wire: snapshot(schema_version, as_of, company_id, company_name, agents, requests, tasks).
Tasks carry parent request, code root/selected paths, stage/status, assignments, events,
artifact refs, candidate, blocker, last activity and execution-liveness UNKNOWN.
UI derives display counts from these typed facts; no workload percentage or process-online inference.

Good: in-flight native child absent in parent's children is still visible using deterministic ID.
Base: no requests/agents yields honest empty state. Bad: digest or company/Task/dispatch binding
mismatch yields unavailable snapshot, preserving browser's explicitly stale prior display.
