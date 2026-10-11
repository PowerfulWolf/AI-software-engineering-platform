# f88 恢复准备耗时诊断（2026-10-10）

## 结论与边界

精确恢复计划 `f88b78a7888c3e28c91bf298c5f0efd68763a9a1a1733980f166b8bb4d88ab49`
已经经过授权、Task 封存、dispatch 提交和 seed 验证，随后出现真实 Coder claim。
从操作开始到 claim 约 7 分 28 秒。准备耗时仍影响使用体验，但现有证据没有定位到一个
可解释分钟级耗时的单一热点，也没有证明执行卡死或本次性能问题已修复。

本次只做有界叶子读取和静态调用分析，不构造 Host、不初始化 SQL、不调用完整 facts
inspection、不访问活动 worktree、不发送 Team GET、不改授权/任务/队列，不重启服务。
下列生产时间线由负责生产操作的 root 提供；叶子计时由本诊断独立执行。

## 生产时间线（UTC）

| 已观察事实 | 时间 |
| --- | --- |
| 操作开始 | 10:47:42 |
| AUTHORIZATION_RECORDED | 10:48:41.517784 |
| TASK_SEALED | 10:49:31.002209 |
| dispatch 已提交 | 10:54:07 |
| seed 已验证 | 10:55:06 |
| 实际 Coder claim | 10:55:09 |

恢复 Task 为 `task_recovery_f88b78a7888c3e28c91bf298c5f0efd6`。
授权至封存约 49.5 秒；封存至 dispatch 约 4 分 36 秒。时间线限定的是已保存事实的
可见边界，不能据此断言某个 Python 函数连续运行了这些时间。真实 claim 证明已进入
实际调度，不能代替 provider 调用、实现完成或独立 QA/Review 通过的证据。

## 有界叶子测量

使用既有 typed read-only store，每次 Python 探针设 25 秒上限，仅输出计数、大小、摘要
和耗时，不输出 JSON 正文、源代码正文、凭证或模型输出。读取前后核对文件字节/目录
inventory，结果保持不变；没有采集活动工作区事实。

| 读取 | 秒 |
| --- | ---: |
| open_recovery_plan（精确文件） | 0.1228 |
| FileRecoveryStore.get_plan | 0.0065 |
| get_authorization | 0.0072 |
| get_task_record | 0.0185 |
| 有界源 Context preflight | 0.0002 |
| FileContextStore.get（源 Context） | 0.0031 |
| JointJournal.current（精确 parent delivery） | 0.3876 |
| 158 个既有 run 的 list_for_run 总计 | 0.0247 |

第一组探针主体 0.1609 秒；parent journal 与 route inventory 探针主体 0.5929 秒。
单次 plan、授权、Task、Context 解析均很短，parent journal 单次约 0.39 秒，全部既有
route 解析约 0.025 秒。这些叶子自身不足以解释 49.5 秒封存或整段分钟级准备；实际
组合中的调用次数和耗时尚未测得，不能把不同叶子时间直接相加为生产耗时。

| 输入规模/完整性 | 测量结果 |
| --- | --- |
| plan / 完整 patch | 380,837 / 352,035 bytes，27 个保留文件 |
| 源 Context | 569,519 bytes；70 sections；正文合计 518,276 bytes |
| 精确 parent journal inventory | 45 records；64,470,834 bytes |
| route inventory | 158 run directories；207 records；860,165 bytes |
| 当前 parent checkpoint | 与计划批准的源 checkpoint 一致 |
| 读取前后字节/inventory | 不变 |

定位摘要：

- plan 文件 SHA-256：`073ba593b694c0a72e5f6c313c75b63ae054cb7a9ad1e4bd1fe33040cd4cbb7e`。
- 源 Context SHA-256：`767cb1bf17c40788365613c636f3daee6ac32103ac4fedd502628012ff6be002`。
- parent checkpoint：`9a1a02899a6ac5d394962dfe88bb3140917af473e502bbae129e62d6fa1190ff`。
- parent inventory SHA-256：`0d1a20b1f1a2d5fc5e55435828b11777a63db7055dcadee38e426ef3747a138e`。
- route inventory SHA-256：`525711fa0876fc0954ae5c92bb30366b535a1924408e76aa78c76c197fecf0e1`。

## 静态重复调用与尚未验证的部分

`AuthorizedRecoveryTaskBuilder.build` 在开头、结尾各调用一次
`require_current_authorization`，中间独立调用一次 `facts.inspect`。
每次 `require_current_authorization → _require_current` 又调用两次 `facts.validate`。
因此一次 builder 调用包含五次完整 facts inspect；每次 inspect 双读比较，又形成
十次 `_inspect`。分配组合还会通过 sealing/builder 及 MySQL fence 前后校验重新进入
这些路径。这是静态调用结构，不是本次运行已测得的调用累计。

Native source 路径会复核 journal、SQL snapshot、baseline epochs、approved stages 和
parent；部分 workspace snapshot 分支还会增加 source inspection。但当前 f88 的
`workspace_snapshot=None`，不能套用完整 terminal audit 分支的最大调用倍数。
精确源 failed run 只有一条 route，最终 result 为 attempt 2、没有 coder-progress artifact；
已接纳 progress 可以来自更早执行。该事实不能被解释为恢复进度缺失，也不能把本次来源
错标为历史 UNKNOWN 执行。None snapshot 本身也不表示缺少必要安全事实。

## 下一步优化与用户交互要求

若继续优化，应先建立专用离线 repro，沿同一个 exact、非 snapshot 路线统计真实 native
source 子调用次数和各层耗时，包括 builder、facts inspect、source inspect、parent 和
approved-stage 读取，以及既有只读 SQL。不能用更多生产叶子探针替代该组合测量，不能
在活动 Coder 执行期间为耗时重启服务。

优化只能复用有界同步操作内、按内容摘要和精确作用域标识绑定的确定性解码/验证结果；
每轮 fresh bytes/inventory、SQL、claim、stop 和授权校验必须保留。不得跨操作缓存
authority/facts，也不得因重复调用而删除安全复核。测试需验证输入变化立即拒绝、缓存
不跨作用域/请求、错误不被缓存，并用同输入离线计时验证收益。

前端应根据真实已保存里程碑说明“正在准备恢复 / 正在执行开发”，让用户看到进展；
Operation RUNNING、模型调用记录为空或 claim 尚未发布都不能被单独解释为卡死。
真实 claim 也不能直接显示实现完成或验收通过。没有明确失败或待审批决定时，不应
诱导用户重复审批、重建需求或重启活动执行。本诊断没有新增或验收前端实现。

## 存量数据处置、验证与回滚

没有数据迁移、写库或历史修复。保留同一原 Requirement、精确批准、恢复 Task、旧失败
及全部现场；已有真实 claim，继续由生产负责人跟踪实际执行与独立 QA/Review。

本次只新增此诊断记录，未运行全量或增量测试，也未宣称代码修复完成。验证限于上文
有界 typed 读取、静态调用分析及读取前后完整性核对。文档回滚仅移除此新增文件，
不会改变生产事实或执行；后续性能改动需单独任务、增量测试和独立 review。
