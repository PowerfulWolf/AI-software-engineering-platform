# Design

Deletion validates complete durable ownership and inactive execution under existing process/SQL fences. It publishes an exact body-free pending inventory, then physically removes SQL rows, files, Task-owned Git references and temporary resources. A minimal completion revokes the old identity. Current and historical Console Operations have independent sealed restartable cleanup, recovered before history reads. Read-only preview never mutates.

Close retains data and cancellation audit. Shared Team/Project knowledge, unrelated work and merged code remain. State/Artifact/Evidence/Handoff readers define ownership; foreign scope or unsupported owned contracts fail closed. Git branch declarations cannot establish creation authority.
