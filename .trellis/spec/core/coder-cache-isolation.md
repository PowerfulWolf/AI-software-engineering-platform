# Coder 验证缓存隔离

## Scope / Trigger

适用于 `agents/codex_cli.py` 中已登记 Python 工具的原生 Coder 执行。mypy 的默认工作区
缓存不是源码交付物，也不是已批准的 `write_paths`。默认缓存应属于本次执行，不能因其
增长而放宽完整源码 inventory、忽略 Git ignored 文件或扩大 Coder 写权限。

## Signatures / Ownership

```python
_prepare_coder_python_launchers(
    tooling: _NativePythonTooling | None,
    temporary_root: Path,
    *,
    mypy_cache_root: Path,
) -> _NativePythonTooling | None
```

`CodexCliAgentAdapter._execute` 创建两个独立的私有临时目录：允许写入的本次 run root 与
只读的 tooling root。`<run-root>/mypy-cache` 为该次调用独占缓存；注册的 `.venv`、源码
和生成的 tooling bootstrap 都不能作为缓存根。其生命周期与该次 adapter 调用一致。

## Contracts

- 仅当 Coder 获得合法的已登记 Python tooling 时创建缓存，目录权限为 `0700`。
- 原生调用环境的 `MYPY_CACHE_DIR` 精确指向该目录；不继承宿主机的同名变量。
- tooling root 内的固定 bootstrap 在用户命令启动前再次设置该 exact 路径。即使模型工具
  子调用只保留 `PATH` 或提供另一个同名值，通过 `ASE_PROJECT_PYTHON -m mypy` 仍使用本次
  私有缓存；这是执行代码约束，不能只写 prompt 建议。
- 保持 `-I -S -B`、当前源码/直接依赖绑定、禁止 `.pth`/`sitecustomize`、tooling 只读及
  网络关闭不变；不新增一般环境 allowlist。QA 与 Reviewer 没有此 Coder 工具/缓存能力。
- default mypy 缓存位于已有 sandbox 的 writable run root，结束和 runner 失败均清理，
  不跨 Run 复用缓存，也不删除现有工作区缓存。
- `git/mutation.py` 的 16,000,000 字节单文件、256,000,000 字节总量、20,000 文件、
  no-follow 和双稳定 hash 门保持不变；`.mypy_cache` 不加入 `is_execution_cache_path`。
- 这是默认环境及受信 launcher 的缓存归属约束。Coder sandbox 仍允许合法源码写入；
  显式 `--cache-dir`、mypy 配置的 `cache_dir` 或绕过 launcher 可以覆盖 mypy 默认值。
  这些路径不获得额外写授权，最终完整 inventory/policy 仍 fail closed。不能宣称该改动
  能在 OS 层阻止所有工作区缓存写入。
- 未获合法 Python tooling的运行不新增该能力；需要验证而工具缺失时按既有 NOT_RUN 路径报告。

## Validation & Error Matrix

| 输入/现场 | 约束点 | 结果 |
|---|---|---|
| 合法 Coder tooling；实际默认 mypy | 原生环境 + 固定 bootstrap | 缓存只在新私有 run root，源码 inventory 不变 |
| 宿主缓存值或精简子调用环境 | 环境过滤 + bootstrap exact binding | 不复用宿主值；仍使用本次缓存 |
| 第二次独立调用 | TemporaryDirectory 生命周期 | 新目录；前次缓存已清理 |
| runner 无法启动或抛出受控错误 | 临时目录上下文退出 | 删除本次私有缓存/launcher，保留工作区 |
| 外置缓存产生超过 16MB 文件 | 原源码 inventory | 不纳入源码；源码规则不变 |
| 工作区源码或 `.mypy_cache` 超过 16MB | 原源码 inventory | 拒绝；不能按 ignored 路径豁免 |
| QA/Reviewer | role tooling gate | 不设置 Coder cache 或 launcher |
| 显式工作区缓存重定向 | 原最终 inventory/policy | 不获得额外授权；保留拒绝现场 |

## Good / Base / Bad

- Good：受信 Python launcher 用精简环境执行真实 mypy，检查当前源码，缓存落在本次
  外置目录；源码完整 inventory 与执行前相同。
- Base：Python tooling 缺失或不是 Coder，沿用既有角色行为，不注入缓存能力。
- Bad：提高源码文件上限、跳过 ignored 目录、给 `.mypy_cache` 永久写许可，或声称缓存
  隔离证明了旧执行的产物/进程停止/审批。

## Tests Required

`tests/agents/test_coder_cache_isolation.py` 必须验证真实 mypy、精简/不可信子调用环境、
新 Run 目录、成功/失败清理、大缓存不进入源码 inventory、工作区超限拒绝和角色隔离。
同时跑既有 `tests/agents/test_native_python_tooling.py` 增量回归、scoped Ruff/mypy/diff。
不以环境字符串断言替代实际子进程缓存写入测试。

## 存量数据与回滚

本变更不写 DB，不接纳旧 artifact，不删除原缓存，不退款、不造 verdict。既有 run7
缓存已进入原工作区，必须按独立、exact/hash-bound 的工程维护计划保留 bytes 并封存，
再走原 Task 的公开后处理失败恢复路径；本默认隔离不能替代该存量处理或审批。
回滚仅还原代码/测试/spec diff，保留 Requirement、Task、原日志和审计事实。
