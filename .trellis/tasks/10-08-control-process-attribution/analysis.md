# Bug Analysis: 本机调查误判平台维护进程

## 1. Root Cause Category

- E（隐式假设）：把任何 cwd 位于工作区当成活跃访问，把完整命令字符串内 Codex 词当成执行器；维护 CLI 和系统 helper 也命中。
- B（跨层契约）：当前进程辅助调查不是历史停止证明，但错误分类会令合法救援连准备入口都无法通过。
- D（覆盖缺口）：仅证明有原生 exec 时拒绝，缺少维护会话常驻时公开恢复仍可完成的场景。

## 2. Why Fixes Failed

- 关闭一个 Codex 会话后，再启动调查会话仍出现同类进程；通过 kill 调查者只能制造短暂消失。
- 仅补 resume 豁免漏掉目录名和 cwd 误推断；豁免整棵维护进程树则会掩盖它启动的真实写入工具。
- ps 增加 PPID 后用列数兼容旧 fixture 不可靠：带参数的旧命令也能拆成十字段。固定真实查询格式并更新 fixtures，拒绝猜测。

- 独立复核发现的首参数白名单会遗漏 exec 的 e alias 和未知真实 CLI；改为内核可执行身份，未知动作保守阻塞。
- 所有 cwd 豁免会遗漏已 reparent 的旧工具；仅明确 idle shell 例外。Unix exec 不改 PID/birth，因此 classifier drift 需再次核验路径。
- Darwin proc_pidpath 对磁盘上已更新删除的旧 app 返回 ENOENT，但进程仍活着；共享原生 BSDINFO 的 kernel name/start/UID 读取，不能误作停止。

- 第二轮独立复核发现动作词出现在参数里仍会误分类；改为按实际 executable/subcommand/script/module/shell command 位置解释，其他词只作数据。漂移重查必须先撤销旧 coverage，缺新事实不能沿用旧空闲结果。

## 3. Prevention Mechanisms

| Priority | Mechanism | Action | Status |
| --- | --- | --- | --- |
| P0 | Runtime | 分开可执行动作、进程归属和工作区文件引用；不豁免任意后代 | DONE |
| P0 | Tests | 维护控制进程、exec、伪装、真正打开文件、Linux/macOS 边界 | DONE |
| P0 | Public path | 同一真实 scanner 进入生产 Host collector 的本机恢复场景 | DONE |
| P1 | Knowledge | 规范和恢复思考指南明确 cwd/控制会话/历史停止的区别 | DONE |

## 4. Systematic Expansion

当前扫描只辅助 legacy exact 工程确认，不能扩成普通进程列表即自动审批。受控服务停机依赖 own registry 的停止记录，与本调查不同；不改变该契约。

## 5. Knowledge Capture

本任务、legacy-execution-rescue spec/user guide 和 recovery-thinking guide 随修复提交。仓库没有 src/templates/markdown/spec 模板目录，无模板同步对象。
