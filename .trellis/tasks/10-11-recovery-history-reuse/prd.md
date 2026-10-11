# 恢复历史重复读取

## 目标与范围

减少一次原生恢复事实观测内，退休判断和联合需求父子归属对同一完整 journal prefix
的重复读取与深拷贝。事实采集前后仍分别新鲜读取；不改变交付、Schema、状态、审批或 Git 安全核验。
当前生产恢复准备正在进行，本任务不热加载、不重启、不触碰生产 stores。

## 验收

- 真实临时文件上的读取计数先红后绿：一次退休检查每份 numbered JSON 读取一次；
  一次父归属观测的退休检查和父搜索共享一次完整验证，保留每份 JSON 的有界 regular-file preflight。
- 同一 reader 下一次观测仍读取每一历史字节，看到新增 tail/退休记录并拒绝历史篡改、路径异常和归属错误。
- 历史子任务仍不能绕过已删除父需求。共享 typed prefix 只供私有只读消费者，不向外暴露可修改缓存。
- 保持现有双重 Source/Facts 观测、命令和 Git 校验次数；不增加跨请求 prefix 或退休结论缓存。

## 验证

`.venv/bin/pytest -q tests/recovery/test_history_reuse.py`；相关非 MySQL retirement/journal/current/
source-inspection/preparation-inspection 增量；对本次生产源码运行 Ruff/format/mypy 和 `git diff --check`。
不运行全量测试。

## 回滚与存量数据

回滚本次 reader/protocol 即恢复重复读行为。无需 SQL/journal 迁移，所有 Requirement、Task、
Operation、审批和工作区保持不变。部署只由主代理在服务空闲后执行受控维护，本任务不操作 ASE。
