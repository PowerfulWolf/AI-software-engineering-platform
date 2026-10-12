# 集成验证与存量处置

基线770c02e；实现、测试及review均在隔离维护worktree。当前生产原K1真实FAILED INVALID_OUTPUT、已停止、完整草稿保留，未交付；原execution/base/attempt/approved scope未手工改写。

## 已审查组件

- slice指导050faba：另一agent Standards/Spec无阻塞，31相关独立选例通过；worker126相关用例通过，无全量测试。
- summary20d1ff7+UPDATE导航edf5c77：独立review发现合法replacement导航回归，真实producer→HTTP→shipped refresh红绿后放行。26Python和85相关Node，真实旧编辑1例通过；不把独立result借用为当前审批。
- rootUI0423ba0+fe70ea8：独立review所发现的known-vs-unknown诊断、旧stop覆盖currentfacts和generic分类下旧服务虚假可点SOURCE均以真实harness红绿修复。独立review无阻塞。
- backend896132d：两个独立review分别覆盖proof/Git/queue/schema及Console公共权限/旧能力/UI范围，均无阻塞。worker44INVALID负例、19Schema、旧WORK/SOURCE policy/RESUME兼容、后续StateEvent拒绝、manifest7均通过；16文件Ruff/strictMypy通过。

## 集成增量

- summary+blocker Python：72 passed/12.86s（26+46，实际shipped JS parity）；无MySQL。
- 六图Schema及实际manifest7：20 passed/39 deselected/4.87s。
- 五相关summary Node：85 passed。
- 五相关产品/知识/交付状态/readiness操作Node：153 passed。
- 真实旧编辑UI选例：1 passed/0.19s；错误筛选模式的文件空run未计入覆盖。
- engineering111及provider13：集成scope门暴露旧fixtures缺少真实resource字段，分别17处与2处具体Console result补身份，native outcome/harness/foreign-stale负例/生产gate均保持；单文件111和13各通过，独立fixture复核无阻塞。最终组合124通过。
- 所有26改动Python文件Ruff check/format与strictMypy通过。新test最初Optional return检查缺失，增加显式non-null断言后严格检查通过，无ignore或类型降级。
- JS syntax和diffcheck通过。没有浏览器视觉验收：当前环境所列browser技能路径不存在，未把fakeDOM验证称为真实浏览器验收。

## 公共真实native/SQL恢复

Root独占ai_software_engineer_test执行两source目的完整publicHost及两queue参数：4 passed/124.24s。
实际原生completed subprocess、super Codex adapter真实{} INVALID、合法完整草稿、公开prepare/exact人PAUSE/独立RESUME、新Run/Context/claim、候选和独立QA/Review均验证。模拟器两次red仅补合法Manager诊断与移除新case越权cache写，未放宽生产policy；旧WORK cachefixture保持。

守护使用0600/no-follow OS锁、exact database校验、GET_LOCK、无其它sessions和13tablesempty前提；finally ownedprocess0且13tablesempty清理、guard释放。没有生产SQL UPDATE或Host初始化诊断，也没有与worker并发SQL。

## 存量数据处置与后续

原Task task_recovery_5536cf4e59ca28db0213bd719d50860d、Run run_cd17fc4c9d254fdf8ae13f19d0cc1fe9、source1769977和旧失败保留，旧terminal task不复活。原GIT_CONTRACT具体子因未保存，不用新的slice红测推断历史原JSON。

无需DDL/改库。先consistent READ ONLY核对所有ACTIVE claims与RUNNING work，再controlledstop实际READY/旧实例退出后FF+locked依赖+push+start；公共readiness、version7、原330历史摘要与原需求/失败需重新验证。注册source更新与runtime更新分开：registered clean main FF到已推送精确版本，再公开原Requirement PROPOSE，读取全部plan及native-rule diff，exact工程PAUSE批准后fresh独立RESUME。此处步骤尚待生产执行，不代表已交付。

维护command SUCCEEDED、服务restart或plan ready都不是K1完成。需要真实同candidate QA PASS、Review APPROVE与Handoff。

## 风险与回滚

不宣称无bug、已根除内存泄漏或线上性能达标。增量并非完整suite，仍需要用户自行跑全量验收。受控关闭后可回滚兼容代码；新rejected reason/binding消费后保留完整历史与compatible readers，优先forward fix，不退款、不删原Task或重新建需求。

## 2026-10-12 08:10（UTC+8）实际部署与存量推进补记

本段追加本次维护负责人已实际执行并核验的事实，保留上文当时“尚待生产执行”的历史记录；文档收尾没有再次操作生产、数据库或模型。

- `ead05e7` 已在 idle 前提下通过受控停止取得 `READY`，旧实例实际退出后完成 main fast-forward、`uv` locked 依赖同步、推送和启动；该次启动 PID 为 `87430`。公共 Console 已返回 contract `7`，readiness 为 HTTP `200`。
- 原需求范围的操作摘要已正常读取：`total_count=68`，本页 `5` 项，`active=[]`、`active_complete=true`。原 `330` 条历史操作完整保留，先前的摘要 `503` 已消失；没有重写历史结果、批准或原失败事实。
- 随后的 `7ef2425` native Coder 诊断展示小修经独立审查 `0 blocking`，再次在 idle 前提下受控停止取得 `READY` 并确认旧实例退出，完成 fast-forward、locked 依赖同步、推送和启动；新实例 PID 为 `4722`。原 K1 的真实 GET Team 返回 HTTP `200`，前端数据已显示“开发报告未通过代码与工作区校验”；旧 `GIT_CONTRACT` 的具体子因仍未知，不能据此推断成切片错误。
- registered clean main 已从 `1769977` fast-forward 到 `7ef2425`。这是注册代码基线更新，旧执行的 source revision、失败记录和完整草稿仍按原事实保留。
- 已通过公开入口为原 Requirement 提交 SOURCE prepare，操作 `operation_d814f022e9e3d59a6e1293592cf5132e` 的已观察状态为 `QUEUED`。尚未完成精确方案与 native-rule diff 审阅、人工 `PAUSE` 批准、独立 `RESUME` 或 K1 交付；没有创建重复需求。

上述结果证明已修复版本部署和存量读取路径已生效，不代表方案已准备完成、Coder 已继续或需求已交付。后续仍须沿原 Requirement 的公开恢复流程完成审批和继续，并取得同一候选的 QA PASS、Review APPROVE 与 Handoff。
