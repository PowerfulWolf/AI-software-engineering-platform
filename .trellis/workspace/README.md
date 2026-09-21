# Trellis workspace records

This repository keeps durable task definitions and verification evidence in
[`../tasks/`](../tasks/README.md). The `workspace` directory is reserved for developer/session
journals and other deliberately written cross-session notes.

Current policy:

- Journals are local working memory and remain ignored by Git.
- `.gitkeep` and this README are tracked so the directory and its policy are visible.
- Requirements, acceptance criteria and task evidence belong in the corresponding task directory,
  not only in a workspace journal.
- No developer identity is configured in this repository, so journals are not organized into
  per-developer subdirectories yet.

Do not delete local journals merely to tidy the repository. Promote any durable decision into a
task document or `.trellis/spec/`, then leave the local journal available for session continuity.
