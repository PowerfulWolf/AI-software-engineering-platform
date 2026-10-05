# 实施记录

用户授权删除自验证Project及清理/tmp无用内容，业务交付仍暂停。

## 已完成的临时整理

- 清理清单保存在外置maintenance目录，绑定460个历史条目及实际文件身份。
- seed-preflight的完整独立Git已原子迁移，121文件/9217859bytes，移动前后type/mode/content摘要逐项相同；额外保留HEAD、index和cached binary patch。
- Playwright依赖已迁移到 /Users/zhangjunshuai/Library/Caches/ase-validation/node，完整inventory一致，独立Chrome启动验证通过。
- 已删除425个旧ASE普通临时文件，逻辑85498138bytes、占盘86536192bytes，零identity漂移/占用项被删除。
- 临时测试目录待Project增量完成后清理，不碰系统、Codex运行目录或生产服务环境。

## 待完成

Project retirement契约、增量/独立检查、提交推送、空闲更新、生产退休及前后API/页面验证。所有生产记录处置通过typed退休入口，不直接SQL写入、不改旧manifest或Task/verdict；归档保留原Requirement退休事实。

## 增量验证完成

- `.venv/bin/pytest -q tests/manager/test_project_retirement.py tests/manager/test_team_workspace.py tests/contracts/test_project_retirement_schema.py -m 'not mysql'`：79 passed（1.32s）。
- `.venv/bin/pytest -q tests/manager/test_requirement_deletion.py tests/manager/test_requirement_retirement.py tests/contracts/test_json_schema_contracts.py -m 'not mysql'`：124 passed，3 deselected（2.39s）。
- Ruff check、format check及strict Mypy `--follow-imports=silent`对四个变更Python文件通过；`git diff --check`通过。未跑全量/MySQL。
- 独立复核无must-fix；生产maintenance脚本补exact command持久化与重放、显式停机/Operation guard和源仓库前后审计。

## 用户澄清后的范围

用户询问为何清理涉及代码。已说明当前仅补空Project安全退休的底层能力；没有页面删除按钮、通用Project删除或有交付历史的级联删除。后续不扩大项目管理功能。

## 真实初始化目录兼容

首次生产退休被检查拒绝，receipt未发布、archive未创建，已恢复服务且262条Operations保持原样。state/product、state/design、state/planning以及spec-conflicts/project-baseline-compilations由标准store/编译查询初始化为精确空目录。补最小识别：只允许这四个标准、非symlink且完全空的目录，其他文件/未知目录/更深子目录仍拒绝。增量retirement+Schema回归76 passed，真实形状定向10 passed，Ruff/format/strict Mypy通过。失败前置命令审计完整保留在外置maintenance/failed-preflight。
