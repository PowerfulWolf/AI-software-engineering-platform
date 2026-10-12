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
