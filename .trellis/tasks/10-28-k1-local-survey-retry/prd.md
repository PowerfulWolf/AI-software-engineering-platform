# Bounded isolated local survey retry

## Goal

Allow original K1 recovery to tolerate transient incomplete current-account process
surveys without accepting partial observations or changing historical UNKNOWN facts.

## Scope

Only the production isolated local execution survey facade, its deterministic tests,
and the executable survey spec. No public Schema, Task, queue, approval, source patch,
or browser behavior changes.

## Acceptance criteria

- [ ] A validated full worker's sole `PROCESS_SCAN_INCOMPLETE` can trigger up to two
  fresh full surveys, each with its own five-second deadline and owned cleanup proof.
- [ ] A later complete idle survey returns idle; a later active/unknown survey returns
  its blocker without further retry.
- [ ] Protocol, parent identity, startup, deadline or cleanup uncertainty never starts
  another worker and remains incomplete.
- [ ] Three incomplete observations remain a blocked prerequisite.
- [ ] Existing isolated worker, contained UNKNOWN, lint and type checks pass.

## Allowed paths

- `src/ai_software_engineer/manager/local_survey_observation.py`
- `tests/manager/test_local_survey_observation.py`
- `.trellis/spec/core/isolated-local-execution-survey.md`
- `.trellis/tasks/10-28-k1-local-survey-retry/{prd,design,implement}.md`

## Rollback

At a safe idle service boundary, revert the facade change while retaining original
Task/Operation/UNKNOWN records. The previous single-survey behavior remains compatible
with every persisted record. Retry original K1 only via a fresh public Continue key.
