# ai-software-engineer 项目规范索引

当前 v0.1 只有一个核心规范层：[`core/`](core/)。

## Pre-Development Checklist

- [ ] 阅读 [`core/index.md`](core/index.md) 和适用规范；
- [ ] 确认 Task/Artifact/Agent Schema 是否需要变更；
- [ ] 搜索现有接口、常量和 payload decoder，避免重复定义；
- [ ] 对跨层改动画出 `Task → Context → Agent → Artifact → State` 数据流；
- [ ] 为合法、非法、边界和恢复场景列出测试点。

## Quality Check

- [ ] JSON Schema 可解析且正反 fixture 已更新；
- [ ] 状态机没有跳过 QA/Review 的路径；
- [ ] 权限、worktree、命令和 secret redaction 有测试；
- [ ] 新知识已同步到 `docs/`、`AGENTS.md` 和 `.trellis/spec/`。

## 规范文件

- [`core/architecture.md`](core/architecture.md)：组件边界、签名、错误矩阵和不变量；
- [`core/contracts.md`](core/contracts.md)：角色、权限、artifact、evidence 和验证契约。
- [`core/python-runtime.md`](core/python-runtime.md)：Python 控制平面的类型、端口、adapter 和质量门。
