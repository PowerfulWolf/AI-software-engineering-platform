# 有界 pytest 诊断

目标：32 个精确测试节点及参数化失败不得仅因 pytest 常规输出超过4096字节而失去全部诊断。保持既有秘密截断保护、权限、SQL隔离、预算和verdict边界。

允许路径：manager/python_verification_runner.py、tests/manager/test_python_verification_runner.py、verification-environment.md 与此任务目录。固定 quiet/no traceback/no summary/no capture/no color/log_cli=false；trusted guard 封存所有批准selector的计数，并提供最多16项索引、阶段、白名单异常类别及数字errno/SQL错误码。禁止任意异常文字、paths、argv、node参数和credentials进入汇总。JSON最多3000字节；超限原输出仍整流清空。

验收：200个参数化失败输出低于4096且状态全部可见；setup skip、setup/teardown错误、collection错误和未知异常分类正确；秘密长异常没有全文或前缀泄露；不把汇总当QA verdict。只跑runner/执行输出的增量回归。

存量：不改旧已消费回执或QA finding，不能恢复已经清空的输出。新runner hash需新精确计划/审批；原生QA发现的业务缺陷继续由ASE Coder修复。回滚此提交，保留旧事实，重提案。
