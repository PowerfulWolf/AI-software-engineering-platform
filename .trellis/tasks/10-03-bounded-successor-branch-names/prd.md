# 限制重复恢复产生的 successor 分支名

## 目标

修复多轮 QA/Review 打回或恢复后，平台递归追加 `recovery`、`review-fixes` 和
`prerequisite-repair`，导致候选分支名不断增长的问题。保留已有分支、Task、审批和
Artifact 历史，并让后续 successor 分支从稳定的业务短名生成。

## 范围

- 只改变新 successor 分支名的确定性生成逻辑。
- 继续保留 feature/bugfix 类型、碰撞检查和显式人工命名覆盖。
- 更新分支命名规范、架构文档和增量回归测试。

## 验收标准

- [ ] 普通 Task 续跑仍复用原分支。
- [ ] 首次 successor 仍生成 `<业务短名>-<purpose>`。
- [ ] 任意连续 successor 后缀被折叠，下一次生成不会继续递归增长。
- [ ] 业务短名、类型、历史分支和审批 digest 不被重写。
- [ ] 旧的无名历史 Task 仍返回 `None`，碰撞仍由调用方 fail closed。
- [ ] 只运行分支命名和受影响的增量检查。

## 技术说明

`successor_branch()` 只折叠平台保留的尾部 purpose 后缀，不截断业务短名，不引入
Task ID、哈希或 attempt 编号；结果仍通过 `BranchName` 校验。现有已创建的长分支不迁移。
