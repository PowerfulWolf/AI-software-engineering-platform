# 修复首个 Coder 启动前恢复的 Git 分支与证据边界

## 目标

让首个 Coder 尚未实际调用时的恢复可安全识别真实 Git 分支占用，避免平台把 Git 查询异常误判为分支可用，重复创建已占用分支并再次阻塞。

## 范围

- 恢复分支检查使用目标代码仓库根目录，而不是 sidecar。
- Git 分支查询验证仓库并区分“分支不存在”和 Git/仓库错误。
- 恢复继续使用当前 successor dispatch 校验 preparation digest，不通过临时开关放宽审批链。
- queue admission、role step、accepted role artifact、活动 lease 和执行锁必须形成首个 Coder 启动前的窄证明。
- 更新中文阻塞/恢复规范和增量契约测试。

## 验收标准

- [ ] 已占用的稳定 recovery 分支选择 `recovery-2`，且不会生成递归分支名。
- [ ] 非 Git sidecar 或 Git 查询异常不能被当成“分支不存在”。
- [ ] 活动 lease、额外 queue 记录、非 plan artifact、Coder model route 或保留 worktree 会阻止恢复。
- [ ] 首个 Coder 之前产生的合法 plan/context/admission 仍可在精确批准后继续。
- [ ] preparation digest 校验始终使用当前 dispatch，禁止绕过上游批准链。
- [ ] 增量测试、Ruff、mypy 和 diff 检查通过；规范记录 queue STARTED、context 编译、模型调用和 worktree 创建是不同事实。

## 存量数据处置

不修改生产事实。已过期 claim 通过正常 queue reaper 追加 `LEASE_EXPIRED` 并进入重试调度；已有阻塞 Task、恢复计划、分支和 worktree 保持不变。修复推送并重启后，针对最新精确 checkpoint 重新生成并审批恢复计划。

## 回滚

回退本次平台提交并重启 Console；不删除任何 sidecar 恢复记录或代码工作区。
