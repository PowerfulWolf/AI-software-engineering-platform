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

### Completed rejected reports and current presentation (2026-10-12)

Separate a completed process, accepted report and complete retained draft. A genuine zero-exit
stop with output can still yield INVALID_OUTPUT; do not replay it as a candidate or call it a
provider outage. Its lawful draft may support an exact ordinary-work new execution through the
existing baseline prepare → engineering PAUSE → independent RESUME, while the original failure
and counters stay intact. Derive the recovery reason from the sealed typed error; callers cannot
assert stop, validate their own draft or exchange rejected/unavailable budget causes.

Read-side current facts and copied reports must use the same current validated plan. Historical
CHECKPOINT_UNAVAILABLE/OUTCOME_REJECTED records remain history and cannot override a later complete
draft capture. New fixed WORK_SLICE diagnostics retain their observed reason; old GIT_CONTRACT
without a specific saved subcause remains unknown. Never infer historical raw JSON from a later
test reproducing one possible violation. Check frontend capability again when retained controls
are clicked; old compatible display is not permission to submit a new purpose/reason.

Actual public native fixture coverage should include original rejection → exact plan → independent
human PAUSE → RESUME → new claim/Context → candidate/QA/Review. A collector-only or queue-model
test misses the Manager diagnosis, original output gate and all-role execution lineage seams.

### Legacy missing facts and crash boundaries (2026-10-08)

Do not mistake a successful investigation report for a completed recovery path. Classify whether
trusted facts exist but were not found, or were never sealed. Fixing future recording cannot recover
old absent facts. Legacy rescue must explicitly separate new engineering evidence from historical
outcome/stop facts, require exact human provenance when old host identity is missing, and audit it
as supplied evidence. See `../core/legacy-execution-rescue.md`.

An existing `capture-start-<run_id>.json` does not by itself mean that the original execution has
a stop record or a usable checkpoint. Re-read a start-only record and bind its complete request,
claim, scope, task revision, policy and manager-owned worktree before allowing legacy preparation;
reject any stop/receipt for that Run through the native fact path. Never create the missing stop,
outcome or checkpoint while making this distinction.

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

Original process-group absence is not complete session absence: a same-SID peer can move into a
different PGID and close both inherited pipes. Bind stop ownership to the actual Popen before reap,
inspect the complete SID and every observed kernel birth, and keep EOF separate. A known birth
escaping the SID cannot disappear from history; never signal a recycled PID under its old birth.
Do not claim unobserved setsid descendants are contained by a session proof. Exercise the real silent
peer and bounded OS-inspection failure, not only a fake leader.

Process exit also cannot precede the required durable save boundary in the Host registry. Trace real
command evidence put → outer run seal or controlled verification receipt put, including nested and
cross-thread consumers; keep stopped entries finalizing until all required saves return. Store failure
must preserve uncertainty. Do not keep capture exceptions/tracebacks in long-lived ownership objects,
and test that failed ownership capture releases its caller payload. See `../core/owned-session-stop.md`.

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

### 已封存方案与页面可读性分开核验（2026-10-09）

- 按钮消失不意味着计划没有成功。先沿 sealed operation → store read → HTTP → browser gate
  核验，不能继续修进程扫描器、重建需求或再次生成计划来绕过读侧失败。
- 一个 writer 接受的完整结果能否重开读取？按真实 serialized UTF-8 JSON bytes 验证预算，
  含完整正文、重复capture、escaping和inventory，不只给小型假结果做roundtrip。
- 超限读写都有界，历史摘要链与正文不截断。通用文档上限与完整 Operation 上限不是同一政策。
- Operation不可读时，Console readiness和交付权限分开；需求内要持久说明门禁原因，
  关闭全局通知后仍有下一步。读成功后最新精确方案重新显示，不能保留旧勾选替代确认。
- `RECORD_NOT_FOUND` 是否真缺事实，还是模型新增 absent 默认使旧内容寻址 key 漂移？
  验证原文件/摘要与真实嵌套 canonical dump，不能凭异常名补造证明。新增字段的兼容测试
  要回放旧 key、只读历史和处理幂等，不只比较 `to_wire()`。详见 live-team-view.md。
- 页面很慢时先测成功读的完整历史 bytes、解码次数和独立请求依赖；单次 snapshot 复用
  完整已校验 prefix，与跨轮询缓存或截断历史是不同方案。见 read-memory-lifecycle.md。
- 新恢复/基线计划发布后，是否新增了同一 capture 的递归扫描热点？分别测 SQL、完整
  history、敏感信息解析和空闲 claim。轮询间隔不限制一次重放的成本；SHA/mtime缓存也
  不能替代每次对完整历史字节和路径的校验。详见 read-memory-lifecycle.md 的有界复用。
- 忙碌机器码与客户端deadline是否被通用数据库错误覆盖？保留阅读状态并测试下一轮
  恢复；客户端结束观察不等于后台worker或Agent停止。见 incremental-polling.md。

## 保留后的执行权必须持久暂停

连续保留/更新两次以上时，是否沿完整可信 binding 链保留所有精确撤销？最新记录中的空字段
不能让旧 checkpoint/candidate 复活；排除最新checkpoint也不能重新选回其显式supersedes
祖先。公共继续用例必须包含真实已接纳进度，再经过第二次暂停更新，而不只有timeout capture。
当前执行源、可交接候选与旧QA/Review finding是不同用途，过滤不能丢掉返工依据。详见
execution-baseline.md 的 accepted artifact order 与 repeated baseline 验证矩阵。

保存草稿与真正启动下一轮是两个不同决定。只跳过同步 Host.resume 不能暂停独立 dispatcher；
必须在原 Task lock→queue authority→Task row fence 内写入精确 WAITING_HUMAN hold。更新代码/
工程规范时延续该 hold 与预算，最后由匹配最新 binding/disposition/source/inventory 的明确决定
释放。授权已落盘但 SQL 尚未提交的恢复重放必须重新核验现场；已提交重放不能重复启动。
项目原生规则采用完整不可变 Git epoch，并同步进入 prompt 与知识查询，不能以路径/hash 清单
代替可阅读的精确增改删正文，也不能静默重编译 hard/structured policy。

### 模型成功、产物发布和交付采纳分别验证（2026-10-11）

- Schema是否只要求正整数，却没有把progress序号绑定到当前request.attempt？不要混淆Task revision、
  queue checkpoint和run attempt；动态Schema/prompt与live接纳同时约束。
- 新语义门能否使旧sealed outcome读不出来？新接纳校验不能加强全局旧模型validator而破坏摘要历史。
- ArtifactStore/AcceptedRoleArtifact publication是不是发生在最终StateEvent之前？查实际消费事件，
  不能只凭“accepted”类名认定进度已接纳。已拒绝的精确ID不得在下一轮latest选择中复活；合法祖先仍保留。
- 已停止且有完整被拒产出与未知中断不同。保留原completed stop和原JSON，独立封存完整合法现场，
  按正常工作额度产生新Run，不纠正旧JSON、伪造timeout或refund transient。
- 恢复首次执行的typed wait是否写回了原需求游标？只有reader发现live successor不能代替写侧挂接。
  通过精确已批准dispatch+真实当前wait接回，不能重复_execute来重新得到一次异常。
- Conditional admission无exact消费决定时是否仍返回None/原delegate，让默认dirty门生效？
  一旦选中专用capability，后续读不到决定应拒绝，不能变成non-null no-op dirty许可。

具体契约与负例见 `../core/rejected-coder-output.md`；每轮处理必须覆盖完整ignored inventory和既有历史。

### 一次性外部 fixture 维护的边界（2026-10-11）

- 未知令牌负测是否仍覆盖非空输入？用独立 fixture ledger 的真实生成 claim，断言其 token
  非空且不同于当前 claim，再传给当前 ledger；保留空值、过期 fence 独立断言。不要为过 scanner
  把非空场景重复改为空值，也不要按字面值/hash/tests 目录放宽检测。
- 文件 mode 是否受维护进程 umask 影响？冻结 exact before/after 与 mode，临时文件显式 fchmod
  后 fsync/原子替换；原意图审计先落盘，完整 capture/wire/verify 后才发布 completion。
- 原执行真实停止和人工测试修改是不同事实。Task/queue fence 内只写 exact 获授权文件，保留
  原 outcome UNKNOWN 与失败历史；raw before/after 仅受控 sidecar 私有保存，仓库只留脱敏展示。
  后续走公共 baseline propose/execute-pause/resume，不能用会立即执行的 HANDLE 代替只读准备。

本次 exact plan、隔离 28 项完整捕获红绿和目标测试证明见
`.trellis/tasks/10-11-run6-fixture-maintenance/`。不改变产品契约或旧事实，不计 ASE 自治交付。

### 恢复性能要量到真实边界（2026-10-12）

- 将 `TASK_SEALED → dispatch committed → seed verified → first admission` 分段，分别数
  builder、facts、完整SourceReader、只读SQL snapshot、capture和inventory，不把局部解码测量
  外推到整个恢复。fake若替换了被测门禁，未覆盖的耗时必须写unknown。
- 有限次数仍会因嵌套验证放大。保留fence的fresh语义，同时识别immutable模型、完整prefix及
  live事实各自的成本；不能通过删安全门、mtime缓存、截断补丁或猜测停止证明加速。
- 长标量补丁和大量嵌套模型的复制成本不同。至少用同一真实source事实的独立只读重放核对结果
  digest；plain计时与函数profile分别报告。cProfile可能放大深拷贝的小调用成本，不能凭profile
  的累计时间断言端到端回退或改善。嵌套累计时间不能相加。
- `find_approval → 每个approval find_product_spec → 全specs` 会产生O(A×S)历史解码。
  优化应建立单调用内完整且稳定的关联prefix，并保持全部原始字节、目录身份、关联与重复检查；
  approval/current权限不能加入跨调用或模型期间的成功缓存。
- 运行中的生产Operation需要保留原授权及现场；冷读重放的时间不代表它当前在哪个函数。
  新优化只在合法idle维护边界上线，不重复提交审批或重写旧记录来制造进度。

### 优化路径必须保留可信校验扩展（2026-10-12）

- 用新的内部 typed 结果绕过旧公共授权方法之前，先验证可信 composition 是否增强了该方法
  或受保护的当前事实校验。只确认 Native verifier 的 exact class 不足以保留 Service 的扩展。
- 标准方法身份要比较定义时保留的原函数、实际 receiver 与函数绑定；比较当前 class attribute
  会把 class-level replacement 自己认成标准实现。实例、子类、类级覆盖都要有精确拒绝负例。
- 公共授权入口保留原完整路径。只有确认标准 composition 的内部 builder 才派生已有末次
  完整事实；最终 gate 再次检查资格和完整 Plan/facts。未满足优化条件回原路径，不删更强校验。
- 用原版本调用图作对照，证明旧路径拒绝而新路径曾放行，再修到红绿。区分可信扩展兼容问题
  和真实生产配置；没有观察到生产扩展时，不能宣称现有需求曾被越权放行。

执行契约和新增六个拒绝回归见 `../core/recovery-admission-facts.md`。

### 恢复派发与服务收尾是不同边界（2026-10-12）

- `DISPATCH_COMMITTED` 证明派发已提交；恢复 seed 和额外 Context 完成之后才物化 SQL Task。
  Task 行不存在与已提交 dispatch 不矛盾，也不能把准备阶段显示为 Coder 正在开发。
- 服务受控停止等待已接纳 Operation 全部完成和持久化；`resume` 只解除 drain，不取消当前
  preparation。没有协作式取消/可验证停止边界时，不通过重启强行加载性能修复。
- 已存在 plan/authorization/task/dispatch 可以按原精确身份重放，不意味着任意中断现场都
  可继续。seed 应用后的 dirty 现场若尚无 seed receipt，不能推断为已验证完成或直接重置。
- 同步完整观察窗口只减少原嵌套读取：保留两轮完整 source/target/terminal、末轮新鲜停止和
  工作区核验及旧 Worker 锁；不要宣称旧重复 stop/capture/inventory 的调用数量都未减少。

实际 modern 窗口、旧 wrapper 兼容和组合增量的范围见 `../core/recovery-facts-window.md`。
