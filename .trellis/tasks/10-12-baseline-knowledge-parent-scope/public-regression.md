# 联合父需求知识准备与基线恢复的公开入口回归

## 目标与范围

仅新增 `tests/manager/test_baseline_knowledge_parent_scope.py`，复用既有离线 provider 与真实执行观察 fixture，不修改生产源码、数据库记录或现有 fixture。真实 MySQL 测试库由 root 协调独占窗口；不调用实际模型、不操作生产需求。

## 可执行验收

1. 通过 `TeamHost.requirement_entry().create → reply → approve` 创建实际单仓联合需求，得到真实 ProductSpec、精确用户审批、Designer 与 Planner 产物及 native child；验证各上游 hash 关联。该小范围文本仓库走生产已有的确定性快速 Planner 路径，仍校验持久化联合计划与真实 Designer 产物的 hash 绑定。
2. 第一次 Coder 的知识准备从实际获批 `joint://` ContextSource 解析 parent Requirement，冻结知识 snapshot，并通过真实 journal、claim、HTTP observation seam 记录一次返回 503 的提供方失败。不能改成 Task/native child 作用域以规避缺陷。
3. 同一 Task 的下一次真实 claim 完成知识准备，但最终模型输入因容量暂停；此时没有主 Coder 调用或活跃租约。
4. 提交实际 Git 基线变更，通过同一个 parent 的公开 PROPOSE、精确 PAUSE、单独 RESUME；quiescence proof 必须同时包含原知识失败与容量暂停，并精确匹配历史 claim/outcome SHA。
5. 暂停期间 Task、状态事件与冻结预算保持不变；恢复后同 Task、同 native child、同 branch，经各自独立 Agent 的 Coder、QA、Reviewer 串行完成，到同一 parent DONE。QA/Review fixture 实际运行受控 `git show` 检查候选文件并持久化 Evidence。
6. 保留既有 retry failure、知识日志字节和状态事件前缀；原主 checkout 没有业务修改，无活跃 Lease。

## 验证命令

```sh
PYTHONPATH=src .venv/bin/python -m pytest tests/manager/test_baseline_knowledge_parent_scope.py -q --tb=short
.venv/bin/ruff check tests/manager/test_baseline_knowledge_parent_scope.py
.venv/bin/ruff format --check tests/manager/test_baseline_knowledge_parent_scope.py
MYPYPATH=src .venv/bin/mypy --follow-imports=silent tests/manager/test_baseline_knowledge_parent_scope.py
git diff --check
```

全量测试不在本次范围。2026-10-12 在 root 授权的隔离测试库独占窗口运行：**1 PASS，54.40 秒**，未跳过。Ruff 检查、格式检查、Mypy 本文件与 `git diff --check` 均通过。早期 fixture 调整只修正预期：容量等待保留父交付 `DELIVERING`、快速 Planner 无模型调用、同作用域 lane 内需精确筛选失败 invocation；这些不是平台缺陷。

## 存量数据处置与回滚

该测试只操作隔离测试库与临时 Git 仓库；生产存量处置由任务主作者与 root 负责。回滚此测试及说明文件不影响生产事实，也不删除历史运行。
