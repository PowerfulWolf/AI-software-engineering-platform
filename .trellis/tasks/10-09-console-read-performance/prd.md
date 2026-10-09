# 修复 Console 慢刷新与间歇读取失败

## 目标与范围

基线 `ab5dead`；修复已定位的完整捕获重复敏感信息扫描、空闲派发全历史重放、Team busy/timeout被通用MySQL提示掩盖。只修改控制台读侧及其安全检查的性能，保持Schema、审批、Task/Operation状态和完整历史语义不变。当前目录单Agent实施，仅增量测试。

允许路径：`src/ai_software_engineer/redaction.py`、`team_view/{reader,engineering_history}.py`、`web_console/store.py`、`team_view/app.js`、对应`tests/context`/`tests/team_view`/`tests/web_console`增量测试、相关Trellis规范、诊断及任务记录。前轮未提交的诊断文档属于本轮自身工作，保留并同步。

## 验收

- 相同完整源码/补丁在同一次读作用域内只运行一次昂贵扫描，路径/正文变化隔离；命中含secret的结果仍拒绝。缓存有容量边界，异常/完成后释放，下一次读取重新检查。
- 每次仍验证文件路径、完整bytes/hash、模型、scope、前驱及精确审批；不能跳过篡改检测或接受旧权限。
- 空闲重复claim只复查完整操作历史字节清单，不重复模型解码；外部新增、同大小同mtime篡改、删除、symlink和新待执行操作会触发原完整验证/拒绝。仍在现有跨进程flock内派发，不新增持久化索引或业务事实。
- 当前调用中的baseline bindings复用一次，保留全部timeline。
- Team忙、客户端超时、读取失败给不同安全中文提示；旧数据/阅读状态保持，客户端超时不声称后台执行停止。
- 在同一真实只读数据上验证快照内容一致、SQL只读、性能改善；不启动Host/模型、不重启或接续需求。

## 验证与存量

先增量红例，再修复；相关Python pytest、JS轻量及fixture浏览器、Ruff/format/strict Mypy、diff check。不运行全量测试。无需改库、清理历史或重建需求。受控空闲重启后刷新同一Project生效；回滚本提交并重启恢复原行为，持久化事实不变。
