# 本次展示失败和慢读的复盘

## 根因分类
跨层契约和覆盖缺口：optional baseline SHA 在 to_wire() 排除None，却进入处理报告身份使用的另一嵌套model_dump()。旧报告并未丢失，按漂移的key读它导致整个Team503。
隐含性能假设：退休校验、主展示、Project count分别调用history，完整历史被多次读取/深拷贝；历史Task和独立验证重复扫同一evaluation ledger。
请求依赖和用户意图：独立Operations响应拖住已完成Team；失败清空可读history；Knowledge/状态页读不完整归属deadline。独立发布暴露late UPDATE与用户关闭的nullable选择竞态。

## 前次判断和修复为何不足
根据RECORD_NOT_FOUND推断调查独立记录缺失不准确，真实失败是handling自己的重算索引；补记录会处理错误对象。已有测试只验证to_wire兼容，没走旧报告文件名及HANDLE幂等。已有serial refresh防止重叠但无法解决分支互相等待。

## 已完成的预防
- absent新字段明确exclude_if，旧key真实重开/文件不变/处理幂等回归；非空SHA仍进摘要。
- 独立proof、错误key、scope/权限/hash坏记录继续拒绝；9份嵌入Schema核对及standalone parity补齐。
- request内typed已验证prefix复用，次次snapshot重新读并检测新增/篡改；count和目录同prefix。
- 独立UI分支发布，旧history可读但current权限失效、重连再次明确确认；所有相关GET有deadline。
- independent reviewer提供关闭后late edit红例，selectionIntentRevision守护显式用户意图。

## 系统性检查与知识落地
已写live-team-view/incremental-polling/read-memory-lifecycle/web-console及recovery-thinking。此仓库没有src/templates/markdown/spec镜像，不生成额外模板。无需SQL或原record迁移。未来版本新增optional事实同时回归所有canonical消费方式和历史身份；性能比较必须用同scope成功wire并串行测量。
