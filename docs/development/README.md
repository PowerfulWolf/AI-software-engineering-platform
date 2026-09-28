# 开发与验证

面向开发 ASE 本身的人类工程师和 AI 协作者。先读 [AGENTS.md](../../AGENTS.md)、
[工程规范索引](../../.trellis/spec/index.md)及相关模块；任务记录放在 [.trellis/tasks](../../.trellis/tasks/README.md)。
依赖安装、日常质量门和完整验证入口见[仓库 README](../../README.md#开发与验证)。

| 文档 | 内容 |
|---|---|
| [跨语言交付 E2E](target-project-e2e.md) | fixture 矩阵、执行命令及证据边界 |
| [Runtime 组合参考](runtime.md) | 直接组装和运行 Task runtime 的低层配置 |
| [Git 基线开发说明](requirement-git-baseline.md) | 输入错误映射、历史只读行为和验证矩阵 |
| [控制台交互验证](ui-interactions.md) | 通知、草稿、焦点、真实布局测试 |
| [文档维护约定](documentation.md) | 新文档放哪里、如何命名、迁移与校验链接 |

设计说明见[架构与协议](../architecture/README.md)，未完成工作见[路线与待办](../roadmap/README.md)。
验证命令默认在仓库根目录运行。实际执行结果留在任务记录或带日期的归档中，不能把历史通过
次数当作本次验证结果。返回[文档导航](../README.md)。
