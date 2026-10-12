# K1 恢复准备的只读性能证据（2026-10-12）

本文件记录部署版本 `9cccb5b5a0eff3b1c3dff6fc0cc5c5210b9fa550` 的代码追踪、生产文件
metadata 和单文件微基准。调查未暂停服务、提交恢复操作、初始化 Host、查询数据库、改变
生产文件或进行交付审批。时间统一为 UTC；上海本地时间为 UTC + 8 小时。

## 实测的公开流程进展

操作：`operation_4e6715d6917b2d10050d5203c6f24996`。
精确方案：`45588301d1b35b02f44762650b6195e4d4a4902b15b128e5f90bc418b4661367`。
父需求：`delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`。

直接只读既有 `team/work-items/console-preparation-progress/<operation-id>/*.json` 中的
`kind` / `observed_at`，未将文件更新时间解释为执行器心跳：

| 已保存里程碑 | observed_at（UTC） | 与前一项间隔 |
| --- | --- | --- |
| AUTHORIZATION_RECORDED | 02:37:43.117824 | — |
| TASK_SEALED | 02:42:39.728281 | 4 分 56.61 秒 |
| DISPATCH_COMMITTED | 03:03:57.383176 | **21 分 17.65 秒** |
| SEED_VERIFIED | 03:09:01.052539 | **5 分 03.67 秒** |
| EXECUTION_CLAIMED | 03:09:06.000010 | 4.95 秒 |

`TASK_SEALED` 是 FileRecoveryStore 中确定性 Task 草稿的封存，尚不是 SQL Task/分配提交。
这些新里程碑证明准备流程在推进，不能由 CPU 使用率独立推断进度。`EXECUTION_CLAIMED`
本身也不证明 provider 已开始。

root 后续报告：真实 `knowledge_intent` 已成功调用；第一轮 `knowledge_assessment` 的 native
代理 exit 1 与两个 HTTP 504 被记录为 `PROVIDER_UNAVAILABLE`；第二轮 assessment 的 Astra
fallback 成功。模型提供方故障与本文件中的准备慢是独立问题，不得互相归因。该后续状态由
root 提供，本次子任务没有重新操作 provider。root 后续已确认主 Coder 于 **03:17:01 UTC**
实际开始执行，隔离工作区出现K1开发变更；不能继续用较早的完成调用列表推断未启动。

随后按 root 授权只读核对精确 `KnowledgeInvocationOutcome` 和 `ConsoleModelCall`：native
第一轮记录只含 returncode=1、kind=failed、stdout/stderr SHA，没有持久化可核实的详细错误
正文；模型调用安全摘要仅为退出1和“本地代理错误详情已隐藏”。部署
`agents/structured.py` 的proxy分支主动隐藏本地错误，`structured_execution.py`仅保存hash，
ephemeral结构化临时输出已被清理。因此无法从既有证据确定该native exit1的具体原因；后续
HTTP504属于独立fallback receipt，不能据此推断native也遇到504。本调查未输出raw日志、
prompt或密钥，也未重复模型调用。

## 部署代码中的静态调用次数

以下行号来自 `git show 9cccb5b:<file>`，不是工作树中尚未部署的改动。

1. `recovery/entry.py:938` 的 `_execute` 首先在 948 调用 `sealing.require_current`，978
   再调用 `builder.build`，之后进入 RecoveryAllocator。
2. `recovery/allocation.py:36` 的新分配路径分别执行 `sealing.require_current`、直接
   `builder.build`、fence 前/后的两个 `validate_current`；共四次 Builder。
3. `manager/mysql_dispatch_authority.py:340` 中的新分配在 366、378 调用两次 validation，
   两者都位于 request/global MySQL fence 内。重放已有分配的路径只有一次 validation。
4. `recovery/task.py:29`、35、118 的标准 native 路径每个 Builder 有两轮
   `inspect_current_authorization`。
5. `recovery/service.py:137`、145、147 的每轮 authorization 都有两次完整 facts inspect。
6. `recovery/current.py:95`、104、105 中，当前 legacy capacity plan 没有 workspace snapshot，
   每个 inspect 又执行两次 `_inspect`，各自重建 capacity reader 并观察 source/target。

因此，正常首次新分配从 TASK_SEALED 到 DISPATCH_COMMITTED 有六次 Builder，即
`6 × 2 × 2 × 2 = 48` 次完整 legacy source 观察；其中 fence 内占 16 次。
`backend.prepare` 的额外成本没有计入这 48 次。

`recovery/seed.py:33`、35 的 `seed.seed` 与 82、111 的首次 Coder `seed.authorize` 又分别
调用 Builder，额外 16 次 source 观察。于是 dispatch 后暂时没有模型调用仍可能是在准备。

不能删掉任一 freshness/fence 校验来减少上述次数；应先消除同一完整字节的纯解码重复。

## 生产 metadata 体积

平台根目录：`/Users/zhangjunshuai/workspace/code/.ase`。只读配置时仅输出路径和
`platform_root`，未输出密钥、runtime.env 或 DSN。目标 Project 为
`project_ai-project_034252eb3595`，目标 sidecar 为
`repository_c78e1680f621ff06c808aa9559666412444fbd7b`。

| 命名空间 | JSON 文件数 | 完整文件字节总量 |
| --- | ---: | ---: |
| 全部联合 Requirement journal | 259 | 308,226,220 |
| 五个退休 journal | 166 | 185,114,269 |
| 当前父 journal | 71 | 105,099,617 |
| contexts | 397 | 107,238,360 |
| artifacts | 148 | 1,713,704 |
| state/execution-baselines | 71 | 86,592,337 |
| state/invocations | 40 | 337,125 |
| state/project-deliveries | 163 | 338,796 |

`_parent` 每次扫描所有七个 journal，不只当前父的 71 条记录。
初始退休检查解码 166 条，两个独立 parent 观察各解码 259 条。因此部署旧实现每次 source
至少有 `166 + 259 + 259 = 684` 次 JointCheckpoint 解码；48 次即 32,832 次。

当前代码每次 Journal 的完整读之外还有独立 `_read_regular` preflight 完整读。静态下限：

- 一次 source 的 journal 字节读取量：
  `2 × 185,114,269 + 4 × 308,226,220 = 1,603,133,418` bytes。
- 48 次 source 的 journal 读取量：76,950,404,064 bytes。
- contexts 全目录 preflight + store 双读，48 次下限：
  `2 × 107,238,360 × 48 = 10,294,882,560` bytes。

这表示 Python 的完整字节读取工作量；不是磁盘真实 I/O、稳定耗时或 profiler 归因。OS 文件
缓存可能服务多数读取，重放、异常退出或并发变化也会改变次数。

## 有界单文件微基准

使用目标 checkout 的部署 `.venv/bin/python` 在独立进程中，仅读取原父的 `000071.json`
一次用于三轮测试，不初始化任何服务或 store：

```python
payload = path.read_bytes()
for _ in range(3):
    checkpoint = JointCheckpoint.model_validate_json(payload)
    checkpoint.validate_integrity()
    copied = checkpoint.model_copy(deep=True)
for _ in range(3):
    fresh = path.read_bytes()
    hashlib.sha256(fresh).hexdigest()
    assert fresh == payload
```

原文件 1,564,872 bytes，SHA-256 为
`73929229f389a9dde37b6d4b068d3a189bf1f13b8a77c0223ab11dd4d7f97208`。

| 三轮测量 | 范围 |
| --- | ---: |
| model_validate_json | 7.03–8.28 ms |
| validate_integrity | 7.20–8.54 ms |
| deep copy | 1.73–2.54 ms |
| fresh full read + SHA | 0.91–1.02 ms |

只能说明完整模型解码/校验确实比该文件的一次读取+SHA贵，不能以一个样本精确计算21分钟中
各部分占比。SQL embedded baseline 解码、Context 全目录解码、baseline/rule 编译仍需独立计数。

PID 43582 在一次 `ps` 观察时运行 41 分 28 秒、CPU 21.2%、RSS 595664 KiB；此前 root 采样
观察到更高 CPU/RSS。单点 RSS 下降既不证明无泄漏，也不证明某个缓存方案的堆上限。

## 既有局部修复与未完成的问题

`78e10ca` + `3723a0b` 在一次 legacy source 观察中复用同一个现有 JointJournal，消除三处
Journal 构造造成的重复解码；仍保留全部完整读取、退休检查和前后事实。真实小 fixture 中
9 次 decode 降至3次，已完成59项增量测试及独立review。它们尚未部署到此次生产运行。
后续本任务compact实现要求每轮head重新完整解码，因此同一小fixture三次观察为7次decode
（1条祖先一次、两个head各三次），与前述局部缓存实现的3次指标属于不同契约。

这不能消除48次独立 source 遍历，且 JointJournal 现有512项限制不是32MiB字节预算。
直接延长完整 typed map 生命周期会保留约308MB原始字节对应的模型图；现有32MiB record
scope 无法容纳全部历史，不能声称只扩大该map就已解决用户等待。

方案与真实service红测见 [design.md](design.md)、[prd.md](prd.md)。本文只读调查未新增生产
审批、数据迁移或新需求；后续授权实现的验证独立记录于 verification.md。
