# 契约

`ShutdownRefusal(component, reason, active_count=None)` 为frozen/extra-forbid typed值；
计数只在组件实际提供时保存，其他组件为unknown而不是猜测0。
component为WRITE_GATE/CONSOLE/KNOWLEDGE_INDEX/OWNED_PROCESSES/LIFECYCLE；reason为
TIMEOUT/UNCONFIRMED/COMPONENT_ERROR。全部文案由固定映射生成，不接收任意异常文本。

`ShutdownResult.refusal` 与 `ServiceShutdownResult.refusal` 为可选扩展，仅REFUSED时可存在。
旧无字段结果仍有效，序列化省略None。coordinator保留真实组件的计数；sticky首次错误的诊断
不可被后续begin/await擦掉。host `_publish(..., refusal=...)` 透传，CLI只在精确result匹配后展示。
诊断只解释拒绝，不构成READY、执行停止、保存证明或授权；state仍是唯一生命周期门。

|情形|诊断|行为|
|---|---|---|
|现有HTTP写入未结束|WRITE_GATE/TIMEOUT+真实count|继续等待或解除纯超时|
|已领Operation/dispatcher等待|CONSOLE/TIMEOUT+真实activecount|继续等待|
|Operation最终持久化失败|CONSOLE/UNCONFIRMED|保留只读，核验记录|
|索引tick等待/失败|KNOWLEDGE_INDEX/TIMEOUT或UNCONFIRMED|失败不可解除|
|执行registry未排空/uncertain|OWNED_PROCESSES/TIMEOUT或UNCONFIRMED|不把PID消失当停止|
|组件抛异常|当前component/COMPONENT_ERROR|不序列化raw异常，保持sticky|
|生命周期保存失败|LIFECYCLE/UNCONFIRMED|保留原实例|

Good：真实owned未核验时，重复请求和status仍说明执行停止/记录未核验，不提示反复等待。
Base：历史无诊断REFUSED保留未知，不能反推具体环节。Bad：把active=[]用作安全退出或自动清除sticky。
