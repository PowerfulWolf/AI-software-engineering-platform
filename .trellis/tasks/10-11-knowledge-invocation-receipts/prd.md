# 知识准备调用的完整执行记录

## 目标

知识准备发生在 DeliveryInvocationStart 之前。当前成功后才记录 model call，知识调用限时、
解析失败或服务中断会丢失实际调用与停止事实。补齐统一的调用前意图、每条实际路由的
可信执行观察、成功/失败结果，支持全部 TeamRole，不修改旧知识产物和历史摘要。

## 范围与约束

- 复用 KnowledgeRecordStore 的不可变、有界、内容校验存储。
- 新记录绑定完整 KnowledgeRunBinding、phase、instructions/input/schema 摘要和有限时限。
- 真实 structured observer 在返回/解析前保存 NativeProcessStop 或独立 HTTP round-trip。
- 记录是执行事实，不提供权限，不产生 verdict、候选、审批或新 claim。
- 原有成功 consultation 保持可读与可复用。旧失败没有收据，不能补造停止事实。
- 本任务先完成可信记录与防重复调用边界；任何自动续跑必须另外验证实际 claim、冻结预算
  和原现场，不能仅因出现一个 stop digest 自动重调。

## 验收

- 全部七角色在知识模型调用前已经保存 exact intent。
- 本地限时、provider failure、无效输出和未知中断保留原调用意图及实际观察。
- 同一 exact intent 的完整结果可重放；只有 start 没有 final 时拒绝重复调用。
- observer 发布失败不被当 provider transient 重试；旧 run 不被新 namespace 掩盖。
- 现有 consultation、gap、schema parity 和角色权限增量回归通过。
- 不运行全量测试，不操作生产记录或活动模型。

## 允许路径与回滚

knowledge/invocation.py、knowledge/agents.py、knowledge/runtime.py、必要 composition 注入，
独立 schemas、knowledge/agents 增量测试、相关文档与本任务目录。
存量记录不迁移；回滚保留新增收据。新增 invocation journal 不能用删除事实来解除阻塞。
