# 实现

本轮修复集中于 legacy_local_execution.py 的入口识别、cwd/文件证据区分和原生执行后代追踪；没有加入控制会话整棵进程树的豁免。

新增回归覆盖 macOS 控制路径、名字含 Codex 的系统 helper、命令文本伪装、维护会话读写原文件、原生 exec/派生工具，以及 Linux 对应边界。公开 Host 本机恢复场景改用真实 scanner 配合固定 OS 查询 facts，验证真实分类可进入准备、核验和同 Task Coder/QA/Review。

仍保持旧调用 UNKNOWN、完整现场、人工 exact 工程声明、剩余预算、新 claim 和独立验收契约。
