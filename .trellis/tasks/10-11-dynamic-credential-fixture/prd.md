# 动态安全测试凭证的进度封存

## 目标与范围

修复 Python source scanner 对 `secrets.token_urlsafe(32)` 动态生成后用于
`f"token={credential}"` 的安全负向测试误判。K1 run8 已停止，但全量合法草稿因
4 处插值被错误识别为固定凭证而无法封存。保留负向测试、原始源文件和旧运行事实。

允许路径：redaction.py、context source detector 测试、Git mutation capture 测试、
相关规范和此任务目录。无数据库/HTTP/角色权限/Schema 变化。

## 验收

- [ ] 完整 Python 文件内可证明的直接动态构造与精确插值可无损封存。
- [ ] 参数、常量、闭包、别名、重绑、控制流绑定、动态反射及格式转换仍拒绝。
- [ ] 只豁免精确赋值匹配；同字符串的固定凭证和强 key/Bearer/PEM 仍拒绝。
- [ ] generic 文本/日志/URI 检测、非 Python 与缺少完整证明的 patch 保持拒绝。
- [ ] real Git capture/wire/revalidation 不修改文件、index、HEAD。
- [ ] 对原 K1 完整现场做只读 capture 验证，不改写原 outcome 或补造报告。

## 验证与回滚

运行 source detector、generic scope、Git mutation capture 增量测试；Ruff 和 strict
mypy。回滚此提交恢复保守拒绝；已封存的动态源码读取也依赖兼容 detector，不能回滚
后删除无法读取的记录。原 K1 保留原 Task/分支，通过受控公开中断处理继续，不直接改库。
