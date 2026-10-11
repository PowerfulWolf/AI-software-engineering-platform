# run7 后处理失败：Root 的恢复实现输入（只读调查）

## 原事实

- Task `task_recovery_8ca06fa0aec236ab940597ad1482bfc8` revision8、attempt7，交付checkpoint IMPLEMENTING。
- Work `work_5d81e7201146a9c300a5badc3376a2677ee6ddcbc508ce0530828eb7948638e0` 已 WAITING_DEPENDENCY。
- 原 Run `run_a711050bf6384b73b588491472001fcd`、lease `lease_bc4c995c1ea75572c62adc06`。
- invocation-start11:14:48.940792Z，capture-start11:15:11.392895Z，source/execution-base
  `8d494027bbbc3a97198dc410601fed11f5f9f91d`，执行基线digest与Work后缀相同。
- 原stop：completed/returncode0，11:38:21.034765Z，output_present=true，
  stopSHA `a28adb139b0442bec17f0825f690767380418ced75dfdc7d23788410d9fd702f`。
- 当时OS精确SID75117枚举无存活成员，leader75117与host78622均消失。不能把这个现场观测
  追溯成更强的旧stop契约；现有stop只绑定leader PGID，保留独立事实。
- typed outcome FAILED/WORK_INTERRUPTED/transient=false，无artifact。lease已RELEASED。
- `.mypy_cache/3.12/cache.db` 是本轮新增22,716,416 bytes，mtime11:22:34.132139Z，
  SHA `b30ebe4a1d658a3ed3bbbee39c9da0fe7dbd39731238b920543cc1c238561888`。

## 确证直接原因与丢失输出边界

`NativeCoderContinuation.finished`（continuation.py442起）在candidate/progress接纳前先完整
inventory。单文件16,000,000上限在mutation.py123拒绝mypy数据库，向外包装为
ContinuationRejected/InterruptionAdmissionRejected，codex_cli.py535捕获后记录WORK_INTERRUPTED。
该检查在codex_cli.py851，先于读取last-message、JSON/Artifact schema与Git candidate校验。
因此不能称该原output已通过或已失败schema，也不能称scanner拒绝。

last-message在`TemporaryDirectory(ase-codex-...)`中；finished异常使作用域退出，读取和验证
raw_output尚未发生。现有stop只存output_present，没有完整output正文/digest。当前failed
outcome不含artifact，不可补造或把不明产物接纳。

只读Git full capture+wire往返+verify通过：28项合法源码草稿、patch556981 bytes，
captureSHA `f8ce0c082b9089b7afa9ddcd82a4deb4024052db8041382bee7a325d0f9a68bc`。
原inventory2299 regular文件逐hash，仅3个已允许pytest/ruff cache改变，无原源码变化；
新增113 ignored路径主要pyc和mypy cache。实时inventory2412文件，总46,542,036 bytes。
`.mypy_cache`不在`is_execution_cache_path`中，即使解除大小问题也会触发越权路径拒绝。

## 可复用 seam

- `validate_capture_stop`：绑定原start/stop/request/Task revision/historical claim，并确认
  owned leader group消失；生产composition继续持Task lock和queue idle-task SQL fence。
- `DeliveryWaitFactCollector._original_invocation/_capture_observation`：复用原claimed身份与
  不可变start/stop校验，不能重置原结果或取消lease历史。
- `GitWorktreeManager.recover/capture_mutations/verify_mutations`：当前source精确HEAD/branch、
  完整合法before/after bodies和index，不需要新model，不产生candidate/verdict。
- `CapturedMutations` 与 immutable `KnowledgeRecordStore`：封存新的后处理失败checkpoint，
  绑定原invocation outcome digest；不要写成原Artifact或覆盖原receipt。
- `RejectedOutputCheckpoint`模式：独立checkpoint、原结果保留、明确被拒artifact不再latest。
  本case没有artifact，需独立discriminator/签名，不能让旧validator宽松接受。
- `BaselineExecutionReservation`与fenced `consume_baseline`：普通工作预算+新Run/claim，
  exact public proposal/execute-pause/resume；仍需明确审批，不用HALDLE自动推进。

## 不可直接复用 seam

- `reconcile_capture`明确只接受known failure、output absent和typed timeout/provider cause。
  本casecompleted/output_present=true，不能fake timeout、清除output标志或补原receipt。
- `supported_rejected_progress`只接受SUCCEEDED的真实CoderProgress Artifact；本caseFAILED且
  无Artifact，collector在已有failed outcome时直接return，不能冒充原progress。
- baseline `_reservation`只接受receipt cause或TRANSIENT_CODES。WORK_INTERRUPTED不是
  transient，本case不能退款、增补temporary failure或使completed output覆盖旧成功。
- legacy rescue针对无outcome的unknown execution，并限制EXECUTION_UNCERTAIN/PLATFORM_BUG。
  本case已有definitive failed outcome，不应利用legacy abandoned把它改成unknown。

## 最小新增受控恢复契约建议（由Root实现）

新typed后处理失败保留事实应绑定原Task/revision/intent、Work/step/claim、request、completed
stop、failed outcome、完整合法草稿与before/after inventory；原产物状态明确unknown/unavailable。
额外缓存需精确freeze path/kind/mode/size/full SHA，先封存完整原缓存和处置授权再隔离它，
不得仅删除或按ignored目录全放行。源码原字节保持；明确人工维护/缓存处置审计，不能写MODIFY_TESTS
来谎称业务测试改了。snapshot捕获可为新维护方案提供有界流式hash，但不要放宽永久cache写capability。

checkpoint仅允许新普通工作额度的retry，必须绑定原failed outcome+completed stop；无transient
refund、无伪造receipt、无接纳丢失output。更新新平台基线并暂停，工程授权者exact审批后再继续。
同一Task/worktree/原需求保留完整历史。已知数据无需直接改库；必须用新增公共恢复入口继续。

未来执行的独立缺口：应在finished之前把完整最终输出作为不可变、bounded、安全私有记录封存，
让workspace gate拒绝也不会丢掉真实output。但只有再次完整核验后才能产物接纳，不能把保存等同成功。

## 当前能否仅点击现有操作

不能。重启/删cache/HANDLE/直接更新baseline均不足：finished门缓存问题和普通预算reservation
缺口独立存在。现有公共接口应给“平台后处理失败；原执行已结束，草稿保留，需平台修复并准备
受控恢复方案”的中文等待，不要求产品用户理解cache/receipt。此调查没有执行这些接口。
