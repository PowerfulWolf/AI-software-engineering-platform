# 实现事实

代码提交 `e7f0d19`，隔离worktree `ase-operation-summary-read`，基线 `1769977`。未写生产主仓/注册源码仓、未操作生产服务或SQL。

- summary_models.py定义严格versioned typed读协议与有界定位字段；summary_projection.py只cache阅读投影并构造稳定scope/page/completeactive。
- store.py新增summary入口与shared-lock completebytes inventory，每miss保持普通replay并复查bytes。旧authority入口保持原行为。
- core.py仅新增store委派；transport.py新增readonly GET、optionalfeature、中文固定错误与ETag；原完整GET保留。
- 四份Schema、spec/read-memory/web-console/index与architecture/contracts同步。
- summary21与相关transport/core/idle/budget/scope总105增量通过，最后summary21重跑通过；strictmypy6、Ruff/check/format、diffcheck通过。未跑全量。
- 私有327/981/28MB镜像coldCPU1.676s；warm50平均CPU0.156s、max0.187s、0fullmodeldecodes；25条response33,802bytes；cache327/452,021bytes；完整Operation/Plan live0、weakrefs释放，RSS无持续增长趋势。此测量不建立长期无泄漏结论。

完整验证命令、独立root审查、存量处置与回滚见 verification.md。前端worker与root负责隔离整合；当前尚未证明生产部署或K1交付。
