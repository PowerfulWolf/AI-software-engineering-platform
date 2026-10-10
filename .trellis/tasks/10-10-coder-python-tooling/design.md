# 契约与验证设计

## 接口

扩展 Native adapter 既有 Git common-root 只读发现。Coder 使用内部 frozen typed tooling 值，
编译专用 `ASE_PROJECT_PYTEST`、`ASE_PROJECT_PYTHON` 私有启动器和当前工作树源码 import 环境。
只有可信直接解释器与唯一真实 `.venv/lib/python3.N/site-packages` 才提供启动器；不追踪解释器
alias，不解析任何 `.pth` 的外部目录。QA discovery 使用原入口及返回值。工具发现是前提信息，
不授予安装、写入或 verdict 权限。

内部固定 argv 为 `registered_python -I -S -B private_bootstrap.py MODE ...args`。
0700 shell 启动器只 exec 全部正确引用的固定 argv + 字面 `"$@"`，无 eval。解释器不接受模型
提供的 startup flags；模式为 pytest，或支持 -c/-m/当前工作树脚本的 Python。bootstrap 完全
绕过 site/.pth/sitecustomize，先从明确依赖根导入 pytest，再把当前 src/root 放在 source 首位。
`Python -m pytest` 也走同一个依赖导入入口。精确 cwd 必须是当前工作树根目录；不自动改变 cwd。
私有启动器与 0600 bootstrap 在独立 manager-owned TemporaryDirectory 中，runner 执行期间
有效，返回或异常后清理；既有 schema/output 与独立 scratch/cache 使用另一 run directory。
原 TMPDIR 默认可写，0700/0600 对同 UID 模型进程没有隔离作用。

`_coder_tooling_sandbox_arguments(workspace_root, run_root, tooling_root, tooling)` 校验三个
canonical real roots 无重叠，提供完整 `ase_coder_tooling` profile，extends `:read-only`。
只允许当前 worktree 和 run root 写；工具、注册 `.venv` 与根层 `.git/.codex/.agents/.trellis`
只读；network false。采用 `default_permissions` 时不混用 legacy `--sandbox`。安全工具
缺失或非 Python Coder/QA/Reviewer 仍走既有 sandbox 路径。Host TMPDIR/UV cache 不作授权根，
本轮变量绑定 run 下 manager 创建的目录。源码绑定不能只依赖 PYTHONPATH 或 prompt：执行型
.pth 可以覆盖它。不可变启动器也不能只依赖 chmod、prompt 或事后 hash，必须有真实 OS 拒绝。

PEP420 namespace 即使source-first仍可被后续已安装regular包/module覆盖。固定bootstrap在
导入pytest之前安装metadata-only PathFinder guard，不执行业务包来判断：如果同名当前source
的package/module/namespace将由外部具体包/module替代，则在外部初始化前拒绝。已缓存的
支持模块也在用户代码开始前核对。没有当前source冲突的依赖、正常namespace portions保持
可用；拒绝是source-binding前提未就绪，应如实NOT_RUN，而不是业务测试FAIL/PASS或安装授权。

缺失工具不猜测网络修复、不继承 `VIRTUAL_ENV`。Coder 可以继续合法开发，但未运行的验证必须
如实 `NOT_RUN`；若必需验证阻止完成，保留精确 dirty inventory，输出合法 coder-progress 与
非空 remaining steps/next actions，明确请平台准备工具后继续。不存在 `blocked_reason` 的
coder-progress wire 不新增字段，不伪造 PASS。

## 测试矩阵

| 场景 | 断言 |
|---|---|
| 注册现有工具 + linked Coder | exact runner/env/prompt，current cwd |
| src 布局 + editable 注册旧源 | 真实 pytest 与 Python 导入当前 worktree `__file__` |
| flat 布局 | 当前 worktree root 为 import 首选 |
| 执行型pth/_virtualenv.pth/sitecustomize | 实际绕过，两个入口仍导入当前源，不改旧文件 |
| src/flat namespace被外部regular包/module覆盖、nested portion冲突 | 真实Python/pytest在旧初始化前拒绝，sentinel不产生 |
| pytest预加载同名current namespace/regular包、已缓存支持模块 | 工具加载前拒绝冲突；用户代码不能利用sys.modules绕过 |
| compatible namespace portions/普通依赖 | 实际导入current源码、测试可用 |
| 外来 PYTHONPATH/VIRTUAL_ENV/工具变量 | 过滤，仅可信派生值 |
| venv/bin/pytest symlink 或非可执行 | 无绑定，不安装 |
| venv/bin/父目录 symlink | 无绑定，不跨目录发现 |
| 无可信解释器/依赖根symlink/多个runtime目录 | 两个入口均不提供，无fallback安装 |
| 含空格引号路径/命令形态参数 | 参数原样传入，不shell展开 |
| 错cwd/未知flags/外部脚本 | 解释器startup固定，测试/脚本不得开始 |
| runner正常/异常返回 | 运行中启动器有效，返回后临时文件清理 |
| 真实 Native sandbox | 旧 TMPDIR 可写对照；新工具 write/unlink/replace/symlink/rename 全拒绝，当前源码与 scratch可写 |
| 工具缺失、非 Python项目 | 既有执行路径，不生成环境 |
| QA/Reviewer | 原 QA 接口行为及禁用 native commands 不变 |
| ignored .venv 文件写入 | 原 mutation policy 继续拒绝 |

## 质量门与回滚点

先添加可失败的真实 subprocess 和 adapter 测试，再实现。验证运行聚焦测试文件、Ruff、format、
严格 Mypy 与 diffcheck，交由独立 reviewer 审查。回滚仅本任务 allowlist 内代码/知识，不修改存量现场。
