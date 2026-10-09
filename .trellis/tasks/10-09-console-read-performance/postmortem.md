# Bug Analysis: 已封存基线计划触发慢读与空闲重放

## 1. Root Cause Category

- E（Implicit Assumption）：把“每次完整验证”误当作“每个嵌套模型反复运行同一纯扫描”。
  真实基线记录经过plan/start/binding、模型入站和完整roundtrip，反复AST/tokenize。
- D（Test Coverage Gap）：此前性能读集不含此次大型baseline/capture事实，也没测无工作时的
  `claim_next`持续模型重放。功能上正确的空闲循环仍能耗尽一个CPU核。
- B（Cross-Layer Contract）：已知Team busy机器码和浏览器deadline被通用MySQL指导覆盖。

## 2. Why Previous Fixes Were Insufficient

此前修复确实减少JointJournal、Evaluation与重复Task投影，但新基线计划发布后的热点
已转为工程捕获深校验；不能据不同负载的延迟宣称旧优化被改坏。
0.25秒等待只控制循环间隔，不控制本轮完整历史重放的成本。仅重启或增加内存不能消除重复扫描。
前端通用提示也掩盖了busy与数据库断连的区别。

## 3. Prevention Mechanisms

| 优先级 | 机制 | 状态 |
| --- | --- | --- |
| P0 | 同读纯扫描有界复用；路径/正文/patch域隔离、拒绝结果、异常/线程/容量反例 | DONE |
| P0 | idle完整bytes清单，外部新增和同大小同mtime篡改反例；现有claim锁测试 | DONE |
| P0 | 固定busy/deadline分类、正文hang反例和真实阅读DOM保留测试 | DONE |
| P1 | 实际存量前后只读wire/文件摘要、SQL/扫描次数与耗时分开测量 | DONE |
| P1 | 正式read lifecycle/增量poll规范和恢复思考检查点 | DONE |

## 4. Systematic Expansion

- 相同capture还被恢复/基线模型与Operation完整结果消费；统一检测规则保留，没有特殊放宽。
  public list/get仍每次重验；下一轮snapshot重新读取，不能形成跨轮询SAFE/READY缓存。
- 继续保留全历史会有随数据量增长的I/O与wire成本。大型结果引用/分页需另行版本化契约，
  不在本修复截断、改写或删除事实；当前4.3–4.6秒不是任何规模的通用SLA。
- 新恢复记录发布后要重跑真实性能feedback loop，分别测SQL、文件、纯扫描、锁和前端依赖，
  不把旧OOM、历史日志或截图通用文案当成本次因果证据。
- 空闲摘要虽跨调用保留，但每次完整bytes重查。不能降级为mtime/inode优化，亦不能在
  生产用claim_next当性能测试，以免真实派发工作。

## 5. Knowledge Capture

- `.trellis/spec/core/read-memory-lifecycle.md`：检测scope、idle清单、可执行矩阵、测量边界。
- `.trellis/spec/core/incremental-polling.md`：busy/deadline/不可用和阅读恢复。
- `.trellis/spec/guides/recovery-thinking.md`：热点变化、idle成本及观察/执行分离。
- 诊断归档和本任务保留证据、实现、验证、存量步骤与回滚；无生成模板镜像需同步。
