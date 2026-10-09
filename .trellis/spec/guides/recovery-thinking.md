# Recovery decision checklist

Before adding another recovery exception, read
`docs/architecture/2026-10-04-delivery-direction-review.md` and
`.trellis/spec/core/delivery-recovery.md`.

- Separate cause from disposition: dirty work is not itself proof of policy violation;
  a local execution window is not a provider outage or a QA FAIL.
- Distinguish materialization, admission, model invocation, accepted progress, candidate and
  role verdict. None implies the others. Check claim ownership and stopped execution first.
- Can the same authorized Task/branch safely continue at its last checkpoint? Use WorkItem
  wait/retry for recoverable new work; do not create a terminal Task just to force a successor.
- Which authorization changed: business content, source/base, scope, permission, capability,
  or budget? Show that exact difference. A digest is evidence, not a user-facing reason.
- Runtime revision and target source revision are separate. Platform deployment is not
  automatic permission to rebase a candidate or silently refresh frozen knowledge.
- Keep complete old evidence and findings. Read-only capture is not write permission,
  a candidate, an independent verdict or permission to reapply protected rule edits.
- Locate all consumers of the invariant before editing: Task/role compiler, adapter/tool,
  candidate/progress gate, recovery proposal/current facts, Context, Schema, Console projection.
- Regress through the public Continue path and verify same Requirement, unchanged source
  history and complete UI record. Local classes alone do not establish production recovery.

This is a design checklist, not an authorization to change current state contracts. Historical
terminal Tasks remain immutable and use the verified successor compatibility path.

### Legacy missing facts and crash boundaries (2026-10-08)

Do not mistake a successful investigation report for a completed recovery path. Classify whether
trusted facts exist but were not found, or were never sealed. Fixing future recording cannot recover
old absent facts. Legacy rescue must explicitly separate new engineering evidence from historical
outcome/stop facts, require exact human provenance when old host identity is missing, and audit it
as supplied evidence. See `../core/legacy-execution-rescue.md`.

A complete current Git patch can still omit ignored files. With no trustworthy before inventory,
compare the full current inventory against Git plus captured mutation bodies; reject unknown ignored
inputs and links rather than bringing them into a new execution implicitly.

Test the boundary after immutable binding but before SQL consumption, both within the same boot and
after a later same-device boot. Do not create another binding for the same original start. Already
authorized containment remains a historical fact; new publication still rechecks exact live inputs.
Always provide a UI way to reprepare an unapproved stale plan. Validate a subsequent full collector
pass over the old UNKNOWN, not only the first successful restart.

The full collector pass must include the succeeding Coder, QA and Review calls. Their requests
inherit the baseline digest but their immutable queue boundaries may bind later candidate SHAs.
Authenticate the exact consumption epoch through the immutable parent chain; do not rewrite
verifier candidate sources to the rescued Coder input. A helper-only lookup can miss this seam.

### Controlled restart is a conjunction, not a timeout guess (2026-10-08)

Before recommending a service restart, trace admission → actual worker → result/evidence persistence →
queue/lease finish → owned process group and pipe stop → exact service-instance proof → replacement.
`Thread.join(timeout)` returning, a daemon disappearing, a leader PID exiting and a stopped provider
request are separate facts. None alone establishes that the service can abandon its work safely.

Close admission before waiting, retain HTTP writer ownership through actual threadpool completion even
after caller cancellation, and keep already claimed Operations responsible for their authorized
remaining roles. An unknown child stop or failed final write must survive as a blocker even when the
dispatcher thread has ended. Treat known store failures as sticky; only a pure wait deadline permits
reopening admission. Do not classify deliberate service shutdown as provider failure, quota refund,
QA FAIL or user approval.

Signals, configuration apply, command-line restart, background indexing, directory choosers and native
verification tools all share this boundary. Binding a port or publishing the trusted identity must
precede starting delivery workers, so failed startup cannot abandon already claimed work. A private
READY file needs exact request/instance/PID and durable publication; a stale success marker or dead PID
is insufficient. Test the real service process and inherited replacement lock, not only local classes.

Old binaries do not gain a new close protocol when disk code changes. Document the one-time maintenance
upgrade and leave missing historical Run facts untouched. See `../core/controlled-service-restart.md`.

For a legacy UNKNOWN local Coder whose stop facts were never sealed, an idle ASE service or expired
lease is not a stop proof. The platform may perform a bounded, read-only current-account OS survey
and seal a complete draft, but only an engineering principal may separately attest that the old call
and every derived tool ended on the same local machine/account. A real later boot continues to
support the old reboot proof; it never changes a local attestation into a reboot record. Survey
failures are typed WAITING results with no plan or queue consumption, and the console distinguishes
the survey from approval and subsequent execution.
### 维护会话不是历史执行（2026-10-08）

- 全账户 Codex 名字匹配是否把正在调查的平台控制会话或路径里的 Codex 词误当执行？
  以 kernel executable identity 区分；真实 CLI 的未知动作必须保守处理，包含 exec 的 e alias。
- cwd 是空闲 shell 的位置还是工具/孤儿进程的工作位置？仅明确 idle shell 可豁免 cwd；
  真正打开原工作区文件、交互控制位于原 checkout 和不明工具仍应拒绝。
- 不用维护 ancestry 给任意子进程文件豁免。Unix exec 不改变 PID/birth；
  两次清单分类变化须重查已覆盖路径，不能只验 PID 复用。
- 当前调查者的桌面工具是否被 native sandbox 全账户分类误伤？复现真实 OS 路径、
  协议调用链和原 checkout 的完整 cwd/file 占用，而非只测独立 resume。新旧桌面入口
  不一定都有 code-mode-host；临时 kernel.js/trusted-worker.js 名称不能作为信任根。
  正向来源只影响 wrapper 分类，不能扩大 ignored_pids。详见 legacy-execution-rescue.md。
- 原电脑当前没有识别到执行依然不能替代旧调用及派生工具的 exact 工程确认。
  见 `../core/legacy-execution-rescue.md` 的进程归属契约。

### 源码快照与日志不是同一种文本（2026-10-09）

- 通用 secret_assignment 是否把属性引用或路径表达式当成明文？先定位实际捕获文件，
  不能为了让草稿通过而改业务源码或全局放宽日志脱敏。
- 例外是否由已校验文件语言及真实代码 token/AST 确认？字符串、注释、插值、配置和 diff
  metadata 都不能借表达式外观获得例外；强 key/PEM/Bearer 仍扫描完整原文本。
- 完整正文、staged patch、wire 父级、计划读取/重放、required Context 是否同规则？
  只改 capture 会在批准后的 Coder 启动再次失败；必须保持 bytes/digest。
- 页面和复制报告是否保留最近一次精确准备失败？历史 UNKNOWN 三项不应盖住本次实际错误。
