# 增量验证与原因边界

工作树 `ase-owned-verification-diagnosis`，base `ad898e5f045d0d5ec5befb6b4ba0fd0f01278e8e`。
无生产 HTTP/SQL/Host/model/approval/signal/restart。本任务未修改 owned-session、registry 或
service lifecycle 实现。

## 有效 RED

真实 `HostOwnedProcessRegistry.operation_scope`、`bounded_verification_command`、独立短命
fixture Docker subprocess 和现有 Inspector seam。只在 image 命令的首次 capture 抛
`OwnedSessionUnknown`；其余实际 OS inspector 与真实 kill/reap 路径不替换。

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest tests/manager/test_owned_verification_discovery_diagnosis.py -q --tb=short
```

有效诊断增量：**1 failed, 1 passed / 1.07s**。image capture 未知实际抛出的
`OwnedProcessesUncertain` 被 image 边界误包装成 `VERIFICATION_MYSQL_IMAGE_UNAVAILABLE`。
第二测试证实后两次真实探测成功得到合法 image ID，而 registry 的原 unknown 仍保留，
`shutdown_failed` 为真、`await_stopped(0)` 为假、`require_stopped()` 仍拒绝。
最初 socket 路径过长的 fixture 失败已修，不能当作平台 RED。

该真实离线结果仅证明可发生的代码路径，**未证明生产 PID 802 原始 capture 的实际故障**。
没有用后续 READY、ESRCH 或 active Operation 为空来补造原 birth/SID stop proof。

## 修复及验证

新增领域 detail `VERIFICATION_PROCESS_STATE_UNCONFIRMED`。只有真实
`OwnedProcessesUncertain` 被映射；三个 Docker 命令边界保留 typed 原因。Native verifier →
production preflight → Schema-valid digest receipt → 中文工程等待保持原 detail。
中文明确原探测停止/收尾未核验、查镜像无效、平台补齐执行事实后再复查。

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest tests/manager/test_owned_verification_discovery_diagnosis.py \
  tests/manager/test_python_verification_discovery.py tests/manager/test_native_verification.py \
  tests/manager/test_delivery_preflight.py tests/manager/test_delivery_wait.py -q --tb=short
```

**163 passed / 67.58s**。包括 context/daemon/image 的真实类型传播、普通失败分类和 generic
RuntimeError 不冒充 owned uncertainty、真实 subprocess unknown 保留、后两次成功不能解除
旧 unknown、native revalidation/preflight 透传、schema 精确 parity、receipt tamper 拒绝、中文
提示去重和正确处理方。没有全量测试。

静态格式/中文标点及测试的 platform 显式 import 修正后，重跑受影响的 3 个测试：

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest tests/manager/test_owned_verification_discovery_diagnosis.py \
  tests/manager/test_delivery_wait.py::test_owned_discovery_wait_explains_missing_facts_without_an_image_repair \
  -q --tb=short
```

**3 passed / 1.08s**。Ruff check、Ruff format --check（8 files）、strict Mypy（8 files）及
`git diff --check` 均通过。Schema 枚举搜索只发现一个发布 Schema 需要同步；完整 model/schema
parity 已有可执行增量测试，不新增依赖。

Root 独立 review **PASS，无阻断**：typed 原因完整传播，普通 stage 失败未偷换，unknown
始终拒绝关闭。Root 已授权提交独立分支，本任务不自行合 main 或部署。

## 存量数据处置、风险和回滚

无改库/迁移/历史 rewrite，不改原 Operation、审批、Task、Queue、K1 工作进度或 stop records。
旧误分类记录 bytes/digest 保留，只有修复版本的新观测写新原因。旧服务已有 unknown 不因
磁盘源码更新或新的 READY 自动解除；原故障实例的受控维护另由 Root 负责。

本修复使诊断真实，不制造缺失证明，也不新增批准或恢复能力。对原捕获能力已丢失的实例，
仍可能需要受控维护路线；不能把这次原因修正宣称为已恢复交付。

回滚在受控停止后撤销代码与 Schema；保留已发布新原因 bytes。旧 binary 若不识别新 enum
应拒绝读取，禁止将它改成镜像错误、删除字段或重算历史 digest。
