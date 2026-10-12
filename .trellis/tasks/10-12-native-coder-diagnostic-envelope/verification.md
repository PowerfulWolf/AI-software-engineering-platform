# 增量验证与存量处置

## Red / green

修复前运行 `PYTHONPATH=src <main>/.venv/bin/python -m pytest -q --tb=line tests/team_view/test_blocker_text.py -k 'coder_output and real_run_envelope'`：11 failed / 46 deselected。

修复后：

- `tests/team_view/test_blocker_text.py`：62 passed / 1.12s，实际 shipped JS parity，含5种非法包装负例。
- `node --test tests/team_view/engineering-wait.test.cjs`：111 passed。
- 两个Python文件 Ruff check / format、strict mypy通过；app.js syntax与diffcheck通过。
- 不运行全量、生产模型或浏览器视觉验收。

## 存量数据处置、风险、回滚

展示层只去掉一层精确native Coder执行包装。无需改库、Schema或历史记录。
原真实 GIT_CONTRACT 子因未保存，不能推断为切片错误或认定完成。
上线必须idle受控停服后加载；现有需求刷新获得准确中文诊断。
回滚提交会恢复笼统原因，须先受控停服；不得删除原执行、草稿或恢复批准。

独立审查与部署事实随后追加。

独立 reviewer 已核对真实 runner 包装和生产 IdFactory UUID；27个最小parity/负例、Ruff、strict mypy、JS syntax与diffcheck通过，0 blocking。
合法自定义下划线/连字符 Run别名仍按历史generic方式展示，当前生产UUID/K1不受影响；本补丁不扩大诊断识别范围。

## 2026-10-12 08:10（UTC+8）实际部署补记

本段追加维护负责人已实际执行并核验的上线事实，保留上文待部署时的记录；本次文档收尾没有操作生产、数据库或模型。

`7ef2425` 已在服务 idle 时通过受控停止取得 `READY`，确认旧实例实际退出后完成 main fast-forward、`uv` locked 依赖同步、推送并启动新实例，PID 为 `4722`。原 K1 的真实 GET Team 返回 HTTP `200`，需求数据已显示“开发报告未通过代码与工作区校验”，本次中文诊断修复已生效。原 `GIT_CONTRACT` 具体校验子因仍未知，没有改写原执行报告、失败或证据。

此前 `ead05e7` 的集成版本也已受控部署并验证 Console contract `7`、readiness HTTP `200`，原操作历史保留且摘要 `503` 消失。registered clean main 已从 `1769977` fast-forward 到 `7ef2425`；原 Requirement 的公开 SOURCE prepare 操作 `operation_d814f022e9e3d59a6e1293592cf5132e` 已观察为 `QUEUED`。精确方案审阅、人工 `PAUSE`、独立 `RESUME` 和 K1 交付均待完成，不能把服务启动或诊断展示正确当作交付完成。
