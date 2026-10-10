# 验证记录

## 契约RED与GREEN

先仅建立测试运行179,583B完整干净正文的三次通用脱敏：原实现真实subn次数18，期望6失败；
输出本来一致且零occurrence。完成实现后同测试6次，nested scope复用、返回新结果对象、下一
scope重新6次。29项新增测试全部通过，覆六种命中/count、完整正文/规则定义/顺序、两向
mode边界、共享预算、精确UTF-8账本、必要逐出/不逐出、异常和nested guard、独立线程。

直接generic缓存最初让原terminal低cap测试失败：源文件7110B恰好填满预算，但之前独立
generic元数据73B已占空间，导致源事实不能记忆。仅内部guard无法解决该独立输入；保留
source/patch优先级后只逐出必要generic、源事实再次只扫描一次，未改旧测试断言或预算。

## 增量命令与结果

```text
.venv/bin/pytest -q tests/context/test_generic_redaction_scope.py
29 passed in 0.13s

.venv/bin/pytest -q tests/context/test_generic_redaction_scope.py tests/context/test_source_inspection_scope.py tests/context/test_source_secret_detection.py tests/recovery/test_terminal_source_inspection_scope.py tests/manager/test_baseline_source_inspection_scope.py
168 passed in 81.80s

.venv/bin/ruff check src/ai_software_engineer/redaction.py tests/context/test_generic_redaction_scope.py
All checks passed!

.venv/bin/ruff format --check src/ai_software_engineer/redaction.py tests/context/test_generic_redaction_scope.py
2 files already formatted

.venv/bin/mypy src/ai_software_engineer/redaction.py tests/context/test_generic_redaction_scope.py
Success: no issues found in 2 source files
```

五文件组启动后又添加了一个“只逐出必要generic项”测试，核心代码未改；随后完整新文件29项
另跑通过（组运行时收集的是28项，故组结果168）。不为单个测试增加再重复慢的整组执行。
仅增量测试，未跑全量。独立reviewer coder_python_tooling_fix 静态复核并独立选择11项容量/
guard/mode边界测试，11 passed in 0.04s；没有代码阻塞发现。按其文档建议澄清compiled pattern
定义/flags相等可以复用，单纯新对象身份不必重扫。真实同封存输入测量由独立Agent补充，
不输出正文。

## 同封存输入的独立离线复测

baseline_resume_contract 在fresh进程对同一四个binding及epochs输入使用相同profile/计数
包装复测。bindings完整读取校验3.011→1.613秒，subn22,326→1,584；两次epochs合计
5.044→3.494秒，subn54,300→1,998，regex自身耗时2.858→0.699秒。同179,583B正文
三次脱敏18→6次，输出与363条目/85个不同完整正文均保持。

bindings前后仍24次sealed read/34,811,964B、1089次正文validator、3721次generic调用。
两次epochs前后仍56次sealed read/86,923,008B、2178次正文validator、9050次generic调用，
纯SHA输入543,800,688B；全部SHA分组调用/字节及11类model_validate计数逐项相同（合计648）。
这证明只减少重复纯regex工作，外部读取/模型和完整性校验不被省略。时间包含profile与本机
负载影响，仅是同输入离线结果，不能作为生产端到端改善比或称当前正在运行的操作已加速。

剩余成本仍是重复序列化、解码和SHA。本次没有缓存领域模型或减少这些校验，不扩展任务范围。

## 存量数据处置、风险与回滚

没有Schema、artifact、SQL或操作/审批事实变化，不需改库，未访问生产Task/worktree或操作
服务；当前运行服务没有因本任务重启。该优化不能代替当前需求的精确审批/停止/现场校验。
缓存只是同同步调用的瞬时纯事实。既有source/patch敏感输入缓存语义不变；新增generic不记
含occurrence正文、结果对象或explicit secret。通用缓存为可逐出的机会型优化，不能承诺
每种输入在任何小cap下都只扫一次。16MiB只约束payload字节，不代表整个Python进程内存。

回滚本任务redaction缓存扩展和spec增量、保留任务验证历史；部署由父任务选择空闲受控时机。
没有被本任务改动的持久化事实需要回滚。
