# Native Coder 的只读 Python 工具绑定

## 问题与目标

注册仓库已有可用 Python 测试工具，但隔离 Coder 工作树没有 `.venv`。当前只有 QA 能发现
注册仓库工具。Coder 因此重新创建环境，导致未授权、被忽略的环境文件进入完整变更现场；
随后无法封存合法进度。应在调用 Coder 前提供已准备的只读工具，并明确测试源码属于当前工作树。

## 范围

- Native `CodexCliAgentAdapter` 的 Coder 工具发现、精确环境和 prompt。
- 注册 Git common-root 下现有的 project-local 工具；不安装依赖、不创建环境、不联网准备。
- Python `src` 和 flat 布局的当前工作树 import 绑定，以及 Host 环境污染拒绝。
- QA 原有行为、非 Python 项目、完整 inventory 与角色权限保持原契约。

## 验收

- 真实 linked worktree 中，现有注册测试工具经专用环境变量传入 Coder。
- 真实子进程导入的 `__file__` 属于当前工作树，不是注册 checkout 的 editable 旧源码。
- 不传入 Host `PYTHONPATH`、`VIRTUAL_ENV` 或未验证的工具变量。
- 工具/父目录不安全、工具缺失时不绑定、不安装；prompt 说明工程前提和合法 checkpoint。
- Coder 不在工作树创建、复制、安装或同步 `.venv`，也不修改注册工具环境。
- 工具与运行 scratch 分离；真实 Native sandbox 拒绝同 UID Coder 改写、替换或移除固定工具，
  当前合法源码和 scratch 仍可写。不把 chmod 或模型承诺当作隔离。
- `.venv` ignored mutation 仍被完整 inventory 拒绝；不扩大缓存或写权限。
- 只运行受影响增量测试，不执行 ASE 操作、重启、改库、工作区清理或提交。

## 存量与回滚

本补丁不改 Schema、数据库、Task 或历史 receipt。已有非法环境文件不能因新工具绑定获得批准；
由原恢复流程在保留完整现场后另行处理。本任务只修未来执行前提。代码回滚撤销工具绑定，
仍保留原停止、失败和草稿记录；旧记录无需迁移。
