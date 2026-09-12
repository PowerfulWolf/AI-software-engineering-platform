# Platform-root default delivery integration

## Goal

Integrate the independently delivered platform-root default onto the latest main while closing every
review finding before publication.

## Requirements

- On macOS and Linux, omitted `platform_root` resolves to the current user's `~/.ase`, independent of cwd.
- Explicit absolute and safe `~/...` values take precedence.
- Relative paths, control characters and lexical `..` traversal in every explicit form fail closed.
- Import, config parsing and read-only team inspection create no platform directories.
- Existing explicit workspace writers remain the only creation boundary.
- Python behavior, JSON Schema, example configuration, operator docs and Trellis specs stay synchronized.

## Acceptance criteria

- Python and JSON Schema reject `/../escape` and `/tmp/platform/../escape`.
- Omitted/default and explicit-path tests pass on controlled macOS/Linux facts.
- An isolated module import leaves `~/.ase` absent.
- Read-only inspection leaves the default root absent; explicit Company initialization creates it.
- Candidate changes merge with current main without unresolved conflicts.

## Rollback

Revert the merge commit. Existing explicit configurations remain usable; no migration or data rewrite is involved.
