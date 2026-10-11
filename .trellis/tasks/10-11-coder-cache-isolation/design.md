# Coder mypy 缓存归属设计

## 问题与选择

run7 的 native Coder 已实际返回并保存 completed stop，但完整现场后处理先扫描全部文件，
工作区内新增的 22,716,416B `.mypy_cache/3.12/cache.db` 超过16MB门。该调用尚未解析
原 output 就进入 FAILED/WORK_INTERRUPTED；临时输出随后清理。提高源码上限仍不能合法
接纳 `.mypy_cache`，因为它不属于已批准写路径/明确cache capability。

未来执行改用本次 run root 的私有 `mypy-cache`，原 sandbox 已允许该 run root 写入，
独立只读 tooling root 保存启动代码。原生环境设置缓存路径，固定 Python bootstrap
再次绑定相同路径，精简子调用环境也不会回到工作区默认缓存。

## 执行顺序与接口

`CodexCliAgentAdapter._execute`：

1. 解析合法 Coder 登记 Python tooling，保持当前 source/direct dependency 检查。
2. 创建本次 run root 与独立 tooling root，保持原 machine sandbox profile。
3. 创建 `scratch`/`uv-cache`/`mypy-cache`，均为私有0700。
4. `_prepare_coder_python_launchers(tooling, tooling_root, mypy_cache_root=...)`
   将 exact cache 路径编译进只读 bootstrap。
5. native invocation 设置 `MYPY_CACHE_DIR`；`ASE_PROJECT_PYTHON -m mypy` 启动用户
   命令前覆盖精简环境中的同名值。
6. 调用返回或 runner 失败均按现有 TemporaryDirectory 生命周期清理私有目录。

源码、注册 `.venv` 和 tooling root 均不能成为缓存归属；不新增一般host环境allowlist。
没有合法Python tooling及非Coder角色沿用原流程，无缓存能力。

## 边界与替代方案

- 不采用增加源码inventory阈值、忽略ignored目录或永久授权 `.mypy_cache` 的方案；
  这些会改变完整交付现场的机器权限且不能修复原output未解析丢失。
- 本变更约束默认环境/受信launcher。显式命令/配置 `cache_dir` 或故意绕开launcher
  可覆盖工具默认值；Coder现有native sandbox必须允许合法源码写入，不能宣称所有命令
  的OS写前缓存隔离。最终inventory和policy继续拒绝越权/超限现场。
- 不引入状态、wire Schema、数据库、重试退款或QA/Reviewer能力变更。
- 已存在run7cache由Root单独exact/hash-bound维护封存；未知output与恢复审批也单独处理。

完整可执行契约见 `.trellis/spec/core/coder-cache-isolation.md`。
