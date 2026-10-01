# 实施记录

- 独立QA和Reviewer已确认缺口及复用seam；现有测试DSN principal并非最小权限，不能复用。
- 本机已有Docker与mysql:8.0镜像，可用本地隔离资源，无需拉取依赖。
- Codex sandbox --help确认支持--allow-unix-socket；最初/usr/bin/true probe只验证单一路径none，不能推断根默认拒绝可用。后续真实Python probe用`:root=none` + `:minimal=read` + 显式读取真实解释器路径，验证source write、secret fixture read、socket unlink、TCP均拒绝，而批准socket连接成功。
- 设计待独立只读复核后实施；业务Coder当前attempt2保持执行。
- 独立Reviewer已完成初审，要求socket独立不可写目录、容器本身网络隔离、崩溃后资源收敛。设计已改为network none + 固定exec relay，生命周期intent/receipt和独立timeout；还没有生产实现。
- 06:03Z业务attempt2成功封存progress并自动进入attempt3；44项相关Python测试通过，fixture范围及MySQL前提仍待解决。实际Chrome14:04显示实现中、Manager处理中、阻塞中0，旧英文建议未展示。
- 06:25Z `/tmp/ase-mysql-relay-probe.py`实际fixture验证：独立mysql完整SHA、network none、0端口发布，固定docker exec/bash relay成功执行真实CREATE/INSERT/SELECT及最小db grants检查；单连接约0.04s。容器有独立150秒timeout，完成后按精确CID+owner标签清理成功。此为设计探测，不是候选QA evidence。
- 更窄真实sandbox profile只保留:root=none、:minimal=read、注册Python runtime/venv/source read及scratch write，去掉额外/usr /System /Library广泛读。仍通过；新增proxy目录rebind和scratch symlink指向未批准Unix socket均拒绝，批准socket连接成功。
- 已开始最小capability契约实现：manager/python_verification.py与tests/manager/test_python_verification.py。13定向测试通过（exact node IDs、glob/目录/flags拒绝、source/scratch/proxy隔离、固定OS sandbox argv），Ruff/Mypy通过。
- 当前模块尚未接入生产、没有runner/resource/receipt/API接线，不能用于真实需求验收；服务不加载这项能力。
- 新增独立 `python_verification_runner.py`，作为后续 capability 中 hash-bound 的固定入口，使用 `-I -S -B` 启动；不加载 editable `.pth`、ambient pytest 插件/参数或候选目录外的 conftest。批准节点与实际 collection 双向绑定，限 256 项；skip 返回非零。PyMySQL 只适配本次专用 DSN 到固定 Unix socket。
- Red：新增真实子进程 fixture 首先因 runner 缺失失败；实现后 `pytest -q tests/manager/test_python_verification_runner.py tests/manager/test_python_verification.py` 20 passed / 1.08s；两source Mypy、三个文件Ruff/format通过。独立只读 QA 复跑 runner 7 passed / 1.19s，未发现具体问题。
- 此进展仍不包含 Docker resource、receipt、精确审批入口或完整真实 OS 拒绝验证；不构成候选验收或生产能力启用。
- Discovery已实现：精确candidate tracked regular测试文件检查、本机Unix Docker daemon和已有image只读发现、runtime/dependency/runner/binary完整指纹。真实本机discovery成功，1.96s；没有建容器、拉镜像或执行候选。独立Review指出并已修复扫描错误漏算、外部symlink链返回内部、Git partial-clone隐式lazy-fetch；文档已正确区分bytecode读/写。
- 真实OS回归暴露`:minimal=read`仍允许读取公共`/private/tmp`中的未授权fixture；先运行定向测试得到red，再显式加入`:slash_tmp=none`与`:tmpdir=none`收紧继承规则。固定runner在用户临时目录和公共临时目录均验证source写、未批准secret读/写、proxy unlink/rebind、其他socket别名及TCP连接拒绝，精确批准socket连接成功。测试只使用临时fixture，没有业务凭据、MySQL或候选验收。

- 最新定向验证：显式启用两组真实OS fixture，三个test文件合计29 passed /4.51s；6个相关source/test文件Ruff、Mypy通过，git diff --check通过。没有全量pytest、MySQL、生产数据库修复或候选验证执行。
- 独立QA复跑真实OS fixture：2 passed /2.95s，涵盖user-tmp/public-tmp；未发现问题，明确不包含MySQL或生产链路验收。
