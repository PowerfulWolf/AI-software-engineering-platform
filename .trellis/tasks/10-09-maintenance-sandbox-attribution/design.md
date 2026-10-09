# 设计：核实工具来源，只调整账户级分类

## 契约

TrustedLegacyLocalExecutionObserver 保持现有 observe(worktree_root, boot) 和 wire。
新增内部固定 OS `_executable_path(pid)`：macOS proc_pidpath；Linux 不获得新路线分类。只用于正向
身份核验，不读取环境、不发信号。不支持、ENOENT、路径未知时不获得维护豁免；不能推断退出。

在第一次与第二次清单分别核实固定五级链。五级中的 PID/PPID/birth/command/kernel name
和真实 OS 路径必须一致、存活且均有 fresh cwd/file coverage。仅短暂 R/S/I 状态变化无需
冒充进程换身份；zombie/stopped/unknown 不获豁免。超过固定层数、缺祖先、环或 reparent 拒绝。

正向身份固定来自已核实安装位置 `/Applications/ChatGPT.app` 的精确真实可执行路径；
不能从被调查进程自己提供的路径推导受信 bundle，迁址/其他平台暂不授予来源分类：
Contents/MacOS/ChatGPT；Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex；
Contents/Resources/cua_node/bin/node_repl 与 node。node 的真实脚本参数必须为同 bundle 下
Contents/Resources/cua_node/lib/node_modules/@oai/cua-repl/bin/cua-repl.mjs，无额外未知参数；
codex 根必须实际动作 app-server，sandbox 子必须实际动作 sandbox，sandbox payload 的
`--` 后执行器必须是同 bundle node。临时 kernel.js/trusted-worker.js 不作为信任根。

归属分类只在扫描完整后影响最后 CODEX_WRAPPER_ACTIVE 聚合；ignored_pids 仍仅 observer。
before/after 的所有旧分类和真实 exec/e 阻塞仍保留。每个进程的路径检查及漂移重查不被跳过。
载荷参数中绝对路径或显式工作目录（含 --arg=PATH）指向原 checkout 时也不给来源豁免。
不能因为已核实桌面工具而自动补造旧停止证明或工程审批。

## 校验矩阵

| 输入 | 结果 |
| --- | --- |
| Good：精确 bundle CUA 链，另一个 checkout，稳定且完整路径检查 | 无 wrapper 假阻塞 |
| Base：同链打开/位于原工作区，包括子工具 | WORKTREE_PROCESS_ACTIVE |
| Bad：任意 sandbox、伪 title/path/script、缺链、孤儿、exec/e、链漂移 | 保持原 wrapper/execution 拒绝 |
| 正向 native path 查询失败，普通进程覆盖完整 | 不获豁免，不假称退出 |
| 原路径检查不完整、身份重用、deadline/截断 | PROCESS_SCAN_INCOMPLETE，无方案 |

## 存量数据处置

不改库、不重写调查/Operation/UNKNOWN。原 K1 仍通过用户在原需求页面重新检查、准备精确
方案和实际停止声明后自行批准继续；平台修复只消除当前错误前提，不代用户审批。
只读验证比较完整原工作树、HEAD、branch 和 index，禁止创建生产方案、启动 Coder 或重启服务。
