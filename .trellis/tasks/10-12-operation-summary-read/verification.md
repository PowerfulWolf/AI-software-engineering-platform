# 验证与交付记录

## 改动
新增有界 typed 只读摘要/分页/游标/ETag；默认25最多50条，完整scope active≤64，response≤256KiB。完整bytes重新读/hash后仅复用512条/2MiB以内摘要，完整Operation/plan/authority不缓存。四份Schema、运行时feature能力与契约同步。旧完整GET、写入、claim、审批不变。

## 增量红绿
初始新增测试红：summary_models模块不存在；随后Schema生成与新增locator断言同步后绿。相关105项通过（summary21、transport、core、idle_replay、operation_budget、scope_contract）。最后追加完整warm36历史文件read计数、非GET405与querySchema回归后summary21再次通过。Ruff/check/format、strict mypy6源/测试文件、git diff --check通过。未跑全量。

命令：

```sh
PYTHONPATH=src ABS_VENV/python -m pytest tests/web_console/test_operation_summaries.py tests/web_console/test_transport.py tests/web_console/test_core.py tests/web_console/test_idle_replay.py tests/web_console/test_operation_budget.py tests/web_console/test_scope_contract.py -q
MYPYPATH=src PYTHONPATH=src ABS_VENV/python -m mypy src/ai_software_engineer/web_console/{summary_models,summary_projection,store,core,transport}.py tests/web_console/test_operation_summaries.py
PYTHONPATH=src ABS_VENV/python -m ruff check src/ai_software_engineer/web_console/{summary_models,summary_projection,store,core,transport}.py tests/web_console/test_operation_summaries.py
```

ABS_VENV指主仓.venv仅工具解释器；PYTHONPATH绑定隔离维护worktree源码。独立root只读审查未发现阻断，并要求补HTTP同mtime/ETag篡改、fullPlan weakref和cold计量，均已落实。UI实现由另一worker独立负责，集成前需验证接口/审批完整GET前置。

## 隔离性能与内存
已封存327 Operation/981版本/28MB只读审计镜像再复制到private scratch；不访问生产SQL/Host/claim/服务。冷summary CPU1.676s/wall1.739s/327full decodes；25条page33,802bytes。warm50轮CPU均值0.156s、最大0.187s/wall0.168s，0full decodes；完整981文件仍每次read/hash。cache327条/452,021serializedbytes。完整Operation weakrefs全释放，live FullOperation/ExecutionBaselinePlan六次采样均0；RSS约258–298MB变化且末尾稳定，不能宣称长期泄漏已消除。私有证据 `/tmp/ase-operation-summary-benchmark-result-20261012.json`，只在文档保存有界数据摘要，不提交原生产journal/patch正文。

本优化针对轮询历史大对象/响应体，与K1恢复核验耗时不是同一热点。冷读仍完整验证较慢；active超过64或页超过256KiB明确拒绝，前端不得用部分记录执行。

## 存量数据处置
无需改库/重写journal/新需求。全部历史与审批原封不动；首次只读投影允许较慢。部署必须等待生产无活跃Operation/role执行的受控维护窗口，当前维护worktree不得直接部署。用户刷新原Project即可使用摘要读取；K1审批/继续仍由原公开精确接口完成。

## 回滚
回滚本提交的新增摘要endpoint/cache/feature及相关前端能力；旧完整GET始终保留。所有Requirement/Task/队列/attempt/QA/Review/审批/开发现场保持原值。
