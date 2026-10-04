# 修复后重新创建 K1 的准备边界

目标：用户决定关闭旧 K1、基于修复后的 main 新建同样需求。51 份规范约 1.13 MB，旧 1M 字符 aggregate 导致新 Create Operation 失败，留下 PREPARING journal。

范围：冻结数据存储采用独立有界 UTF-8 字节上限，保持完整原始规则、单文件上限、URI/hash、安全路径和模型 token 上限；明确超限异常并封存 BLOCKED，使 UI 不停留 PREPARING。信号退出优先按中断诊断，不能从 stderr 里的认证词推断认证失败。

验收：约 1.3 MB 的完整规则冻结成功，模型仍读取引用与验证 passage；超过 4 MB 拒绝且可关闭，模型调用为 0；合法单文件上限保持 256 KB；SIGTERM 后 dirty 保留、无 artifact、不可自动重试、中文准确。

允许路径：multi_directory/production.py、errors.py、service.py，agents/codex_cli.py、team_view/blocker_text.py，对应增量测试和规范、本任务文档。不改持久 Schema、数据库或 QA/Review verdict。

验证：相关准备/retirement、Codex dirty failure 和中文回归；Ruff、源 mypy、diff check。只跑增量。

存量处置：旧 K1 已以 Close Operation 追加 CLOSED；取消动作只向精确父进程、工作区匹配的旧 Codex/Codex Code 子进程发送 SIGTERM，未杀 Host、未删除改动，平台封存 Run/Task 失败。失败的新建 journal 先通过同一 typed Create 在未移动的基线完成准备，再正式删除未批准草稿；随后目标 clone ff 到最新修复，新建重新交付。不改旧 sealed failure code。
