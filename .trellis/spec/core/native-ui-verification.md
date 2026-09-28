# Bounded native Mock UI verification

## 1. Scope / Trigger

Use only when an approved candidate has an isolated, memory-only Mock UI entry and the acceptance
criteria require rendered, interactive or accessibility evidence. This is a verification capability,
not a general desktop automation API. It cannot validate real login, production data, Keychain or
network behavior.

## 2. Signatures

```python
NativeUiScenario(product, mock_argument, window_title, steps) -> NativeUiScenario
native_ui_capability(scenario) -> NativeUiCapability
native_ui_profile(capability, binary, scratch) -> str
run_native_ui(capability, build_capability, source, scratch, environment, guard) -> tuple[NativeUiResult, ...]
```

`CandidateVerificationPlan.native_ui` is optional and must be accompanied by the approved Swift
build capability. `VerificationExecutionRecord.native_ui/ui_results` are immutable evidence fields;
neither is a QA/Review verdict.

`NativeUiOutput.diagnostics: NativeUiDiagnostics | None` records session status, AX trust,
the target child's native/AX window counts and AX status. The executor attaches the actual
two-token launch argv and observed process-running/returncode facts. A process that exits before
the first observation yields a typed `PROCESS_EXITED` result, not discarded diagnostic evidence.
Legacy receipts omit diagnostics and retain their hashes. Receipt validation binds launch path to
private scratch/build/product and the exact approved mock argument.

## 3. Contracts

- Window diagnostics retain only the exact child PID's counts. WindowServer lacks a per-PID list
  query, so filter its transient metadata immediately; do not return unrelated titles/processes,
  unapproved screenshots or global AX trees. No activation, reopen, menu, AppleEvent or production fallback
  is introduced. Manager sees the available driver/policy hashes and diagnostic fields, allowing
  an explicitly approved diagnostic attempt after a capability change without claiming a remedy.

- Scenario arguments are mock-only (`--mock-*`), the first step is a snapshot, and every press has
  an exact `AXButton`/`AXCheckBox` role plus bounded identifier/title selector, or an `AXLink`
  with exact AXIdentifier, index=0 and exactly one observed match. The trusted driver rechecks
  this link constraint before AXPress; title/description, duplicate IDs and indexing are rejected.
  Link support changes the driver/policy hashes and requires a new exact plan. No arbitrary text,
  menu, global coordinate or system application target is accepted.
- The platform hashes the driver and policy source, binds the candidate, window title, action order,
  role and execution identity into the exact verification plan. A changed driver, policy, binary,
  candidate or scenario requires a new plan and human approval.
- Build remains under the existing Codex read-only outer sandbox with isolated scratch and network
  disabled. The GUI child uses a distinct Seatbelt profile: no network, no source writes, no user
  home/Keychain reads, no AppleEvents, no unrelated process execution, and only its private scratch
  is writable. AX traversal starts at the exact child PID's titled windows and skips menu bars.
- Deny data reads from both user-cache temporary roots and `/tmp` / `/private/tmp`, then allow
  only the exact private scratch subtree. Do not assume pytest or the production executor always
  places temporary files below `/private/var/folders`; that location-only assumption left other
  host temporary files readable. Profile source hashes change with this restriction, so old plans
  cannot silently gain the new executor implementation.
- A press is never retried after an uncertain result. Driver output is bounded, typed, tied to the
  child PID and action, and stored only after the durable STARTED receipt. A missing window, failed
  action, timeout or changed policy is a typed environment block, not a PASS/FAIL verdict.
- Every non-null driver error, including TARGET_UNAVAILABLE, ACTION_FAILED, UNKNOWN_ACTION and
  future error strings, must stop before a verifier model and seal a BLOCKED receipt. Do not use
  an error-code allowlist with a success default. `native_ui_failure_code(results)` classifies
  session lock separately and all remaining errors as NATIVE_UI_UNAVAILABLE.
- Historical COMPLETED receipts with a final UI error remain immutable/readable; the derived
  `effective_failure_code` refuses replay and makes them available to Manager. Preserve the exact
  recorded phase/code in the coordination payload; never rewrite them as historical BLOCKED or
  grant a pre-model source-repair authorization from a completed verification.
- Manager receives up to 40 observed button/checkbox/link controls from the failed snapshot, with
  bounded/redacted selector/value attributes and an explicit truncation flag. These are evidence,
  not new action permissions. A source Button label is not necessarily AXTitle or even AXButton;
  ground a revised scenario in the actual observed AX attribute/role and require a new approval.
- The trusted driver supports `--session-check` returning typed `status=READY|SESSION_LOCKED|
  SESSION_UNAVAILABLE`. Read `CGSessionCopyCurrentDictionary` before launching the candidate and
  before each AX operation/press. Locking the desktop is an environment prerequisite, not a business
  defect: persist `NATIVE_UI_SESSION_LOCKED`, return Manager WAITING_HUMAN with an explicit unlock
  instruction, and do not start that role's model. Never unlock automatically or collect passwords.
  The consumed plan/receipt cannot be replayed; resume through a fresh exact approval after unlock.
- On this host, AXWindows sometimes returned status=0/count=1 but the referenced node had
  AXRole=AXApplication. The earlier `MallocNanoZone=0` explanation was not supported by subsequent
  A/B tests and has been withdrawn; the host was independently confirmed locked. Do not infer an
  allocator defect from transient success. Require actual AXWindow roots and reject application/menu
  nodes. The real interaction test must require checkbox 0→1, not accept environment blocks as PASS.
- QA and Reviewer receive the receipt and snapshots as untrusted evidence and independently map
  each acceptance criterion. Build/XCTest success and UI driver success do not establish delivery
  DONE; real-data/login criteria remain NOT_TESTED when only Mock UI ran.

## 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| non-mock launch argument, menu/global selector or missing first snapshot | reject before launch |
| source/scratch overlap, symlink, changed driver/policy/binary | reject; new plan required |
| user-home/Keychain read, source write, network or unrelated exec | child fails closed; evidence records environment block |
| exact window unavailable | bounded retry for initial snapshot only, then block |
| desktop locked / no logged-in console session | block before GUI launch or next action; Manager requests usable desktop |
| uncertain press/driver process exit | no replay; Manager must repropose |
| TARGET_UNAVAILABLE / ACTION_FAILED / unknown non-null driver error | seal execution block; no model verdict |
| historical COMPLETED plus last-step UI error | preserve hash/phase, derive failure for Manager/replay refusal |
| complete snapshots/actions for Mock criteria | supply evidence to independent QA/Reviewer |
| real account or production-data criterion | remains NOT_TESTED unless separately exercised |

## 5. Good / Base / Bad Cases

- Good: an approved Mock scenario snapshots two accounts, presses exact checkboxes, records changed
  AX values, and QA independently checks the original criteria.
- Base: build/XCTest passes but AX service is unavailable; Manager reports the environment block and
  does not claim UI acceptance.
- Bad: operator drives the business app with CUA, attaches to all desktop windows, or changes the
  global command allowlist and reports screenshots as independent QA.

## 6. Tests Required

- model tests for argument/selector/sequence bounds and capability digest drift;
- real macOS fixture test for child launch, AX snapshot/press, source-write/network/home-read/extra-
  process denial and unrelated-window rejection;
- receipt replay/tamper/role/candidate/action-order tests;
- locked/unavailable/malformed session preflight prevents candidate launch; a mid-sequence lock
  is durably BLOCKED, never replayed, and Manager reports unlock instructions without a verdict;
- launch-exit fixture retains exact argv/status without retry; the real GUI fixture asserts
  READY/AX trust, native/AX window counts and actual launch identity alongside checkbox 0→1;
- independent QA/Reviewer tests that preserve NOT_TESTED real-data criteria;
- all driver error classes through the real executor receipt seam, repeat refusal, legacy completed
  receipt readback/coordination and bounded observed controls for selector correction;
- Ruff, strict mypy, schema regeneration, offline regressions and isolated MySQL recovery.

## 7. Wrong vs Correct

```python
# Wrong: a successful xcodebuild or operator click is treated as UI PASS.
qa_status = "PASS"

# Correct: exact typed AX evidence is attached; QA still evaluates every criterion.
receipt = run_native_ui(approved_capability, ...)
qa.evaluate(candidate, receipt, criteria=original_criteria)
```

## Bounded rendered-window evidence

### 1. Scope / Trigger

Use when the independent verifier cannot establish rendered text/chart facts from AX alone.
Successful interaction is not proof of rendered content. Manager proposes the missing observations;
the platform owner implements/tests the capability, then a new exact plan requires approval.

### 2. Signatures

`NativeUiStep.capture_window: Literal[True] | None`; only snapshot steps, at most six per scenario.
`NativeUiOutput.capture: NativeUiCapture(window_id, image: PngEvidence) | None`.
`PngEvidence(media_type, data_base64, sha256, width, height)` validates bounded PNG bytes.
`VerificationEvidence(text, images: tuple[PromptImage, ...])` replaces text-only executor context.

### 3. Contracts

- The trusted driver uses ScreenCaptureKit's unique exact child PID/title/layer-zero window and
  `SCContentFilter(desktopIndependentWindow:)`. No display/rectangle/global capture, cursor or shadow.
  Transient window inventory is never returned. Only preflight existing screen permission; no TCC
  prompt/setting changes. Check desktop readiness before/after capture. No app activation.
- A CLI helper must initialize `NSApplication.shared` on MainActor before constructing the filter.
  Main-thread scheduling alone was insufficient: the real probe aborted in SLSGetDisplaysWithRect.
  Initialization establishes AppKit's connection without opening/activating windows.
- PNG longest dimension <=1800, encoded bytes <=400000, base64 <=540000; validate signature,
  IHDR dimensions, SHA, chunk CRC and complete IEND with no trailing bytes. Existing per-step 2 MB,
  sequence 4 MB and record 8 MB limits still apply. No silent image drop on overflow.
- A successful approved capture must have pixels; noncapture/failed steps must not. Result-level
  validation errors map to NativeUiUnavailable so the executor seals BLOCKED and Manager handles it.
  Capture denial is SCREEN_CAPTURE_UNAVAILABLE; desktop errors preserve their original codes.
- Omit absent optional fields, retaining historical plan/receipt hashes. Driver/policy/scenario
  changes require new approval; never replay consumed execution. Images stay in the sealed receipt,
  bound to role/candidate/step/window identity, and restart reuses them without recapture.
- Nested hash producers must also retain old bytes: ManagerVerificationAdvice historically hashes
  null selector fields, unlike plan/receipt exclude_none serialization. Omit only a null new
  capture_window/scroll_position in its hash; dropping all nulls would also break history. Test an old populated
  UI advice, not only WAITING_HUMAN/no-scenario advice, and reject true-flag digest tampering.
- Provider-neutral PromptPayload carries at most twelve typed image attachments: at most six
  current captures plus six from one explicitly approved predecessor (contract below). Receipt text retains
  hash/dimension/window identity, not base64. Responses uses input_image data URLs, Chat uses
  image_url, CLI uses --image on private 0600 files inside a temporary 0700 directory and cleans up.
  Fallback routes retain images and the same receipt identity. No model tool permissions expand.
- Image content, labels and AX text remain untrusted evidence. Neither capture success nor a PNG
  attachment establishes QA PASS; original criteria and independent Reviewer gates remain.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| capture on press / more than six | reject scenario |
| locked, permission denied, no unique exact window | typed execution block; no model verdict |
| missing/unapproved/failed-step pixels, corrupt or oversized PNG | reject; no partial success |
| historical absent capture fields | same canonical digest |
| sealed receipt reopened on fallback/restart | same images, no action replay |
| unchanged AX plus no render evidence | NOT_TESTED remains legitimate; Manager coordinates |

### 5. Good / Base / Bad Cases

Good: two explicitly approved states supply distinct sealed PNGs for independent comparison.
Base: AX-only historical receipts still load without pixels. Bad: capture the desktop or put a
base64 string in a text prompt and claim the verifier saw an image.

### 6. Tests Required

`test_real_swiftui_launch_exposes_its_primary_window`: two captures, same window ID, different
hashes, link counter 0 -> 1; retain checkbox/source/home/network/extra-process denial tests.
`test_controlled_execution_independent_receipts_replay_and_denials`: schema, role/candidate binding,
image forwarding, private store reopen, no repeated actions and no text base64.
`test_missing_approved_pixels_is_a_typed_environment_block`: real driver-adapter seam, no replay.
`test_visual_inputs.py` and real local CLI image probe: actual provider image parts, labels,
private files, cleanup, unchanged read-only tool policy. Tests use platform fixtures, not business QA.

### 7. Wrong vs Correct

Wrong: `prompt += image.data_base64`; capture success -> PASS; retry consumed plan with new driver.
Correct: sealed `PromptImage` -> actual provider image attachment -> independent criterion verdict;
changed capability -> Manager proposal -> exact approval -> separately admitted execution.

## Bounded viewport scroll contract

`NativeUiStep(action="scroll", scroll_position=<finite 0..1>)` has no role/attribute/value/index
selector and cannot capture implicitly. The trusted driver finds exactly one enabled vertical
AXScrollBar beneath the exact child PID/titled window, checks AXValue is settable, sets its
normalized value and reads it back within 0.02. Snapshots now include AXOrientation for observed
scrollbars. Zero/multiple/disabled/unsettable bars yield SCROLL_UNAVAILABLE; an unmatched readback
yields SCROLL_UNCONFIRMED. Both become durable execution blocks for Manager, never action replay.
No global scroll event, pointer movement, desktop coordinate, keyboard input or window activation.
An approved subsequent capture_window snapshot supplies pixels; scrollbar movement alone proves
neither a chart nor the business criterion. Max six captures and all sandbox limits remain.

Why: real plan 5339eab5 produced six valid PNGs but QA found charts below the visible viewport
(3 PASS/1 NOT_TESTED). Manager requested this capability, not source repair or manual observations.
Original acceptance is selected-account trend display; extra QA requests for exact sample-by-sample
comparison cannot silently expand Product requirements. Manager must choose observable states.

Required tests: normalized/NaN/out-of-range/selector/capture-on-scroll rejection; real SwiftUI
scrollbar 0->1->0 plus changed pixels in the same window; two-scrollbar ambiguity leaves both
values 0 and stops before capture; old advice/plan/receipt round-trip with null/absent new fields.
Good: exact-plan scroll then capture. Bad: generic wheel/coordinates or claiming AXValue=1 is PASS.

## Exact predecessor evidence for complementary verification (2026-09-28)

### 1. Scope / Trigger

A six-capture supplementary scenario relies on a previous scenario's pixels. Model sessions have
no implicit memory: mentioning old image names or passing a QA report does not deliver those PNGs.
Live QA37d83241 passed3 criteria but could not inspect clear/restore/signed-out; Manager's proposed
complementary scenario assumed previous AB/A/AC pictures were still available. Fix evidence routing,
not business criteria or screenshot execution authority.

### 2. Signatures

- `PriorVisualEvidence(plan_sha256, record_sha256)`;
- `CandidateVerificationPlan.prior_visual_evidence: PriorVisualEvidence | None`;
- `FileRecoveryStore.get_prior_visual_evidence(plan) -> VerificationExecutionRecord | None`;
- `_available_prior_visual_evidence(store, inputs, completion) -> VerificationExecutionRecord | None`;
- Manager input contract v9 includes `available_prior_visual_evidence` with exact reference and
  captured step/image digests; Console displays the reference as part of fresh exact approval.

### 3. Contracts

Only the QA receipt of the plan's prerequisite incident's sealed RETRY_VERIFICATION completion
is eligible. Require same scope, source Task snapshot, original artifacts and candidate; ignore
only append-only prior_run_ids when comparing original inputs. Require exact receipt digest,
matching completion QA invocation, COMPLETED with no effective failure and actual captures.
Reject missing/corrupt/cross-candidate/blocked sources. Revalidate on plan read/write and before
execution. Do not scan arbitrary history, follow inherited image chains, fabricate a partial
completion, relabel QA observations as Reviewer's own execution, or inherit a verdict.

The optional reference participates in plan hash; legacy absent fields retain old wire/digests
and do not gain images. New Manager proposal advertises exactly one source's captures. Fresh
approval explicitly authorizes reuse; current scenario still permits only6 new captures. Attach
prior6 plus current6 as real PNG parts, with historical/current labels, exact receipt and step
identity. Summary omits base64 but preserves AX facts/window/image hashes. Prompt max12; reject
overflow, never silently drop images. Existing PNG, per-step/sequence/record limits remain unchanged.
Reuse sealed pictures after restart/fallback without repeating old actions; no new desktop access.

### 4. Validation & Error Matrix

| Condition | Outcome |
| --- | --- |
| Exact incident QA receipt plus six new captures | Up to12 real attachments, independent judgment |
| No approved reference | Only current images, no implicit historical loading |
| Source plan is not incident source / hash or Task/artifact/candidate drift | RecoveryRejected before execution |
| Missing/blocked/pixelless prior receipt | Not advertised; an explicit invalid reference is rejected |
| Source changes on disk after prior successful read | Revalidate and reject, no recapture |
| Prompt over12 | Validation error, no truncation |

### 5. Good / Base / Bad Cases

Good: old AB/A/AC charts plus newly approved clear/restore/signed-out captures jointly cover criteria.
Base: historical AX-only plans remain readable and supply no pictures. Bad: tell QA to remember old
screenshots, search arbitrary folders, or import all historical receipts without a bounded reference.

### 6. Tests Required

`test_prior_visual_evidence.py`: production proposal/Manager agreement, real store/admission,
six+six image delivery, exact labels, no text base64, new-plan identity, foreign/hash/candidate
refusal, unchanged old wire, reopen/tamper and no recapture. `test_visual_inputs.py`:1/12 provider
image parts and private CLI cleanup,13 rejection. Real local mock-provider CLI images12 fixture
confirms all12 reach the wire without granting execution tools. Retain schema/old-hash regressions.

### 7. Wrong vs Correct

Wrong: Manager prose says combine old images but PromptPayload contains only new images.
Correct: new plan binds the precise prerequisite receipt; provider sends both bounded typed sets.
