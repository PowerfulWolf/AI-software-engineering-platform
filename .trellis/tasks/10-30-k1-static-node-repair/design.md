# Design: bounded source observation for frozen pytest node

The observer uses the accepted Plan and implementation parent chain and the
same candidate Git commit as the existing missing-file route. For each frozen
QA row with one exact `python -m pytest ... path::test_function` selection, it
reads the regular candidate blob with a fixed byte limit and strict UTF-8,
parses Python AST, and identifies *direct source bindings* only. The positive
absence proof is available solely for a simple module of optional docstring
and explicit named `from ... import ...` statements. A direct `def`/`async def`
or explicit `from ... import name [as test_function]` defeats the absence
proof. Star imports, assignments, class/conditional/decorator-driven or other
top-level execution make the result uncertain. The observer never imports or
executes candidate code.

The observation distinguishes `missing_file` from `missing_named_node` and
binds the exact node, frozen row, Plan and candidate commit SHA. The current
candidate Git blob is reread and checked during later decision and output
admission; the observation does not carry a separate source blob SHA. Optional
fields are omitted from old missing-file wires before digesting so historical
records remain readable. The trusted static QA output contract carries the
node identity and all affected criteria. Its validator still requires an
independent QA-authored FAIL, one proof evidence reference, no tests_run, a
finding for each source path and `NOT_TESTED` for unrelated criteria. The
prompt says only a direct source gap was observed; no full test collection or
business behavior was verified. Any ambiguity returns to the original
`WAITING_DEPENDENCY` with no partial mixed verification.

The public wait collector and resolver continue to prove original
`WAIT/NOT_STARTED`, no model/command start, accepted artifact lineage, current
Task/Requirement checkpoint, original and waiting claims and current Git tree
before making this one-use decision. A later QA claim rechecks all facts again.
The result follows the ordinary FAIL → Coder path. No operator-written K1 patch
or fabricated blocked executor receipt is involved.

Validation matrix:

| Source at accepted SHA | Result |
| --- | --- |
| Exact file missing | Existing missing-file proof and unchanged digest |
| Simple import of another test; exact planned function unbound | Named-node source-gap proof |
| Direct function or named alias reexport | No source-gap proof |
| Assignment, star import, dynamic/module-level execution, malformed/oversize source | No node proof for that row; an independent missing-file row may still be proven |
| Git object identity, read or size/body drift | Reject the entire observation |
| Candidate/Plan/claim changes or original QA execution started | Refuse decision/output; preserve history |

Good: independently claimed QA reports source FAIL and ASE routes to Coder.
Base: a direct test function exists; mixed capability wait remains until real
verification is available. Bad: treat AST analysis or manual collection as a
QA PASS, or assert that no dynamically generated test could collect.
