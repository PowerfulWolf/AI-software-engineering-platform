# 恢复准备的有界历史验证复用

状态：**设计提案，等待 root 和独立 reviewer 审查；本阶段只写文档，不实现。**

## 问题与目标

原 K1 恢复从 Task 草稿封存到分配提交实测21分17.65秒，之后封存seed又花5分03.67秒。
标准service链多层before/after freshness观察放大纯历史解码：新分配至少48轮source观察。
用户必须能在合理等待内继续原需求；不能通过削弱批准、SQL fence、停止证明、历史完整性
或QA/Review来缩短时间。模型服务故障单独处理。

目标是在同一同步恢复准备窗口，对**每次重新完整读取、hash且完整枚举的相同历史字节与
相同 predecessor**复用固定验证receipt，而不是把完整历史模型长期存入内存。
保持公共 `JointJournal.current/history` 的现有语义。

## 最小下一阶段范围

1. 固定typed compact record projection与固定完整Journal codec，先写真实file-store红测。
2. 一次同步scope内的完整前缀observer：冷读完整model/integrity/successor校验；温读每文件
   fullbytes/hash/path/inventory，再按exact edge receipt复用纯校验；head仍独立解码并私有返回。
3. 在legacy capacity source的退休和parent观察接入该observer；保留同样的观察次数和native
   SQL、claim、no-start、capture、target、policy检查。
4. 共享既有recovery record owner的**总32MiB/512条**预算；容量用完执行完整streaming fallback。
5. 实际Allocator→sealing→Builder→NativeFacts service链红测，保持两个fence和全读取计数；
   正常、异常、被保留traceback、跨thread/async和pre-model释放验证。

允许实现文件的建议：新 `recovery/requirement_history_observer.py`、必要
`recovery/context_capacity.py` 接入、`read_record_scope.py` 的固定注册/共同预算，以及专用
recovery测试/spec。不得修改team_view、app、生产数据或JointJournal.history公共语义。

**待设计review决定的额外桥接范围：**现有退休checker的 typed port 只有完整
`history() -> tuple[JointCheckpoint, ...]`，compact投影不能冒充这个结果。推荐在
`multi_directory/retirement.py` 增加可选内部typed compact-history能力，原完整history fallback
保留；在 `recovery/native.py` 的内部parent adapter接入该能力。两处只桥接数据投影，复用原
退休/parent判定，不复制授权逻辑。root 当前ownership未包含这两处；review前不实现或扩范围。

## 验收标准

- 已缓存的每个record仍重新完整读与SHA；所有prefix均读完，不能第一个match就停止。
- first/sequence/filename/owner/delivery/path、fullmodel/integrity、完整successor规则冷读不变。
- 温读receipt只在完整rawbytes和精确predecessor相同且固定codec版本一致时有效。
- 新tail立即可见；退休/替换文件每轮新鲜读取；对任意历史篡改/缺失/symlink均fail closed。
- 不能将latest/head、可恢复、READY、授权、停止证明、SQL/Task/claim/lease/Git结论注册到缓存。
- 全共享owner总额不超过32MiB/512条；不把rawbyte预算描述为Python heap/RSS硬上限。
- scope在异常及正常返回清空；下次HTTP/operation重新冷读；provider前释放。
- 红测同时断言减少的是固定typeddecode次数，完整读取和freshfacts次数保持，不用flaky时间阈值。
- 增量测试、Ruff、strict mypy、diff check和独立review完成后才能提交实施。

## 非目标

不承诺仅此优化解决所有准备热点；不变更Schema、持久化receipt、操作审批、Task状态机、
provider fallback、上游knowledge预算、UI、merge或交付业务代码。本阶段仅给可review设计。

## 存量数据处置和回滚

无需改库、重新建需求、重写旧记录或重新生成审批hash。完成实现后空闲时通过受控重启部署，
原需求按既有精确批准和freshfacts gate继续；旧失败保留。回滚仅恢复完整解码的原组合，保留
全部durable bytes、Task/审批/Operation。当前活动生产流程不部署或暂停。
