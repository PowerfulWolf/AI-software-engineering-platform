# Exact observation and quarantine contract

`capture_mutation_inventory(root, *, known_oversized_file: MutationFile | None = None)` adds a
trusted observation-only capability for one complete previously hashed regular file. The
default stays 16,000,000 bytes per file, 256,000,000 bytes total and 20,000 files. A supplied
fingerprint must be canonical, regular, above the default and within the unchanged total
bound. Both no-follow stable passes must observe exactly that path, SHA, mode and size.
Other files retain the default bound. This does not authorize writing, hiding, ignoring or
admitting that file as code; all runtime callers omit the capability. No global constant changes.

The one-use external engineering script seals a complete plan before mutation. Under original
Task process lock and MySQL idle fence it verifies exact Task/work/claim/start/stop/outcome,
full code capture/HEAD/index and all inventory bytes twice. Prepare writes only task-local
review files. Apply requires exact plan digest and delegated engineering reference, records
SUPPLY_EVIDENCE, then renames `.mypy_cache` to a private audit directory without overwriting.
All original bytes remain. It verifies the archive's complete inventory and a default-bound
workspace inventory, unchanged code, Task, queue, stop and outcome, then seals completion.
Any failure preserves available files and records; it grants no recovery or execution authority.

Good: the exact 22,716,416-byte run7 cache is fully hashed and preserved externally. Base:
normal inventories retain byte limits and existing canonical digest. Bad: arbitrary ignored
files, changed cache, another oversized file, symlink, FIFO, path/size/hash drift or a missing
expected file fails before mutation. Unit tests cover these boundaries; actual prepare/apply
evidence validates the full stock state. New model runs use separate cache isolation.
