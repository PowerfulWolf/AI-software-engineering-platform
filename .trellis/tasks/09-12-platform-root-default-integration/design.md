# Design

- Keep default selection and `~/` expansion as pure configuration normalization.
- Reject lexical `..` components before any normalization for both absolute and home-relative input.
- Retain the post-normalization absolute/control-character validator as the shared safety guard.
- Express the same accepted/rejected language in the canonical JSON Schema.
- Preserve the delivered Candidate as a merge parent; resolve its README conflict against the latest main and
  include review corrections in the integration result.
- Add focused import, reader and explicit-writer boundary regressions without invoking real models.

## Validation matrix

| Case | Result |
|---|---|
| omitted on macOS/Linux | `~/.ase`, no mkdir |
| explicit `/safe/root` or `~/safe-root` | normalized explicit value |
| relative/control/any `..` component | validation error, no fallback or mkdir |
| read-only snapshot with missing default root | `TeamReadError`, no mkdir |
| explicit Company writer | initializes the external workspace |
