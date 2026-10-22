# Exact mixed verification for the original K1

## Goal and scope

Continue the existing K1 without changing its ProductSpec, immutable Plan, Task source, permissions or historical results. Add only the controlled implementation needed to execute already-authorized verification commands and bind their real evidence. User authorization is the standing instruction to repair the platform, approve engineering actions and follow original K1 delivery.

Maintenance base: main `120d168` (runtime implementation `ec9c61c1508bf8e2904696a8160f4931e4fd0c87`). Original K1 Task `task_recovery_6c7e369928a23df6e2ccf8ba32d6f816`, source `5547815464a04991f50a2e0532d6f2f13d8daa69`; native Plan `art_plan_9a1e1138a870bef5f7104892`, SHA `844d632f773cdf7c83fa4623510dcd28322b4f55fc4ee2181703bb0d13d2c3f8`.

## Verified problem

The original Plan has 61 QA verification requirements. Fifty-five explicitly select the registered Python/MySQL capability. Six have no explicit capability, including the exact browser command `node --test tests/team_view/browser/learning-collection.test.cjs` and real live A-to-B pytest. Node is already authorized by original Task constraints and the sealed RepositoryProfile. However, the shared test-entry predicate does not recognize this Node entry, the native verifier parses the entire mixed group as Python, and its report contract accepts only one trusted receipt.

New Plans already reject the unsupported Node entry before the Python prefix split. The initial new-Plan gate-leak hypothesis was withdrawn after two real planner-service cases passed. Do not change a correct gate based on the earlier incomplete inspection.

Ordinary Responses subprocess execution does not prove an OS filesystem/network sandbox. Splitting Node to ordinary Popen is insufficient. A registered implementation must actually enforce the original permissions and bind exact dependencies, invocation, candidate, claim, test coverage and cleanup.

## Ordered work

1. Prove a real offline Node/Playwright/Chrome positive case under a fixed read-only, network-disabled sandbox, then actual denial cases. Current experiment is isolated under `/tmp/ase-browser-verifier-spike-20261022`; it does not execute the K1 candidate or count as business QA.
2. Only after a feasible boundary is demonstrated, define the concrete versioned runtime/binding/receipt schemas and implementation allowlist in design.md. Do not enable an unproven profile or install tools during role execution.
3. Compose per-requirement execution under the same original role claim. Retain Python/MySQL isolation and expose one aggregate receipt to the existing output contract. Aggregate coverage must bind requirement IDs, original argv/criterion/level digests and each real child receipt.
4. Independently investigate the actual live A-to-B requirements. Browser fixtures and the composition test cannot substitute for the real live entry.
5. Run contract, boundary and legacy compatibility checks plus independent review, then deploy at a verified controlled boundary. Fresh inspection is required for existing waits; preserve history and budgets.

## Acceptance

- [ ] Exact approved Node entry executes in a measured, versioned, read-only and network-disabled environment with separate scratch and actual process cleanup.
- [ ] Host/deny-path reads, source/public-temp writes, scratch escape, TCP and unauthorized sockets are actually rejected; failure is not addressed by silently widening permissions.
- [ ] Mixed requirement coverage is complete and exact; Python success cannot cover an unexecuted browser or live requirement.
- [ ] One aggregate receipt references complete child bindings, starts/finals, commands and SHA values; zero tests, skip, unknown cleanup or missing final cannot become successful preparation.
- [ ] Legacy bindings/receipts/requests remain readable with unchanged bytes/hashes. STARTED without final is not replayed.
- [ ] Same-candidate independent QA and Reviewer remain distinct real claimed Runs; no synthetic verdict or candidate is produced by this maintenance task.
- [ ] Original K1 continues through public operations; no SQL reset, baseline replacement, permissions expansion or replacement Requirement.

## Historical Coder observations and limits

The following attempt6/7 observations are historical. Current independently checked deployment and attempt8 continuation are recorded in `../10-22-coder-verification-boundary/verification.md`. This task remains research only; no mixed verifier or live A-to-B capability has been implemented or enabled.

Attempt6 sealed coder-progress `art_coder_567173b6f4ad7d784797f10003a9543b` (SHA `2a5d2399f84279d62ac066c063152605584355e2ffaebf08389a90d23f4b8548`), with25 changed files and steps01/02 complete,03–08 remaining. Its added source-stream SQL file was NOT_RUN and is not itself one of the32 frozen exact QA nodes. The original Plan assigns all61 verification requirements to QA; it does not require Coder to obtain SQL PASS before continuing other implementation. Do not expand Coder authority or falsify step completion to solve that environment distinction.

Attempt7 actually started at `2026-10-22T07:20:22.375350Z`, Run `run_9919a6c7b2f44e6a85422628fb3b2b86`. This observation is not candidate delivery or proof of subsequent model/tool progress.

## 存量数据处置 and rollback

Do not edit original Task, Plan, ProductSpec, source, citations, outcomes, approvals or verdicts. An upgraded registry cannot reinterpret a historical unsupported observation as READY. Use a fresh exact public investigation/resolution after controlled deployment, retain old failure evidence and original work budget. New durable formats must retain old readers; do not roll back a reader after consuming records that require it. Tool installation or the platform spike is never K1 acceptance.

## Browser research status at 2026-10-22T09:36Z

The macOS experiments reached real Node execution and five OS denial cases, but Chrome aborted in HIServices application registration; rendering was not demonstrated. Two300-second Linux exact-image pulls timed out. A third was NOT_RUN because automatic approval was at capacity; its independent resource postcheck succeeded. No container or browser result was inferred from these attempts.

After the user reported the review service restored, a fourth independently bounded exact pull succeeded in103.001s. The official linux/arm64 manifest is `mcr.microsoft.com/playwright@sha256:68456172e8d99f42cf391e835f5d566b3ab0a2c6a745decd9590c4d73c54d2fb`. Docker29/containerd exposes the manifest as image Id; identity checks additionally compare exact Descriptor/RepoDigests/platform, the SHA-verified original config and all seven RootFS diff_ids. Runtime discovery and browser isolation are still separate required checks. Image download alone is no K1 evidence, capability, QA PASS or Review APPROVE.

The original61 QA requirements and actual live A-to-B obligation remain unchanged. Existing scripted Host/MySQL/Git tests establish composition only. A complete candidate and independently claimed, controlled actual A/B execution are still required.


## Real isolated browser feasibility result (2026-10-22)

This is a research result, not a registered capability or K1 QA verdict. The owned offline
fixture uses the official Playwright linux/arm64 image digest
mcr.microsoft.com/playwright@sha256:68456172e8d99f42cf391e835f5d566b3ab0a2c6a745decd9590c4d73c54d2fb.
Fixed uid/gid1001, read-only rootfs, network=none, private IPC, all caps dropped,
no-new-privileges, default seccomp and docker-default AppArmor, bounded memory/CPU/PIDs,
owned scratch/shm and only the exact fixture subtree mounted read-only. No home/root,
Docker socket, secret or target repository is mounted. Created-state copy-out verifies
all224 fixture entries before start. Local path sharing and uid assumptions were measured
and corrected before use; no failed assumption counts as a passing security check.

Actual Node negative probes: scratch read/write succeeded; writing the0666 fixture and
rootfs/tmp failed EROFS; reading the unmounted owned host sentinel failed ENOENT with
unchanged host SHA before its cleanup; external TCP failed ENETUNREACH. A real localhost
listener and connection succeeded. Thus network=none is not a loopback-denial boundary,
and these Node observations do not prove Chromium renderer confinement.

Actual positive Chromium launch with chromiumSandbox=true failed before creating a page:
FATAL zygote_host_impl_linux.cc:130 No usable sandbox!, SIGABRT. No render/click/screenshot
occurred. remote-debugging-pipe was requested, --no-sandbox was absent, detached=false.
No default seccomp/AppArmor/privilege setting was weakened to obtain a green result. The
specific denial layer remains unproven. Both exact owned containers were removed with
cleanup_errors=[]; final read-only resource check found no experiment containers, and
shared image/config/rootfs digests matched. Shared image/cache were not pruned.

Research artifacts remain under /private/tmp/ase-browser-verifier-spike-20261022;
18.7MB owned synthetic fixture cache remains outside production. Next step is an explicit,
versioned feasible executor design with real browser positive/negative checks, then
candidate/claim/requirement-bound receipts and independent verification. Real live A-to-B
also remains an independent required capability; fixture models cannot satisfy it.
