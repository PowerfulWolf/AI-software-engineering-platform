# Implementation record

## Final implementation

The lookup now lazily streams the complete ProductSpec prefix once per actual-approval lookup,
uses only typed exact associations for the rest of the approvals, and finally reopens/hashes
all complete spec/approval records and rechecks category/request inventories and directory
identities before return. Shared sequence validation preserves the original versions and
supersedes rules. Other public reads and Designer current-facts fences remain independent.

Aggregate private fingerprints/associations have 512-entry / 2 MiB serialized accounting;
overflow restores the original complete lookup rather than truncating or adding a validity
limit. The prefix has no full spec/raw body or cross-call authority. New wrappers clear raw
content in finally; streamed predecessors retain only typed version identity.

## Independent review and repairs

The reviewer reproduced three lifecycle gaps in the first implementation:

1. Calling the original fallback inside the overflow exception handler held two fully decoded
   spec models via the active traceback throughout that long scan.
2. A held later spec corruption held the previous full spec from index traversal.
3. A held final raw-SHA rejection held the newly read full text wrapper.

Exit the exception handler/finally before fallback, use lightweight version predecessors and
release the current record in finally, and release each new raw wrapper in finally. Exact
partial-overflow and held-spec/raw-error weak-reference tests now cover those boundaries.
The reviewer independently reran the six affected lifetime/Designer cases and found no
remaining code blocker. No forced GC or manipulation of another component's traceback exists.

## Existing data and rollback

No schema/SQL/journal/approval migration, Task reset or source rewrite. Existing K1 history and
drafts stay intact. Wait for actual production Operations/roles to finish before an idle
controlled deployment. Continue the same Requirement using its public entry and exact approval;
runtime code deployment does not silently rebind its approved source baseline. Rollback only
reverts this optimization while idle and restores original repeated-decode cost.
