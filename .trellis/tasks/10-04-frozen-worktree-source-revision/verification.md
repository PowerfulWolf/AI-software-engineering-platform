# Verification

状态：`incremental_verified`（待平台提交、重启后进行真实 Console Continue）。

已通过：

- `73 passed`：RepositoryProfile、production backend、TeamHost、joint contracts、joint resume；
- `81 passed`：Responses dirty diagnostics、blocker text、web console manager；
- 新增 legacy `unknown` profile 的 `delivery_runtime → _derived_backend` 回归通过；
- Ruff、Mypy（3 个变更源文件）、compileall、`git diff --check` 通过。

真实存量处置：不修改 `.ase`、MySQL 或历史 journal。提交并重启新 Console 后，使用原
`CONTINUE_DELIVERY` 入口重新读取当前 checkpoint；若返回精确 recovery/verification approval，
只批准对应 digest，继续经过 Coder → QA → Reviewer。QA `VERIFICATION_INCONCLUSIVE` 不能当作
PASS，也不能直接把失败 Run 审批成成功。
