# Design

The lookup owns a private bounded prefix with typed ProductSpec ID → request/repository/
spec digest/duplicate marker associations and raw SHA/path/directory/inventory fingerprints.
The first actual approval lazily reads every ProductSpec version. Fixed envelope, Pydantic,
inner integrity and lineage validation consume the same trusted full raw bytes recorded by
the fingerprint. Subsequent approvals validate exact associations without decoding specs
again. Do not retain spec bodies, verdicts, request heads or authority.

Final observation rechecks all captured directories and inventories, reads/hashes every
complete observed spec and approval again through trusted no-symlink directory descriptors,
and repeats directory/inventory checks. This is read integrity, not a transactional approval:
Designer and every downstream application fence remain independently fresh.

An internal capacity exception clears the prefix and delegates to the unchanged original
per-approval full lookup. A real corruption/path change never becomes an overflow fallback.
All call exit paths clear private associations and fingerprints. No cache spans calls or
model execution, and no arbitrary decoder can inject unvalidated associations.

Traversal carries a typed lightweight version predecessor and releases each complete record.
New raw wrappers clear text in finally. Overflow falls back only after leaving the exception
handler, so a traceback cannot hold full partial-index bodies during the original expensive
scan. These lifetimes are asserted with actual weak references, including externally held
corruption errors; original fixed-decoder error semantics are preserved.
