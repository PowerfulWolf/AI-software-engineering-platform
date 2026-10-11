# Root public-flow verification

Root owns only `tests/manager/test_production_execution_baseline.py` and this file
in the isolated checkout. The implementation worker owns the other changed files.
Main remains frozen at `e4023c4` while production K1 run8 executes. No production
operation, service restart, SQL write, or Coder-workspace edit was made by these tests.

The existing public MySQL fixture now has a separate
`completed_output_same_base_pause_resume` case. It uses a real owned native runner,
immutable completed stop and unknown failed output, then public Host PROPOSE,
engineering PAUSE approval, SQL consumption, explicit RESUME, fresh Coder and
independent QA/Reviewer. The new purpose omits the target; the original Task,
approved base, source, branch and legal draft are retained. It checks product-only
authority refusal, wrong Requirement/revision, refusal of approval-as-RESUME,
workspace/index drift, crashes before SQL release and after commit, exact replay,
normal work accounting without refund, and candidate/artifact/role independence.

Incremental command (dedicated test-scoped MySQL safety gate, serial execution):

```sh
PYTHONPATH=src <main-venv>/bin/python -m pytest -q \
  tests/manager/test_production_execution_baseline.py \
  -k 'completed_output_same_base_pause_resume' --tb=short
```

Result: **1 passed, 10 deselected in 48.90s**.

After the final SQL pre-consumption guard was added, the same public case was
rerun: **1 passed, 10 deselected in 51.12s**.

Scoped Ruff check and format: pass. Strict mypy with `PYTHONPATH=src MYPYPATH=src`
and an external cache: **no issues in 1 source file**. The first mypy invocation
set only PYTHONPATH, so mypy treated the imported platform as an untyped installed
package; correcting MYPYPATH resolved those environment/import diagnostics.
No type-ignore or source workaround was introduced.

The old different-source `completed_output_unavailable_pause_resume` parameter
also passed separately: **1 passed, 10 deselected in 62.18s**. It retains the native
rule epoch approval and the original different-target source-rebind behavior.
Both public flows completed independent Coder/QA/Review with one candidate SHA.
No full suite was run.

存量数据处置：these are isolated fixtures only. Production run8 has now stopped
at its local execution limit and remains waiting for complete capture;
no current approval, WorkItem, historical outcome or retained source is changed.
Do not deploy this new purpose until its implementation, schema, UI and review
gates finish and the service is safely idle. Loading it later does not itself
approve or resume K1.
