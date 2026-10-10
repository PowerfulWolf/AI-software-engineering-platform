# 当前恢复决定与原执行历史分离

## 根因

公开原 K1 的 `CONTINUE_DELIVERY` 已成功准备恢复计划，父 Requirement 仍是 BLOCKED，原 Task
仍是合法的终态 BLOCKED。旧 `requestNodeExecution` 在审批前读取 STOPPED/child blocker，
`requestBlockingSummary` 又提前采用旧工程建议，所以标题说已阻塞/无需产品操作，而页面另处
要求批准并继续。恢复运行后还存在第二个同源窗口：current role queue 已 READY 或
RUNNING/LEASE_VALID，Requirement 的保留 STOPPED 摘要仍盖住它；旧审批的其他展示入口和
保留 callback 也没有统一核验当前是否仍可审批。

## 最小改动

- `latestApproval` 的当前需求调用显式绑定 Project；保留 checkpoint、签发与消费时间门。
- `requestRecoveryDecision` 集中校验当前 Team/Console/Project、能力、未消费精确审批、无活跃
  Operation 和新角色派发事实。Product/final/已批准知识的明确确认步骤优先。
- 当前可信方案显示待工程确认；当前事实、批准者、按钮和批准后的行为直接展开，原失败只在
  原执行历史折叠中。scope approval 明确只准备方案、不启动 Agent。
- RUNNING 的平台恢复 Operation 仅表示平台正在处理恢复，使用 paused 状态，不声称 Coder
  正在调用模型。新的 failure/wait/expired 仍优先。
- 当前 native role queue 可取代旧 Requirement STOPPED 摘要；READY/LEASED 显示排队，RUNNING
  须 LEASE_VALID。不以平台 Operation 推断角色在跑，不覆盖当前 Task stop/wait/expired。
- 阻塞模块、操作模块、Manager 状态和提交 callback 共用同一 actionable decision；新角色出现
  后旧审批隐藏，保留的旧 handler 也不提交。原 Requirement/Task/Operation bytes 不改。

## 存量与回滚

无需改数据库、journal、Task 终态或补造历史。部署后在同一个原需求查看新鲜数据和当前 exact
方案；基线更新时先重新准备新 exact 方案，随后走公开审批并保持独立 QA/Review。不得重用旧
plan digest 或新建同名需求。撤销 app.js 的本次展示改动并受控部署即可回滚；本补丁不改变任何
生产事实，部署验收由集成 Agent 继续完成。
