# 恢复同步准备的有界纯扫描复用

## 目标与范围

首次恢复 dispatch 到 seed 发布前，既有同步链执行七次 Builder；每次保持五次 facts.inspect、
十次完整事实观察。已有低层 scope 不能共享这些相邻观察中的相同完整正文纯扫描。
只为 build、seal/require_current、allocate、seed/authorize 添加明确同步边界，复用现有
source_inspection_scope 的 512 项/16 MiB 预算。禁止包装 execute、resume、run 或模型生命周期。

## 验收

- 先 RED 再 GREEN，实际 service 链的完整正文 source/patch/generic scanner 次数下降；
  facts、capture、store getters、commit 前后核验保持原次数。
- 每次仍读取正文；正文变化、fresh gate 漂移和异常均拒绝。下一 public call 重新扫描。
- 成功和异常均释放 scope；authorize 返回时、后续真实 provider admission 外无 cache。
- 不缓存领域模型、授权、hash、数据库、停止或 inventory；不减少原有安全检查。
- 只跑相关增量测试、Ruff、strict Mypy，交 root 独立审查。

## 存量、部署与回滚

无需改库；所有 Task、审批、计划、seed 与历史 bytes 保持原样。当前服务不在本任务中操作。
root 负责部署和在原需求上通过现有公开恢复入口继续。回滚四个模块新增 import/decorator
及本次文档即可恢复旧扫描成本，不改变已封存记录或批准。
