# T046 逐角色 Worker：上线与恢复

## 范围

生产 `ase request` / Console 的原生单仓及多仓子交付现在通过同一个同步 Supervisor 推进：
每次领取一个 Coder、QA 或 Reviewer Run，持续续约，在产物及 Task 状态通过原有校验后关闭
队列项。Coder → QA → Reviewer 仍严格串行，队列完成不等于需求交付完成。

本轮不迁移上游 Product/Designer/Planner 模型会话、独立候选复核 reservation，也不提供
独立 Worker fleet、多 Task 并发部署、自动 merge 或生产部署。独立候选复核仍占用原来的
QA/Reviewer reservation 容量，普通交付队列计算容量时也会计算这些未完成预约。

## 存量数据处置

本轮开发和验证没有修改生产数据库、Requirement journal、审批或 worktree。
不需要手工 `UPDATE` Task 状态或删除队列。新版本在原有 MySQL 队列表旁初始化三张附加表：

- `work_queue_admissions`：Task 首次移交到角色队列的不可变记录；
- `work_queue_steps`：角色、attempt、checkpoint 与批准 allocation 的绑定；
- `work_queue_accepted_artifacts`：在有效租约内持久化并读回验证的产物 receipt。

存量非终态 Task 第一次继续交付时，在同一容量锁事务中写入 admission 与首个角色项。
旧 dispatch/approval/artifact 保留；admission 之后该 Task 的旧普通交付预约不再重复占用容量，
改由当前队列 claim 占用。未迁移 Task 和独立候选复核的容量仍保留。
既有 DONE/BLOCKED/FAILED Task 不会被强行重置；终态需要继续时仍走已有恢复计划与批准入口。

旧版 `project_id` 队列表只允许原有 exact-schema 原子归档升级；混合或损坏结构会拒绝启动，
不能手工改列、删除历史或绕过 hash 校验。详见 Persistent WorkQueue 规范。

## 升级与继续现有需求

1. 先让旧 Console/CLI 的活动交付结束，或按现有受控方式停止；确认旧执行进程及其子进程退出。
   同一 Team/MySQL/workspace 不得混跑旧版和新版本写入者。保留数据库及外置 workspace 备份。
2. 从包含本次改动的 checkout 启动服务，仍使用原来的 `ASE_CONFIG` 和生产 MySQL 配置。
   本文不改变已有配置路径、模型授权或服务启动脚本。
3. 在 Console 打开原需求并点击“继续交付”。有效的非终态 checkpoint 自动接入新队列，
   无需新建需求或复制工作目录。该动作不是重新执行已通过的角色。
4. 在任务详情“角色执行队列”中查看当前角色、队列状态、最近心跳及租约有效性。
   `CLOSED` 只表示那次执行结束；最终交付仍以 Task/Requirement 的 QA、Review 证据链为准。
5. 若提示旧执行仍存在，先确认旧进程确已退出。若提示旧租约尚未到期，等待租约到期并再次继续；
   首次继续可能只回收旧租约，短暂重试间隔后再点一次即可。不要删除 lock 文件、改 owner token
   或把 Task 改成 READY/DONE。

## 中断与审批边界

- 丢失租约属于可恢复等待，不会单凭这一事实把 native/joint journal 固化为永久阻塞。
  旧 Worker 不得再接受产物、推进 Task 或成功关单；待原进程退出、租约回收后恢复。
- 等待或异常返回保留干净与未提交的 worktree。原始未提交改动是工作现场，不是可随意清理的脏数据。
  未知写入、范围违规或不完整候选仍需现有范围/恢复审批，不能因为已重新领取就自动当成候选。
- 已有有效 receipt 的产物经原有 lineage 校验后重用；只有文件、没有 accepted receipt 的残留
  不得绕过所有权检查进入下游。Task 已前进而队列还未关闭时，重启协调旧项，不重复已完成模型调用。
- 知识缺口释放租约和容量。通过原知识补充入口对 exact gap/resolution 完成审批后再继续；
  仅编辑等待文案或手工改队列状态不能授权恢复。
- 主 Agent/主模型仍受批准 dispatch 约束。只允许该 dispatch 绑定的策略版本中显式有序备用路由，
  实际尝试模型在原 ModelRouteAttempt 历史中展示；修改设置不能给旧 Run 悄悄增加备用模型。

## 回滚

不能仅切回旧 binary 就继续执行已写入 admission 的非终态 Task：旧代码不知道新的容量移交与
accepted receipt 约束，可能重复执行或双重计数。先停止写入者，再选择：

- 用当前新版本将已接入队列的 Task 推进到安全终态，确认无活动 claim/子进程后再评估版本回退；或
- 暂停这些交付，保留数据库、journal、queue history 和 worktree，待前向修复后继续。

不得删除 admission、清空队列、改 Task 终态或重写审批来制造“兼容”。数据回滚需完整的一致性
恢复方案，不能只回滚 MySQL 而保留更晚的文件产物，反之亦然。

## 验证方式

本轮使用专用 `*_tests` MySQL 数据库、临时 Git 仓库、scripted/fake Agent；没有运行真实模型或
部署生产。相关命令与实测结果记录在
`.trellis/tasks/09-19-t046-worker-integration/implement.md`。全量测试和实际服务升级由用户触发。
