# T035 多目录需求交付：修订设计

## 已确认边界

一次需求可以涉及一个或多个项目，一个项目可以分布在一个或多个目录。入口接收
先创建一个有名称的“需求项目”，填入 `project_roots[]` 改造范围；目录不要求相邻，
也不要求预注册项目组。准备完成后才在需求项目中讨论需求。需求项目是外置协作空间，
不是代码仓库，不要求人为建立业务项目层级。原强制分组方案已撤销。

## 目标数据流

公司是 sidecar 的收纳与上下文边界。`companies/<company_id>/knowledge` 保存共享知识，
`projects/` 统一收纳项目知识和每仓运行事实，`requests/` 保存需求项目记录。
Agent 团队仍归平台组织所有；目录集中不等于权限共享，代码原地保留，不复制源码。
不同公司的项目、交付 ID 也必须隔离，不能仅靠换文件夹防止共享 MySQL 数据串用。

```text
需求项目名称 + 一个或多个改造范围目录
  → canonical 路径 / VCS root / relative scope 解析和归并
  → 各目录 ProjectProfile、规范发现与编译
  → READY_FOR_DISCUSSION（此时尚未调用模型）
  → 在需求项目内聊需求 → 一个 ProductSpec / 用户确认
  → 跨目录 TechnicalDesign（接口契约、影响路径、验证方法）
  → Planner 生成有序执行单元
  → 每仓独立 Task、worktree、Coder→QA→Reviewer
  → candidate revisions 集合 + 联合验证 + 一份需求交付结果
```

## 接口方向

- `ase request create PROJECT_ROOT... --name NAME`：创建并准备需求项目，不要求提前提交需求。
- `ase request discuss REQUEST_ID --message TEXT --checkpoint SHA`：准备好以后再聊需求。
- `ase request approve/status/resume`：在同一需求项目上批准、查看与继续。
- `ase project start PROJECT_ROOT... --requirement TEXT`：兼容已有的一步接单入口。
- reply/approve/status/resume 通过一个 delivery ID 定位完整需求，无需逐项目重复接单。
- 上游需求/设计使用 source scopes 集合，各项记录 requested_root、repository_root、relative scope、
  profile/规范 digest、base revision；业务归属和代码仓库身份区分表达。
- 下游 Task.repository / source_revision 保持单仓精确语义，只对需要修改的仓库创建 Task。
- 父交付关联所有子 Task/candidate/evidence；不把多仓结果伪装为一个 SHA。
- 同仓多目录归并后仍只允许选定范围；权限不能自动扩展到整个仓库。
- 前端需消费后端的共享接口定义和已验证候选事实，不能依赖主 checkout 已合并变更。
- 联合验收按需求和项目流程决定，不强制增加一个人工批准步骤。

## 实施影响

现有 StartProjectDelivery、ProjectPreparation/Request、Product/Design Context 和统一 checkpoint
均只有一个 project_root/project_id。应先补统一多目录上游契约，再组合已有单仓 Runtime。
仅将 CLI 参数变成数组并循环调用既有 start，不满足统一产品与设计，不能保证前后端接口一致。
这类批量启动不能当作联合需求交付。

## 验证矩阵

| 场景 | 预期 |
|---|---|
| 一个项目一个目录 | 原调用及交付语义不回归 |
| 一个项目多个仓库目录 | 一条需求/产品确认，多仓执行与候选 |
| 同一仓库两个模块目录 | 一个执行单元，两个允许范围 |
| 一个需求涉及后端与前端项目 | 一份跨项目方案、接口与联合验收 |
| 多个不相邻目录 | 无需共同父目录或业务分组配置 |
| 仅提供参考目录 | 纳入相关上下文，不强制代码变更 |
| 一个目录 prepare 冲突 | 产品阶段前停下并给出人工处理事实 |
| 部分 Task 完成 | 父需求保持未完成，可恢复其他 Task |
| 接口/候选变化 | 下游绑定失效，重新验证而非沿用旧 PASS |

## 回滚与当前状态

实施前基线为 main 的 T034。本轮撤销的是未提交的错误项目组草稿，可以从此前工具记录恢复；
目标业务仓库未改动。四项闭环代码已接通；验证结果记录在 implement.md。尚未提交/合并，
不要使用 destructive reset 回滚整个工作区；需要回退时应先保存本轮 diff，再按文件审查撤回。
联合可视化接线是下一项工作，不属于本任务完成范围；仅记录已接受的四个展示字段。
