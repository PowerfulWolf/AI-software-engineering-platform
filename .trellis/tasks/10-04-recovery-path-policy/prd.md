# 恢复路径身份与 Trellis 硬权限

## 目标

同一 Requirement 中的中断恢复不得按 basename 改写合法新文件路径，也不得将设计中的 Trellis 路径当作 Coder 写权限。新 K1 的旧工作区含 3 个规范改动，须保留完整现场、补丁与失败记录，以明确隔离的恢复计划继续，不能靠新建需求或放宽权限规避。

## 范围与验收

- 新恢复计划保留完整相对路径，不自动产生同名文件重绑定；历史计划可读但与新目标 policy 不一致时拒绝执行。
- WorkspacePolicy 与 typed 写入在执行前拒绝任意层级 `.trellis`（含大小写别名）的写入；生产权限编译剔除明确规范路径，候选提交与 progress 校验拒绝接受包含规范改动的结果。读取仍允许。原生 CLI 的后置检查不冒充 OS 写入排除能力。
- 历史误授权的 Trellis 改动只允许通过专用只读 capture 审计；不能扩大旧读写 allowlist 或绕过显式 deny、路径/符号链接/大小/secret 检查。
- 恢复计划的 `quarantined_paths` 精确绑定所有被隔离的 capture 路径；必须 `coder_reapply`，使用干净新基线。完整补丁不截断，隔离路径不应用，Coder 无其写权限。
- Console 审批明确列出保留但不重用的规范改动与干净重实现模式；继续同一 Requirement，保留已批准上游和独立 QA/Review。
- 仅运行相关 Git/policy/recovery/Console 增量测试、Ruff、mypy；全量交用户。

## 存量数据处置与回滚

旧 d9ab670f…计划、旧 Task、dirty worktree 不变。修复部署后 current-facts 校验拒绝旧目标权限，正式 Continue 生成新计划，精确批准后追加同 Requirement 的 successor Task。完整旧补丁包含规范改动作为审计数据，新 worktree 不复用它们。不直接改库、不退款或重开旧终态。空闲回滚提交并重启即可，所有历史保留。
