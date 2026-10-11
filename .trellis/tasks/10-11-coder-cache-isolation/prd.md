# Coder 验证缓存隔离

## 目标与边界

原run7完成native调用后，合法mypy验证在工作区生成22MB ignored缓存，使完整现场inventory
在16MB单文件门拒绝，产物尚未解析即丢失。修复未来执行的缓存归属：受信Python tooling把
mypy默认缓存绑定到本次run-owned外置scratch，不增加源码inventory上限或cache授权豁免。

允许修改agents/codex_cli.py、专用test_coder_cache_isolation.py、Trellis任务包及缓存隔离spec。
不改git/mutation.py、continuation权限分类、Task/队列/预算/schema、QA/Reviewer权限、旧数据。
主仓与原K1工作区只读；Root独立实现后处理失败恢复及存量缓存封存。

## 验收

- 每次Coder tooling运行都有新私有run-owned mypy cache，位于现有sandbox允许写的run root，
  与代码/注册工具根不重叠；环境不能复用host MYPY_CACHE_DIR。
- 原生invocation env及受信Python bootstrap共同绑定该路径；子命令仅收到精简环境时也可正常
  通过受信launcher运行mypy，固定bootstrap补齐路径，不依赖prompt中的建议。
- 实际mypy检查只访问当前源码，不在工作区创建.mypy_cache；可在scratch生成大于16MB缓存
  而原代码inventory仍按16MB/256MB/20k/no-follow稳定hash契约核验。
- 已登记tooling保持只读、当前source绑定/-I -S -B不变；run退出或runner失败清理私有scratch。
- QA/Reviewer不注入本能力。绕开受信launcher或显式重定向缓存不获得工作区写许可，最终门仍拒绝。
- 增量fixture真实子进程测试+既有native Python tooling回归，scoped Ruff/mypy/diff通过。

## 保障范围

此改变机器绑定受信launcher及默认mypy环境；native sandbox允许Coder写源码，因此无法阻止
一个显式使用--cache-dir或绕过launcher的模型另写工作区。原inventory/policy仍fail closed，
不得把这个能力声称为所有命令的OS写前隔离。不给ignored缓存添加永久豁免或增加一般大小上限。

## 存量与回滚

原run7缓存/源码不改，完整事实及Root恢复seam见run7-recovery-seams.md。新代码部署要等空闲后
受控加载；原需求须经过Root新增的exact后处理失败恢复，不靠本改动静默接纳旧产物。
回滚仅恢复本code/tests/spec diff，不删除原日志、workspace或人工审计；全量测试由用户运行。
