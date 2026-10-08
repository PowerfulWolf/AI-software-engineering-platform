# 设计

数据流：固定 ps/lsof 或 /proc → 内存进程身份/归属 → typed LegacyLocalExecutionSurvey → ProductionBaselineFactCollector.require_idle → Console READY/WAITING → 独立工程确认 → 同 Task 新 claim。

1. ps 查询显式增加 PPID，解析严格对应十字段（命令尾部保留完整），fixtures 同步真实格式。
2. Codex CLI 识别使用 OS kernel executable basename；目录里的 Codex 词不算入口，未知真实 CLI 动作也保守阻塞。直接 standalone resume/控制服务只排除全账户原生执行判定。
3. 原生执行树用于 cwd 归属；不把维护进程的祖先或任意后代加入文件豁免。原工作区内真实打开的文件继续阻塞；只排除正在进行调查的进程自身。
4. 仅明确空闲 shell cwd 不阻塞；未知工具、孤儿进程和交互控制会话在原 Coder checkout 的 cwd 仍阻塞。同 PID/birth 的 command/exe/PPID drift 会重查路径。不能以一次进程快照证明所有旧派生进程历史停止，仍需要 exact 工程声明。
5. wire/Schema/数据库和 survey 边界不改变，本次为 v1 scanner 的误分类修正。存量计划/记录不重写。

## 边界

- 进程查询失败、截断、未知状态、覆盖遗漏或 PID 复用：WAITING，不生成计划/审批/新调用。
- 命令中夹带控制名字、真实 exec 的父进程是维护会话：继续阻塞。
- 维护会话在另一 checkout：可以准备；它正在打开原恢复 checkout 的文件或交互 cwd 就在原 checkout：等待工具停止。
