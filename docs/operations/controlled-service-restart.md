# ASE 受控停止与重启

更新平台代码后，从更新后的检出目录执行：

```bash
uv sync
./scripts/ase-console-service.sh restart
./scripts/ase-console-service.sh status
```

重启会立即暂停新操作、后续角色、模型回合和重试入口，给当前本机 Agent 默认 30 秒收尾窗口。
当前角色若完整返回，仍按原产物、QA/Review 和候选版本门禁接纳；下一角色留在队列。
窗口到期后，实际拥有执行会话的 runner 受控停止本机 Agent 和已观测到的同会话进程，保存
`service_pause` 停止证明及 `SERVICE_PAUSED` 执行结果。未完成的源码和 worktree 保留，原 Task
保持交付 checkpoint，Lease 通过原队列等待事务释放。暂停不会制造 verdict、完成状态或预算退款。

无法取消的同步 HTTP 调用会等真实返回，然后阻止下一轮模型或工具调用。平台不会遗弃后台线程来冒充
停止。重启还要核验 Operation 最终记录、写请求、索引线程、真实会话和输出管道均已结束并完成封存；
任何事实缺失仍会拒绝。脚本核对实例、请求和 PID，等旧服务实际退出才启动替代服务。

原需求保留。干净角色边界可从原需求继续；中途暂停的 Coder 草稿通过精确的“更新执行基线”工程计划
核验并批准接续。旧冻结策略不会自动增加 `service_pause` 续跑权限；恢复使用普通剩余工作额度，不需要
重新批准未改变的产品范围。未领取的 QUEUED Operation 保留给下一次有效启动。

默认最多等待 300 秒；可临时设置 0.01–3600 秒的等待上限：

```bash
ASE_SHUTDOWN_TIMEOUT_SECONDS=900 ./scripts/ase-console-service.sh restart
```

超过时限会明确拒绝重启，原服务仍在，页面读取可用，新写入暂停。可以等待当前工作结束后重试同一命令，
也可以执行以下命令解除这次排空，让原服务继续接单：

```bash
./scripts/ase-console-service.sh resume
```

若原因是最终记录无法保存、执行停止无法证明或生命周期文件损坏，平台会保持拒绝。`resume` 不会放宽这些
校验；先修复记录保存/执行服务并核对事实。不要删 PID、强杀进程或新建同样的需求来绕开检查。

新版拒绝结果会说明具体等待环节：现有写入、交付操作及调度、知识索引、服务拥有的执行进程与记录，
或生命周期记录。纯等待超时可以等工作结束再重试；若显示“完整收尾尚未核验，重复等待不能补齐事实”，
需要核对原执行停止与记录保存，反复重启或重复检查镜像不能补齐这些事实。
旧实例没有记录具体环节时仍显示原摘要，不能根据新的测试结果为旧记录补写原因。

设置页“应用配置”使用同一受控流程。它与命令行重启共用一把进程锁，不能同时启动两个替代服务。
前台运行 `uv run ase-console` 时，第一次 Ctrl+C 或 TERM 也进入受控收尾；重复信号不会强制绕过收尾。

## 首次从没有握手的旧版本升级

更新磁盘代码不会让内存中的旧 Host 自动获得新关闭协议。新脚本发现旧服务没有精确实例握手时会拒绝停止，
而不会宣称它已经安全收尾。这是一次升级边界。

1. 暂停在旧页面提交新操作，等已知的模型调用和工具执行结束，并检查其最终执行记录、Operation 与工作区。
2. 若存在结果/停止事实缺失的旧 Run，保持其 UNKNOWN 和现场；使用该 Run 对应的工程核对/恢复流程。
   服务升级与旧 Run 恢复分开。空闲旧服务维护停止不要求整机重启；旧 Run 可通过
   [保留进度恢复](../user/legacy-execution-rescue.md) 的当前本机调查与明确工程补证据准备方案。
   无法确认旧调用及全部派生工具结束时才需进一步工程核实或整机重启，不能补造历史成功结果。
3. 由维护者停止旧服务，并核实原 ASE 进程及其拥有的执行进程已结束。若旧记录不足，不能标记 READY。
   保留旧 PID、日志及已有生命周期文件到受限的升级归档后，才用新代码启动。归档是维护动作，不能删除
   Team/Project journals、Task、工作区或保留进度。
4. 启动新版本，确认状态显示“服务正在运行，可以接收新操作”。之后的日常停止、重启、应用配置都使用
   上面的受控命令。需求是否能继续，仍由它自己的事实和批准决定。

维护流程不替旧 Run 补写停止记录。异常崩溃、操作系统强杀和服务外独立启动的
ASE CLI 仍需各自的恢复流程；本流程不能保证任意脱离拥有进程组的外部程序已结束，不确定就拒绝替换。

## 回滚

如需回滚暂停行为，先让新版本完成受控 `stop`，再回退行为实现并保留 `SERVICE_PAUSED`、
`service_pause` 和新增停止记录的兼容读取能力。已产生新记录后，不能直接启动不识别这些值的旧版本。不要在活动执行期间直接
换代码或强杀新服务。本改造没有数据库迁移，不改写历史 Task、Run、审批或 verdict。


## 故障服务替换为只读检查服务

若旧服务sticky REFUSED且控制台读取已故障，可由明确获授权的本机工程维护者使用以下入口。
它会归档全部旧生命周期/PID文件和完整日志，核验精确旧实例的kernel身份与实际冻结状态，
结束对应控制supervisor与Host，然后只允许新的只读检查服务。不会继续任何需求，也不会把
原Run UNKNOWN或服务REFUSED改成成功/READY。普通重启仍使用上面的受控流程。

```bash
ASE_CONFIG=/absolute/path/config.json .venv/bin/python scripts/ase-console-maintenance.py prepare
ASE_CONFIG=/absolute/path/config.json .venv/bin/python scripts/ase-console-maintenance.py execute \
  --plan <prepare输出的record_sha256> --confirm-fault-retirement
./scripts/ase-console-service.sh start
```

沿用同一`ASE_SERVICE_STATE_DIR`。prepare要求原Host已经真实挂起；没有自动SIGCONT或任意
进程选择。execute前审阅exact计划，显式confirm只批准这次故障Host退休。实际执行只处理
计划绑定的Host和固定supervisor，不停止历史开发工具。

如果曾完成过维护并恢复普通模式，新退役计划会精确引用上一轮 marker、完成/接纳记录和完整
completion 文件清单。执行期间的 pending marker 阻止启动；上一轮记录按原字节归档到
`console-fault-retirements/<新planSHA>/previous-maintenance/`。新轮仍需重新完成查看模式核验、
维护完成和普通启动接纳，不能复用旧授权。中途失败使用同一个 planSHA 重试，不删除或恢复旧控制文件。

若rename/chmod/实际终止后的日志hash/receipt/marker封存失败，完整现场保留在state目录的
`console-fault-retirements/<planSHA>/`；使用同一个execute命令重试即可完成尚缺阶段。
旧Host已消失时只finalize，不再对其他PID发信号。未知日志writer仍存在时等待它自行退出后
同plan重试；调查失败/身份、config或原文件漂移会拒绝，需要先核对实际原事实。
原服务完整日志不截断，大文件首次核验需要等待。新服务只读启动最多等待120秒建立生命周期。

永久`console-inspection.json`会强制后续重启仍只读，设置normal环境也不能恢复写入；配置apply
和所有HTTP写操作均拒绝。坏marker或损坏档案拒绝启动，不可删除marker或档案绕过。
退出检查模式与原需求恢复需另行完成工程核验，不包含在本维护动作中。
详细契约见[故障服务维护规范](../../.trellis/spec/core/faulted-service-maintenance.md)。

检查模式的 `status` 会明确显示“仅可查看记录，需求交付和写入暂停”；生命周期仍保留真实 RUNNING/REFUSED 状态，不改写历史收尾事实。
