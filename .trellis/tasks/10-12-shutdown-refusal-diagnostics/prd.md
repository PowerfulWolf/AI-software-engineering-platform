# 关闭拒绝原因保真

生产 PID802 的第一次受控停止完整等待300秒后拒绝；第二次请求约0.086秒即拒绝。
现有结果仅保存统一 REFUSED 摘要，丢失写入、Operation、索引、拥有执行或生命周期保存的
具体环节，也无法区别可重试的等待与不可解除的事实缺失。不能凭这些观察推断原失败根因。

## 目标和验收

- 从真实 coordinator 返回值到精确 instance/request/PID 的关闭结果、CLI wait/status保留
  typed 环节、固定原因和中文下一步；不输出异常正文、命令、环境或secret。
- TIMEOUT 和 UNCONFIRMED/COMPONENT_ERROR 分开；sticky拒绝重复请求保持首个诊断。
- 历史结果无诊断仍可读取；READY/RUNNING不得携带拒绝；不允许unknown字段或非法组合。
- 不改变关闭顺序、READY门、registry、锁、信号权限或任何需求执行/审批。
- fake coordinator与真实私有store/CLI和host调用链测试先RED再GREEN；仅相关增量测试。

## 存量处置和回滚

不改SQL或旧关闭/Task/Run/审批事实，不给PID802补造拒绝原因或READY。
旧实例无法从磁盘变更获得内存诊断，仍需先保留其REFUSED和日志、核对实际执行；不能把新代码
测试成功当作已解决旧实例。部署只能经核验的维护边界。回滚保留已有可选诊断，新reader必须
继续支持它，不删字段绕过读取校验。
