# Implementation / verification

根因：外层 TMPDIR=scratch 与 Codex :tmpdir=none 解析为同一路径，deny 覆盖 scratch=write。
普通 boundary fixture 没有使用 tmp_path，因此虽然 SQL/socket 测试成功，却漏掉真实 pytest setup。
原候选单节点真实沙箱只去掉 outer TMPDIR 即通过；counterexample 两种 temp 根均复现同错误。

新增固定环境 seam，生产 executor/真实 OS/SQL fixture 复用；可信 runner 进入沙箱后仍设置
TMPDIR=scratch。不改 root/temp deny、源码只读、socket/network、权限/Schema/旧 digest。

## 增量测试

- before-fix OS tmp_path 两根：2 failed，均 setup PermissionError(1)，零执行 test body。
- 原候选单个 wire schema 节点，修正 outer env 的 disposable diagnostic：1 passed；不作原生 verdict。
- after-fix OS trusted env 与冲突反例：4 passed/8.18s，包含源码/secret/publictmp/foreignsocket/TCP拒绝。
- real isolated MySQL + tmp_path + 权限拒绝：1 passed/14.01s。
- runner/capability/admitted execution/Console contract：49 passed/4 explicitly disabled OS skips/9.13s。
  OS 四项已另行显式真实执行通过；未跑全量。
- Ruff、strict Mypy 三个 typed 变更文件、diff check通过。
- 独立 QA 真实 OS4项、权限/receipt/resource 离线27项通过；host-env sentinel 用实际
  SubprocessCommandExecutor 验证不继承宿主TMPDIR/PYTHONPATH/PYTEST_ADDOPTS/API-key。
  独立 Reviewer 只读复核固定env/权限、原错覆盖与旧计划不可重放，无确认finding。
  这些平台工程检查不构成 K1 原生 QA/Review verdict。

## 存量数据处置 / 回滚

保留 9179235e 原审批、43 setup ERROR receipt、独立 QA FAIL（两项真实静态 code finding）与新
task_continue_1de2709cd1496c74b8db84caca0eed4c。原生流程已自动把 finding 路由给 Coder，
不能因修复执行器就覆盖这些 finding。当前 Operation/角色继续运行，不重启打断；空闲激活后
按新 candidate/Task facts 重新提案/精确审批受控增量验证。无需生产 SQL 修改或迁移。
回滚提交并空闲重启；保留全部 Task/审批/资源/receipt，禁止复用消费过的计划。
