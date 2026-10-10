# 验证与存量处置

真实Git的runtime-token-generation回归先失败于capture plain redaction，另3个secret拒绝用例
通过。Git capture与CapturedChanges改为复用patch_secret_occurrences后，4条全绿。
Git capture/model/workspace绑定组合72条通过；独立审查追加source detector组合149条通过。
限定Ruff/format/strict Mypy及diffcheck通过。

生产原K1以正式source reader和Git API只读复核：27文件patch可完整capture，没有改index、
HEAD、原Task、数据库或工作区文件。后续公开精确恢复仍需当前目标基线与完整scene证明。
无需迁移或补写旧数据；旧失败记录保持。未运行全量测试。
