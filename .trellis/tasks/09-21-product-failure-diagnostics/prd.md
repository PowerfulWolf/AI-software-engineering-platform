# Product failure diagnostics and recovery

## Goal and scope

Preserve a bounded, secret-safe explanation of structured upstream failures in the existing
Console Operation, and show the cause plus an actionable recovery instruction in Product
discussion. Do not change delivery states, approvals, fallback eligibility, or retry budgets.

## Contract / design

`Codex/Responses → StructuredModelError → ManagerConsoleAdapter → ConsoleOperation → UI`.
Use existing `error_code` and `error_summary` (maximum 500 characters); no wire/DB migration.
Preserve error category, selected provider/model/reasoning and knowledge phase. Only sanitized
diagnostic error lines may leave the adapter; never persist prompts, raw model output,
credentials, entire stderr or tracebacks. Unexpected failures expose a safe exception type
and operation reference, not arbitrary exception text.

## Acceptance and validation matrix

- Good: successful Product clarification still returns to WAITING_PRODUCT_REPLY.
- Base: provider timeout/quota/auth/start/HTTP/output failures preserve classification and
  concrete diagnostic details; UI shows next steps and a single explicit resume action.
- Bad: secret/URL/ANSI/oversized/multiline diagnostics are cleaned before truncation;
  unrecognized errors and legacy MANAGER_FAILURE do not invent a cause.
- Real filesystem/production preparation + fake subprocess regression proves a failed reply
  preserves the user turn, source baseline and failed Operation; continuing resumes the same
  requirement, without appending a duplicate user turn or bypassing Product approval.
- UI regression covers new causes, legacy errors, running/success dismissal and text-only
  rendering. Only focused pytest, Node DOM tests, Ruff and strict Mypy are run.

## Files and rollback

Allowed changes: structured provider diagnostics, knowledge error context, Console error
mapping/logging, Product discussion UI, related tests and core web-console code-spec.
Revert this patch to roll back. No production records are rewritten; existing failed
Operations remain immutable. After restart, user resumes the original Product reply once
to collect a fresh diagnostic or receive the response. No live model invocation by this fix.

## Verification result (2026-09-21)

- Focused pytest across structured agents, Console, Product recovery, knowledge consultation
  and joint contracts: **102 passed**, two existing dependency deprecation warnings.
- Node UI/readiness contracts: **25 passed**.
- Changed Python files: Ruff check/format and strict Mypy passed; `git diff --check` passed.
- Initial regression was red with MANAGER_FAILURE; fixed regression covers authentication,
  invalid knowledge intent and invalid ProductDraft, each followed by same-Requirement resume.
- Cross-layer review: existing Operation JSON Schema validates the new codes; no schema or
  SQL change, automatic replay, role policy change or provider fallback expansion.
- Production Operation remains FAILED at its original timestamp; Requirement remains at
  sequence 5 / PRODUCT_DISCOVERY with one saved user message. No service restart or real
  model call was performed. User must restart Console and resume the original discussion.
- Full regression and live delivery remain user-operated; changes are not committed.
