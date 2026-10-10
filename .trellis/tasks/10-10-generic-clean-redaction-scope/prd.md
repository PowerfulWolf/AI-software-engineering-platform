# 通用 clean 脱敏扫描的同步有界复用

## 问题与目标

真实恢复读输入中只有85个不同完整正文（约2.43 MB），通用脱敏仍反复扫描同一正文。
在现有 source_inspection_scope 中，179,583 B干净正文连续脱敏3次执行18次regex subn。
只复用已经完整扫描、零命中的纯事实，使该场景只执行6次扫描；输出和所有领域验证不变。

## 范围与硬边界

- 在既有同步 scope 中新增独立generic namespace，以完整正文和实际不可变规则tuple
  （kind、编译定义/flags、顺序）共同确定复用；不能借用source/patch语言例外。
- 只记零occurrence事实，不记含命中输入、RedactedText或显式secret处理结果。
- 复用原512项/16 MiB共享预算；规则tuple只保留引用，正文/path字节计入原payload预算。
  source/patch保留原预算优先级：内部扫描期间generic不读写memo，必要时只逐出generic清洁
  条目，以精确的每条字节账本扣减。单独不可容纳或逐出后仍不可容纳不淘汰。超额、不可编码
  文本完整扫描而不缓存；不扩为全局、异步、worker或模型生命周期。
- source/patch既有语义不变。文件、SQL、停止事实、inventory、Schema/hash校验及精确审批
  都继续实际读取/验证，不缓存authority或领域模型。不操作生产、数据库、审批或worktree。

## 验收与验证

先RED再GREEN，验证干净重复、规则定义/顺序变化、正文单字变化引入secret、实际命中不缓存、
模式隔离、nested/exception生命周期、共享entry/UTF-8 bytes预算、超长/Unicode/surrogate、
独立线程和scope外重扫；cached与uncached的text/count完全一致。跑相关source检测与terminal/
baseline增量回归、Ruff和strict Mypy，不跑全量测试。由独立Agent审查最终diff。

## 存量与回滚

无需改库或迁移任何事实，作用仅是一个同步调用内的临时内存。现有需求的执行及审批历史保持
原记录；父任务决定部署时机。回滚本次generic命中/remember分支与typed key扩展即可恢复原成本。
