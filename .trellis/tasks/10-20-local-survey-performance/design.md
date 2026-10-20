# Isolate complete lsof path interpretation from Host Python threads

The observer retains the fixed OS ps/lsof queries, current inventory/identity checks and one
absolute five-second deadline. `_inspect_mac_paths` delegates the already captured bytes,
canonical root, existing ignored/cwd-blocker sets and that exact deadline to the private adapter.
The worker performs the same complete field parsing and filesystem alias resolution in a separate
interpreter. It collects no new process facts and makes no recovery or historical-stop decision.

The adapter launches only `sys.executable -I -S -B <fixed local_path_worker.py>`, cwd `/`, with
fixed PATH/LANG/LC_ALL. The worker directly adds its trusted checkout and selected interpreter's
dependency directory; it does not process Python site startup hooks or accept import roots from
request data. No shell or discovered process identity is an executable parameter.

The complete canonical request contains every parsing input and its SHA-256. Strict typed decode
requires all fields, bounds, protocol and digest. The child returns only complete sorted coverage,
the existing worktree-active blocker and the exact request digest. Parent acceptance requires
zero exit, empty stderr, bounded valid output, matching SHA and the original deadline still live.
All streams use private temporary files and the exact pre-exec ownership observation is always
finalized. An uncertain stop remains an incomplete observation.

Knowledge isolation checks each survey immediately. Failure stops further work; success preserves
the original repository/repository/worktree/worktree ordering and same boundary proof. Neither
optimization adds an exception for a PID, changes persisted survey semantics or supplies authority.

Executable signatures, limits, negative cases and rollback are in
[the worker specification](../../spec/core/local-path-survey-worker.md).
The private stdin/stdout protocol introduces no public or persisted Schema change.
