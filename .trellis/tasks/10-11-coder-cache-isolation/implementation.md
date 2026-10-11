# 实现与交付范围

基线 `8d494027bbbc3a97198dc410601fed11f5f9f91d`，独立分支
`task/coder-cache-isolation`；仅修改允许的 adapter、专用tests、任务包和新spec。

- `_execute` 为已获Python tooling的Coder新增私有 `mypy-cache`，native environment绑定。
- `_prepare_coder_python_launchers` 接收keyword-only `mypy_cache_root`，固定bootstrap
  在用户命令前绑定相同路径，不依赖模型prompt或子命令继承环境。
- Coder工具说明明确使用受信Python执行mypy及缓存归属，不赋予工作区缓存额外写许可。
- 真实mypy回归验证当前源码/精简或不可信环境；同时验证新调用缓存、成功/失败清理、
  外置大缓存与原源码inventory的分离、原工作区超限拒绝、QA/Reviewer权限不变。

Root已只读独立审查code/tests/spec，没有阻断。没有部署、重启、调用模型、修改K1worktree、
改DB或操作ASE恢复/审批；实际sandboxprobe仅本地临时fixture，无模型。

## 存量数据处置

本diff不修改存量事实或缓存。原run7的cache22,716,416B、FAILED outcome、completed stop、
28项合法草稿均保持；详见 `run7-recovery-seams.md`。Root须先按独立维护计划完整封存
exact缓存bytes，再用原16MBinventory重新核验原场景，走同Task公开恢复方案与精确审批。
不能用本次默认隔离接纳丢失output、造原成功记录或退款；不新建需求代替原需求。

## 已知限制与回滚

显式 `--cache-dir`、配置 `cache_dir` 或未受信Python可覆盖默认缓存路径；最终机器门
保持拒绝越权/超限，现阶段不声称全面OS缓存写前隔离。每次Run独立缓存不复用前次mypy
增量结果，因此第一次检查可能稍慢；缓存安全归属优先于跨执行复用。

回滚本次adapter/tests/spec/task diff即可；不删除生产sidecar、原缓存、worktree、Task、
日志或HumanAction审计。部署与公开恢复由Root统一完成。
