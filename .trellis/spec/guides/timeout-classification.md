# Timeout classification checklist

Before changing an Agent timeout or retry path, ask:

- Which clock fired: provider response, socket inactivity, local process watchdog, or Task lease?
- Is there explicit trusted evidence of a provider failure, or only an elapsed local window?
- Does fallback preserve the error origin and its safe diagnostic without leaking stderr?
- Which durable counter is charged, and can restart replay the same next time limit?
- Does the UI show the active stage, next window and exhaustion without offering a futile retry?
- Are knowledge subcalls, role output and legacy Task paths using different clocks?
- Did tests cover provider 504, ambiguous timeout, success, restart and exhaustion?

Implementation contracts and concrete limits: [Execution and retry policy](../core/execution-retry-policy.md).
