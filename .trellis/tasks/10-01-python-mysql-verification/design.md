# 受控候选 Python/MySQL 验证设计

## 入口与最小范围

只扩展已有 terminal candidate verification，不给 dirty Coder progress 授权。Console Continue新增可选`python_mysql_tests: tuple[PytestSelection, ...]`，每项为精确node ID和criterion IDs；经原生Resume生成新candidate-bound计划，用户精确批准plan后QA/Reviewer分别执行。旧字段缺省None，不改变历史digest。复用VerificationEvidenceProvider及receipt prompt，不开启Agent shell。

## Capability / signatures

- `PythonMysqlSandboxCapability(kind='codex_sandbox_pytest_mysql_v1', sandbox executable/hash, Python executable/hash/venv, trusted runner/hash, Docker executable/hash, local mysql image SHA, selections, max_cases=256)`。
- `discover_python_mysql_capability(repository_root, candidate_revision, selections, codex_executable)`只读检查工具链、candidate内选中测试路径、已有本地image；不pull或启动容器。
- `python_mysql_sandbox_command(capability, source, scratch)`生成唯一固定argv；不接受模型flags或任意命令。
- `BoundPythonMysqlVerificationEvidence.evidence_for(request, workspace_root, guard)`复用已批准plan→invocation→STARTED/final receipt，QA与Reviewer独立执行。
- `VerificationExecutionRecord.capability`使用tagged union，Python结果为固定一个pytest命令；native_ui严格只允许Swift。store按capability重算argv，历史Swift两命令规则保留。

## 隔离资源与网络

当前宿主ASE_TEST_MYSQL_DSN拥有业务库权限，禁止传入候选。每role在审批后建立独占、短寿命、受资源限制的MySQL容器，绑定本机Unix Docker daemon身份与已缓存image完整SHA，忽略ambient Docker环境/context，固定`--pull=never --network none`，不发布端口、不挂宿主源码/数据/socket、不修改现有MySQL。固定测试库+专用principal，随机密码仅通过stdin/内存/0600临时文件，可信前置检查校验真实CURRENT_USER和grants。

可信Unix socket代理通过固定`docker exec -i <exact owned container> /usr/bin/bash -c <versioned relay>`，桥接容器内部127.0.0.1:3306。镜像内已确认bash/timeout/mysql可用，无需安装或拉取。该方案先以独立fixture验证双向协议和退出收敛，不把探测成功当成生产能力。

Codex sandbox保持network=false，仅`--allow-unix-socket`批准精确socket。socket在独立executor-owned目录，候选无目录写权限，不能unlink/rebind；tmp/cache另用scratch。可信pytest wrapper仅将本次专用DSN的PyMySQL连接转为该socket，其它目标拒绝。OS sandbox独立阻止原生socket/Connection绕过及symlink指向其它socket。receipt声明此适配只验证真实MySQL SQL行为，不证明TCP/DNS/TLS/网络超时语义；相关传输测试不得纳入。

创建前持久化STARTED及唯一resource intent（name/owner/plan/run/role/image/daemon/deadline），创建后封存真实container ID和配置。正常退出立即精确清理；`--rm`及容器内固定timeout提供独立寿命上限，控制进程死亡不允许无限驻留。重启按精确intent+实际ID/labels/config复核收敛，不能按前缀/标签批量删除，不能重放测试。覆盖create成功但落盘失败、失租约/进程退出、cleanup失败后重启。

## 文件、导入与输出

filesystem使用`:root=none`、`:minimal=read`和显式只读工具链、注册venv依赖、候选、可信runner；只写role私有scratch。Python使用解析后的真实解释器、`-I -S -B`，可信runner显式插入candidate/src与candidate、依赖site-packages，禁止执行venv的editable `.pth`，禁宿主PYTEST_ADDOPTS/插件auto-load。`-B`只禁止写入bytecode，已有可加载`.pyc`必须纳入runtime/dependency完整tree fingerprint；目录读取失败不得静默漏算。runner校验实际pytest collection与批准selectors并限量；没有收集、跳过/环境错误不可被描述成PASS。

Secret永不进入argv、plan、receipt、Operation或prompt。输出先替换本次已知秘密再做URI credential脱敏，最终限长封存。stdout是非可信观察，模型独立判断所有criterion，不从命令0退出伪造verdict。

## 验证矩阵

| 情形 | 行为 |
|---|---|
| candidate/node IDs/toolchain/image变化 | 执行前拒绝，重新提案 |
| 未批准/错role/旧invocation/STARTED无final | 拒绝，不重放 |
| 合法精确pytest节点+独立MySQL | 执行固定命令，封存真实结果 |
| 非测试库/跨库或全局grants | 执行前拒绝 |
| 外网/其他TCP端口/其它Unix socket/宿主secret读写/源码写 | OS sandbox真实拒绝 |
| 测试失败/跳过/空collection/超时 | 保留失败事实，由QA/Review判断；不PASS替代 |
| cleanup/owner检查失败 | 保留receipt与资源身份，禁止清理其它资源 |

## 增量验证与存量

单元/Schema/假适配器→真实mac sandbox拒绝→独立临时MySQL fixture→现有Swift兼容增量测试。当前业务运行不重启；有精确candidate后安全重载服务，提案并批准新验证计划。保留全部旧Task/approval/verdict/history。

## 已完成的设计探测（不是生产验收）

- 2026-10-01 `/tmp/ase-python-sandbox-probe.py`：`:root=none`须配合`:minimal=read`，并使用真实解释器路径；仅根none与/usr read会因缺少运行时读权限失败。
- 实际探测成功：候选只读可读、scratch可写、源文件写入/隐藏fixture读取/socket unlink/本机TCP连接均被拒绝；精确批准Unix socket连接成功。
- 参考官方权限文档 https://developers.openai.com/codex/permissions ，本机版本仍接受`none`；不得只凭文档假定真实OS隔离生效。
- 独立Reviewer指出socket替换、容器自身网络和进程崩溃资源泄漏三项高风险，已纳入上面的契约；尚需完整实现及独立增量验证。

## 已收敛的最小capability字段

`PytestSelection(node_id, criterion_ids)`只接受tests下精确test函数/类方法，可选有界参数化标识；1..32个selector，每个1..50个criterion，最多收集256项。`PythonMysqlSandboxCapability`绑定sandbox/Python/Docker binary路径与SHA、Python runtime root、dependency root及tree SHA、runner文件与SHA、精确Docker Unix socket/daemon ID、mysql image完整SHA、selections、固定1200秒资源寿命、明确Unix-proxy transport类型。

`python_mysql_sandbox_command(capability, source, scratch, private)`为纯argv编码。source/scratch/private互不重叠，scratch不能覆盖任何可信只读目录。private内connection.json只读，mysql.sock只授予精确连接；Docker socket不进入子进程权限。解释器`-I -S -B`禁ambient import/.pth与bytecode写入；trusted runner只接受固定参数。

Discovery还绑定`python_runtime_sha256`。runtime/dependency fingerprint只允许直接指向同注册树内regular file的符号链接，并同时绑定链接文本和规范目标相对路径；不接受外部跳转后返回树内的链接链。Git discovery设置`GIT_NO_LAZY_FETCH=1`与空`GIT_ALLOW_PROTOCOL`，缺少对象即拒绝，不隐式联网或拉取对象。

容器启动时可使用network-none环境内的临时空root初始化，但**在建立任何候选可达proxy之前必须轮换root为不传入候选的随机secret**，否则候选可以绕过PyMySQL wrapper自行以root登录。专用测试principal只获单测试库权限，root登录失败及跨库/全局权限拒绝必须真实测试。Docker CLI固定本机--host和私有空--config，忽略ambient context/credentials。初版设计probe只有可信SQL，没有候选执行；它不是上述全部边界的验收证明。
