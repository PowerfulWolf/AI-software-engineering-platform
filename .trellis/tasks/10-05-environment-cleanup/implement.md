# 实施记录

用户授权删除自验证Project及清理/tmp无用内容，业务交付仍暂停。

## 已完成的临时整理

- 清理清单保存在外置maintenance目录，绑定460个历史条目及实际文件身份。
- seed-preflight的完整独立Git已原子迁移，121文件/9217859bytes，移动前后type/mode/content摘要逐项相同；额外保留HEAD、index和cached binary patch。
- Playwright依赖已迁移到 /Users/zhangjunshuai/Library/Caches/ase-validation/node，完整inventory一致，独立Chrome启动验证通过。
- 已删除425个旧ASE普通临时文件，逻辑85498138bytes、占盘86536192bytes，零identity漂移/占用项被删除。
- 临时测试目录待Project增量完成后清理，不碰系统、Codex运行目录或生产服务环境。

## 存量数据处置与最终结果

已通过精确、typed空Project退休入口删除 project_ase_self_validation_20260929。Team永久receipt先发布，原sidecar整体移入project-archives；58个inventory条目（30文件）的type/mode/byte SHA前后完全相同。原Project/Repository manifests、已删除K1的Requirement journal和tombstone保持原字节；旧ID已永久拒绝打开。未写SQL、未改Task/verdict/审批，删除操作前后源码Git HEAD/status/worktree一致。

重启后API和完整刷新页面均仅显示ai-project、app-cloud、codex。其他三Project的完整需求/Task/候选/角色历史事实与清理前snapshot一致（仅排除as_of和Project catalog列表）；262条Operations逐字结构相同、零QUEUED/RUNNING。未创建需求、未恢复业务交付、未调用ASE生产模型。

## 增量验证完成

- `.venv/bin/pytest -q tests/manager/test_project_retirement.py tests/manager/test_team_workspace.py tests/contracts/test_project_retirement_schema.py -m 'not mysql'`：79 passed（1.32s）。
- `.venv/bin/pytest -q tests/manager/test_requirement_deletion.py tests/manager/test_requirement_retirement.py tests/contracts/test_json_schema_contracts.py -m 'not mysql'`：124 passed，3 deselected（2.39s）。
- Ruff check、format check及strict Mypy `--follow-imports=silent`对四个变更Python文件通过；`git diff --check`通过。未跑全量/MySQL。
- 独立复核无must-fix；生产maintenance脚本补exact command持久化与重放、显式停机/Operation guard和源仓库前后审计。

## 用户澄清后的范围

用户询问为何清理涉及代码。已说明当前仅补空Project安全退休的底层能力；没有页面删除按钮、通用Project删除或有交付历史的级联删除。后续不扩大项目管理功能。

## 真实初始化目录兼容

首次生产退休被检查拒绝，receipt未发布、archive未创建，已恢复服务且262条Operations保持原样。state/product、state/design、state/planning以及spec-conflicts/project-baseline-compilations由标准store/编译查询初始化为精确空目录。补最小识别：只允许这四个标准、非symlink且完全空的目录，其他文件/未知目录/更深子目录仍拒绝。增量retirement+Schema回归76 passed，真实形状定向10 passed，Ruff/format/strict Mypy通过。失败前置命令审计完整保留在外置maintenance/failed-preflight。

## 清理与页面验收

- 425个旧普通文件、31个旧测试/缓存目录、2份已有持久副本的临时审计JSON全部移除，共458个原计划顶层/tmp条目。清理内容415,518,235 bytes（约396 MiB）；旧普通文件及目录测得原占盘540,409,856 bytes，未将测得占盘等同APFS实际空闲空间增量。
- 完成后的增量验证scratch另清理：/tmp/ase-project-retirement-check-20261005及两个本轮pytest系统临时目录。/tmp旧ASE相关顶层条目为零；系统、Codex及不明用途文件保留。
- 23条已不存在路径的Git worktree登记已prune；实际存在的worktree/branch refs未删。
- 唯一未提交Git测试现场整体保留在外置maintenance/preserved；稳定Playwright缓存位于Library/Caches/ase-validation/node，不再依赖/tmp。
- 真实Chrome页面完整刷新后3个Project正确。拦截所有非GET/HEAD/OPTIONS请求，实际零写请求、零pageerror、零API错误；已目视检查Project选择菜单截图。

## 已知边界与回滚

仅提供pre-execution空Project底层退休能力，没有页面删除按钮、一般Project删除或工程历史级联删除。已打开旧Project页面需完整刷新；当前team读取接口对旧ID沿用TEAM_UNAVAILABLE/503，未扩展通用错误/选择回退UI。活动页面和其余Project读取均正常。

缓存可重建，唯一草稿有完整归档。永久退休不通过删receipt/改旧manifest恢复；若平台版本需要回退，保留退休reader/身份保护并优先向前修复。审计目录为/Users/zhangjunshuai/workspace/code/.ase/maintenance/environment-cleanup-20261005，Project原数据归档为同platform根下project-archives/project_ase_self_validation_20260929。上述外置事实未进入Git。
