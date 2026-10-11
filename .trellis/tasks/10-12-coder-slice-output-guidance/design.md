# Design and diagnosis

The reproducible signal uses actual Request/Context builders, native prompt compilation,
native artifact/schema acceptance and a real temporary Git repository. Only the process
port is fake: it writes a complete output and a legal dirty source file. The original
production failure cannot be replayed because its ephemeral output is unavailable.

Ranked prospective causes and predictions:

1. Missing explicit prompt guidance: real builders serialize work_slice but never explain
   why partial slices must use progress. System/native prompt assertions fail before fix.
2. Collapsed typed rejection: native catches CoderSliceRejected as ValueError, recording
   only GIT_CONTRACT. Four distinct actual slice-gate cases report the same generic class.
3. Incorrect inherited completion interpretation: guidance could permit later completion or
   drop inherited steps. Existing planning gate rejects both, and new prompts must match it.
4. Other Git/provider causes remain possible for the original run. A no-candidate Git case
   must retain GIT_CONTRACT and cannot be labeled WORK_SLICE.

Keep a single system helper in openai_compatible.py rather than duplicate rules in native
compilation. Use the typed work slice only to choose partial/final instructions; reference
its field names in policy text rather than interpolating arbitrary step IDs into system.
Native wording follows the supplied slice and consumes the same PromptPayload.

Keep all domain check order and predicates. CoderSliceRejected gains a fixed Enum while
its existing fixed messages/ValueError base remain compatible. Native catches the typed
exception before generic ValueError, retains INVALID_OUTPUT/nontransient, and emits only
the Enum plus output digest/size and Enum-mapped Chinese explanation. Do not expose raw
exception messages or output, repair an output, create a progress artifact, refund budget,
alter approvals or move the queue.

Read-side localizeBlockingText/_role_failure mapping is outside this task ownership and
has been explicitly reported to root for separate integration. It must use fixed machine
classes and not infer an old GIT_CONTRACT subcause or display arbitrary failure text.
