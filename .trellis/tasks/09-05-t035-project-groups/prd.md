# T035 单项目与跨项目需求的多目录联合交付

## Goal

一次需求可以在一个项目中完成，也可以修改多个项目；每个项目可以包含一个或多个代码目录。
入口先创建有名称的需求项目，接收一个或多个绝对目录作为改造范围；全部 prepare 后再聊需求。
不要求共同父目录，不要求项目组配置或成员 manifest。
例如后端 hdl-kylin-cloud、hdl-kylin-cloud-api 属于同一业务项目，book-queue-saas 是前端项目，
三个目录既可以分别接需求，也可以参与同一个跨项目需求。

## 2026-09-05 用户纠正

原方案误将目录集合强制组织为 ProjectGroup → LogicalProject → Component，已撤销未提交的
project_groups 模型和存储草稿。本任务目录名仅保留追踪；不代表产品引入强制项目组。

需求 ↔ 项目为多对多；项目 ↔ 代码目录也不能凭文件夹层级推断。平台识别仓库/构建/规范等客观关系，
无法确定的业务归属在必要时澄清，不让用户先配置组织树才能开始。

## Requirements

- 每家公司统一拥有一个外置 sidecar：公司知识、项目知识子模块、需求项目分别收纳；Agent 团队
  仍属于平台组织。公司选择一次，不要求每仓配置 workspace。知识按需加载，冲突交由人工。

- `ase project start PROJECT_ROOT... --requirement TEXT` 接收一个或多个目录，原单目录使用方法兼容。
- 推荐 `ase request create PROJECT_ROOT... --name NAME`，先 prepare，再 discuss/approve。
- 目录可以不相邻，属于同一项目或不同项目。无需 group ID、component ID 或 manifest。
- 全部目录先 prepare，发现 VCS、语言、构建、原生规范和依赖；组织依然拥有 Agent 团队。
- 同仓多个模块目录归并执行，保留用户选择的路径范围；不同仓库独立绑定 base/candidate revision。
- Product 围绕整个需求生成一份统一 ProductSpec 并由用户确认；Designer 设计跨目录/跨项目技术方案，
  明确共享接口、影响范围和联合验证；不能把需求机械复制成多个互不知情的产品流程。
- Planner 按实际修改范围安排每仓执行单元和顺序；参考目录可以只读，不要求每个输入目录产生修改。
- 下游消费明确的上游接口契约、候选与证据；跨项目协作不依赖隐式 Agent 会话或主分支已合并。
- 每仓保留独立 Task/worktree、Coder→QA→Reviewer、权限、规范和证据；整体需求关联多个候选提交。
- 单项目需求和跨项目需求使用统一接单/澄清/批准/状态/恢复接口；部分完成不能标记整体 DONE。
- 单仓验证与跨仓联合验证分别记录；联合验收按需求及项目流程决定，不因多个目录强制新增人工门禁。
- 外置需求 workspace 关联各目录和项目知识，不在目标代码目录写入 AI metadata。

## Acceptance Criteria

- [x] 一个项目一个目录、一个项目多个目录、跨项目多个目录通过同一入口接需求。
- [x] 不相邻目录无需分组配置；同仓多个模块归并且范围外写入拒绝。
- [x] 产品对话与批准为一个完整需求，设计及各执行单元的接口和验收引用可追溯。
- [x] 只读参考目录不强制修改；未受影响的项目不被安排无意义代码任务。
- [x] 部分完成可恢复；候选/接口变化使旧下游验证失效，整体完成需联合证据。
- [x] 重复路径/别名、规范冲突、过期确认、篡改事实有回归测试。
- [x] 单目录入口不回归；Schema、README、规范与本阶段验证记录同步（合并后按 archive 约定归档）。

## Technical approach

上游需求/产品/设计/计划使用 source scopes 集合。下游保留 Task.repository 和 source_revision 的单仓
精确含义，以父需求关联多个 Task/candidate/evidence。多个独立 Git 仓库用候选集合表达。

## Alternatives considered

1. 让现有 Task.repository 变成数组：会破坏 Artifact/source revision、Git 和权限的所有单仓不变量。
2. 统一多目录上游 + 既有单仓执行（采用）：一份需求和产品设计，按仓库拆分执行并汇总验证。
3. 通用 DAG/分布式事务：超出当前需要，暂不引入。

## Boundaries

v0.1 执行 adapter 仍使用 Git；非 Git 目录可被发现，无法执行时明确报告，不自动 git init。
输入目录可以是 Git root 或仓库子目录，由平台归并并保留路径范围。跨仓库不承诺原子提交、自动
merge/deploy；不引入单 Task 复杂 DAG。本任务实现平台能力，不修改用户举例的业务仓库。

## 当前状态

公司归属、需求项目 CLI/Host、原生多仓执行桥接、完整候选集联合验收与中断恢复均已实现，
最终全量 MySQL 回归 698 passed，Ruff/格式/严格类型检查/构建通过，详见 implement.md。
原强制项目组实现不是有效交付。未提交/推送，T033 Reporter 仍暂停，可视化聚合接线另行实施。
