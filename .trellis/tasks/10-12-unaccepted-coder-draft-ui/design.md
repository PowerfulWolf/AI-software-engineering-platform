# 设计与错误矩阵

复用 exact baseline plan/工程PAUSE/独立RESUME，仅按封存原失败派生 ordinary cause。UI不是proof producer：它重验完整操作资源归属、当前Task/work/source/checkpoint、原typed start/stop及proof原因配对，然后调用既有命令。数据库与Git安全判断仍由服务完成。

GOOD：版本7、真实INVALID、零退出/outputPresent/noArtifact、普通新执行预留；同基线无target，不同目标完整规范审阅。
BASE：未知旧报告只提供检查，不猜报告内容；旧WORK版本5保持兼容。
BAD：旧服务/newreason、wrongcause/digest/Run、异Project、已接纳artifact、unknownstop、旧方案native-rule确认，均拒绝写入。

当前completed/source方案按明确validated operation时间选择，旧缺项只属于历史。复制报告和可见用户操作保持同一事实来源，不能用旧调查覆盖当前核验结果。

相关规范：core/web-console.md、execution-baseline.md、completed-coder-output-unavailable.md、unaccepted-coder-draft-ui.md、guides/recovery-thinking.md。
