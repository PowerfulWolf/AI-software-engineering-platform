# Timeout classification checklist

Before changing an Agent timeout or retry path, ask:

- Which clock fired: provider response, socket inactivity, local process watchdog, or Task lease?
- Is there explicit trusted evidence of a provider failure, or only an elapsed local window?
- Does fallback preserve the error origin and its safe diagnostic without leaking stderr?
- Which durable counter is charged, and can restart replay the same next time limit?
- Does the UI show the active stage, next window and exhaustion without offering a futile retry?
- Are knowledge subcalls, role output and legacy Task paths using different clocks?
- Did tests cover provider 504, ambiguous timeout, success, restart and exhaustion?
- Was the process killed by a signal? A negative POSIX return code is interruption evidence;
  stderr words such as authentication/401 cannot override it. Keep the original bytes' hashes.

`agents/codex_cli.py::_failure_diagnostic` prioritizes the explicit watchdog `timed_out` flag,
then a negative return code (`cause=INTERRUPTED`), then recognized provider errors. Clean signal
exits are nontransient PROVIDER_ERROR; dirty exits retain nontransient POLICY_VIOLATION and no
artifact. Never infer cancellation reason, health or a successful checkpoint. The console
projects retained dirty signal exits, including historical diagnostics with wrong auth cause,
as interruption from the sealed returncode; it does not rewrite them. Incremental regression:
`test_codex_cli.py::test_signalled_dirty_run_does_not_classify_stderr_authentication_words`
and `test_blocker_text.py::test_signalled_historical_cli_exit_is_presented_as_interruption`.

Implementation contracts and concrete limits: [Execution and retry policy](../core/execution-retry-policy.md).
