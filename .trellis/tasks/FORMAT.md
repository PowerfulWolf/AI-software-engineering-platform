# Trellis task record format

This directory is the durable engineering-task history for this repository. Keep existing
directories in place: documents and historical conversations link to their current paths.

## Directory and file contract

Use one stable directory per task. New directory names use `MM-DD-<task-slug>`; an established
historical directory name is never renamed merely to match this convention.

Every task directory must contain:

- `task.json`: machine-readable identity and lifecycle metadata.
- `prd.md`: goal, scope and acceptance criteria for a new task.

Historical records may retain the files that actually exist instead of fabricating a missing
artifact. In particular, `09-18-t051-joint-recovered-child-convergence` predates this contract and
keeps its detailed scope and acceptance criteria in `task.json` rather than a reconstructed PRD.

The following files are optional:

- `design.md`: chosen design and important trade-offs.
- `implement.md`: implementation notes and handoff details.
- `implement.jsonl` and `check.jsonl`: captured agent context.
- `verification.md`: commands, results, limitations and remaining human validation.
- Other evidence files named by `task.json` or the task documents.

## `task.json`

Store UTF-8 JSON with two-space indentation and a trailing newline. The first four fields are
required and appear in this order:

```json
{
  "id": "stable-unique-id",
  "title": "Human-readable title",
  "status": "in_progress",
  "phase": "implementation"
}
```

- `id` is stable and unique; it does not have to equal the directory name for old records.
- `title` is the display title. Historical `name` fields may remain for compatibility, but do not
  use `name` instead of `title` in new records.
- New work uses `planned`, `in_progress` or `completed` for `status`.
- `legacy_unknown` is reserved for migrated records whose original status cannot be proved.
- `phase` is a concise, task-specific progress marker. Existing evidence-bearing values such as
  `verified`, `offline_verified` and `ready_for_user_validation` are preserved.

Additional fields are allowed when they preserve useful evidence or workflow context. Do not
remove historical extension fields merely to make records identical.

## Integrity rules

- Never infer `completed` from an implementation note or commit alone.
- Never invent QA, review, test or user-acceptance evidence.
- Use `legacy_unknown / needs_status_verification` when adding metadata to an unclassified record.
- Keep `.trellis/tasks/README.md` synchronized so every task directory appears in exactly one
  status section.
- Keep task paths stable. If a move is ever necessary, update every inbound documentation link in
  the same change.

## Validation

From the repository root, validate the metadata and index with:

```sh
find .trellis/tasks -mindepth 2 -maxdepth 2 -name task.json -print0 \
  | xargs -0 -n1 jq -e 'has("id") and has("title") and has("status") and has("phase")' >/dev/null

for directory in .trellis/tasks/*/; do
  test -f "${directory}task.json" || printf 'missing task.json: %s\n' "$directory"
done
```
