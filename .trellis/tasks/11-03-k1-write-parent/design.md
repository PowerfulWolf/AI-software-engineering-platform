# Design

The current `PolicyBoundToolRegistry._write_file` authorizes a concrete target but refuses a missing parent with `PARENT_NOT_FOUND`. The K1 approved Task explicitly allows new `src/ai_software_engineer/learning_collection/*.py` and `tests/learning_collection/**`, while the approved base lacks both directories. Its first Responses Coder call produced a real nontransient `write_file/PARENT_NOT_FOUND`; the Task is terminal and cannot be replayed.

Keep the existing three-tool protocol. After exact target and role authorization, walk parent components relative to an open worktree directory descriptor, opening existing directories without following symlinks and creating only missing components. Create a temporary file relative to the final directory descriptor, preserve a regular target's mode, fsync, and replace atomically. Reject symlinked or non-directory components and files with special mode bits. A failed or denied write never follows an outside link. The new path remains subject to the original allowed and denied patterns.

| Case | Result |
| --- | --- |
| Allowed nested file under absent parent | Create parents and file, return SHA receipt |
| Existing regular file | Atomic replacement; preserve mode |
| Denied target or QA outside `tests/` | Reject before directory creation |
| Parent symlink or file | Reject without following or replacing it |
| Existing target symlink or special mode | Reject before replacement |

The K1 production repair is separate: release only after isolated regressions, controlled restart, and current Task/Requirement inspection. Use the public Continue path to obtain and approve the exact successor plan. Never alter the failed Run, old Task, candidate, or ProductSpec/Design/Plan.
