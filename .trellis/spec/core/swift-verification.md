# Candidate-bound Swift verification

Controlled executor continuation is specified in [verification-environment.md](verification-environment.md).
The model-command restrictions below remain unchanged; the separately approved executor is the only
owner of the SwiftPM inner-sandbox exception, always under the retained outer sandbox.

## 1. Scope / Trigger

Use when detecting Swift packages, extending verification for a historical Task whose frozen profile
predates Swift support, or changing verifier command permissions after a plan was proposed.

## 2. Signatures

```python
ProjectLanguage.SWIFT = "swift"
BuildSystem.SWIFT = "swift"
_verification_task_commands(source: NativeCandidateSource, profile: RepositoryProfile) -> tuple[str, ...]
is_restricted_swift_command(arguments: tuple[str, ...]) -> bool
_verification_context(plan: CandidateVerificationPlan) -> ContextSource
NativeVerificationFacts.validate(plan: CandidateVerificationPlan) -> None
```

`repository-profile.schema.json` admits both enum values; detector `t020-v3` recognizes `.swift` and
`Package.swift`, ignoring `.build` and `.swiftpm`. Discovery does not execute the manifest or tests.

## 3. Contracts

- Frozen RepositoryProfile, Task, approved stages and prior verification results are immutable.
  Candidate verification may augment only QA/Reviewer definitions with current trusted capabilities.
  Coder/Orchestrator retain the historical command set.
- Augmentation reads `git ls-tree <exact candidate> -- Package.swift`, not current main or working-tree
  contents. Only regular blob modes `100644`/`100755` qualify. Git hooks/fsmonitor and global/system
  config are disabled; cwd, a minimal environment and a 30-second timeout are explicit.
- The shared allowlist is exactly `swift --version`,
  `swift build --disable-automatic-resolution --skip-update` and
  `swift test --disable-automatic-resolution --skip-update`. The policy additionally parses argv:
  optional configuration is debug/release, build product is a simple identifier, test filter is
  bounded to 256 non-control characters; duplicate options (including `-c`/`--configuration` aliases),
  unknown options and missing values are rejected. No package/scratch/credential/compiler overrides,
  shell scripts, signing, `swift run`, `xcodebuild` or sandbox disabling are added.
- These flags restrict resolution/update; they are not a general OS/network sandbox. Dependency or
  toolchain installation remains separately authorized. The incident candidate has no external package
  dependencies. Never use a build script without inspecting its side effects.
- Definitions and `current_policy_sha256` bind the exact commands in a newly approved plan. Unstarted
  stale plans fail current-permission validation before approval/execution; normal Continue proposes a
  fresh plan without invoking agents. Admitted runs/completions remain valid historical evidence under
  their sealed policy, and cannot be replayed to gain new permissions.
- Required priority-20 context `verification.approved_plan` binds plan digest, candidate and per-role
  commands. It explains why the current run's machine policy differs from historical Task text, without
  overriding acceptance criteria or denied paths. Console approval displays exact restricted commands.
- Build/source checks do not establish interactive UI or accessibility acceptance. Missing XCTest,
  authenticated test accounts, trend data or UI execution capability must be reported as unavailable,
  not fabricated PASS. A tool's success is not a delivery verdict.
- Installing Xcode on a host does not mutate ASE project capability. A future Xcode integration must
  add versioned detector/profile fields, an explicit `xcodebuild`/`xcrun` argv validator, role-scoped
  permissions, context/evidence records and contract tests. It must be approved as a new plan
  capability; host installation, `PATH`, or `xcode-select` state alone is never an authorization.
- This candidate is Swift Package Manager-only (`Package.swift`, no `.xcodeproj`/`.xcworkspace`), so
  the current persisted capability is the restricted Swift Package path. Xcode may provide XCTest
  for that package later, but ASE must still explicitly integrate and record that toolchain capability.
- After a toolchain change, probe the exact candidate through `SubprocessCommandExecutor`,
  not only a login shell: its environment defaults to `PATH`, `LANG`, `LC_ALL`. Record the
  selected Developer directory, toolchain version, exit status and suite totals. An operator
  probe remains prerequisite evidence; independent QA must produce its own verdict.
- Swift Package output can contain both an XCTest suite summary and a separate Swift Testing
  summary of zero tests. Read the named suites; do not infer that no XCTest ran from the last line.
- Also reproduce under the selected provider's **OS sandbox**. A normal
  `SubprocessCommandExecutor` pass does not prove a Codex CLI sandbox pass. On macOS,
  default Swift/Clang module caches can target non-writable user directories; isolated
  `CLANG_MODULE_CACHE_PATH`/`SWIFTPM_MODULECACHE_OVERRIDE` avoid those paths but do not
  resolve a subsequent nested `sandbox_apply` denial. Never silently add
  `--disable-sandbox`: current capability rejects it. Any future inner-sandbox
  compatibility mode needs explicit authorization, retained outer isolation, isolated
  scratch, exact candidate/plan binding, and real sandbox regressions for every verifier role.

## 4. Validation & Error Matrix

| Input | Result |
|---|---|
| Candidate has regular Package.swift, current main differs | Candidate-bound Swift commands |
| Candidate marker absent/symlink/directory | No marker-derived augmentation |
| Git inspection fails | RecoveryRejected; no verification launch |
| Unstarted plan commands differ from current permissions | RecoveryRejected; Continue reproposes |
| Old exact approval supplied after reproposal | New plan returned; no agents run |
| Path/sandbox/compiler override or duplicate option | CommandPolicyViolation |
| Valid admitted/completed plan from old policy | Historical verification still readable |
| XCTest or UI prerequisites missing | NOT_TESTED/ERROR, no Reviewer or DONE claim |
| Xcode installed but no ASE Xcode capability/approved plan | Keep Xcode commands unavailable |

## 5. Good / Base / Bad Cases

- Good: historical Git-only Task gets a new exact verification plan; independent roles run against the
  sealed candidate and original Task/event bytes stay unchanged.
- Base: dependency-free Swift package is built with fixed flags in the verifier worktree.
- Bad: grant bare `swift`/`bash`, edit the historical Task, run main and call it candidate evidence, or
  repeatedly approve an impossible XCTest/UI run without repairing its prerequisites.

## 6. Tests Required

- `tests/repository_profile/test_discovery.py`: deterministic Swift detection, schema parity and scratch exclusion.
- `tests/recovery/test_swift_verification.py`: real Git candidate versus opposite working-tree state;
  regular/symlink/directory/absent markers; immutable historical profile; unavailable candidate rejects.
- `tests/git/test_policy.py`: exact allowed calls, focused selection, all forbidden suffixes and aliases.
- `tests/recovery/test_resume.py`: real Git/MySQL old approval after capability change yields a distinct
  plan/policy without calls; exact approval reaches independent QA/Reviewer and joint DONE; context
  plan/candidate/commands align; historical Task/events and Coder permissions are unchanged.
- `tests/web_console/test_manager.py`: exact command facts for standalone/joint and Reviewer-only plans.

## 7. Wrong vs Correct

```python
# Wrong: a frozen old approval is silently expanded, or main is treated as candidate proof.
commands = ("swift", "bash")

# Correct: a candidate-bound command set is sealed in a fresh exact plan.
commands = _verification_task_commands(source, historical_profile)
# Continue returns the new plan for approval before any Agent invocation.
```
