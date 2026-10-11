# 新恢复计划冻结工程授权和受控续跑能力

## 问题与目标

正常派发 Task 冻结 engineering_policy 与 interruption_continuation_policy；现有恢复
Task builder 没有传递这些字段。恢复后丢失 Manager 工程能力、已注册验证与受控续跑支持。
不能通过 builder 读取当前配置或追补旧计划授权修复：新能力必须进入新 RecoveryPlan
精确摘要，经过独立明确批准后才进入新恢复 Task。

## 范围与限制

新增typed可选目标授权；trusted Host ENGINEERING主体按真实Team/Project/Repository/root
签发bounded_local策略，续跑只按原Task冻结retry预算构造，不从当前配置扩额。原Task没有
冻结retry预算时不创建v2续跑授权。无工程主体不新增授权。

Builder只使用已批准plan字段；current facts与record核验签发职责、scope、来源、冻结预算。
旧计划缺字段时在全部嵌套序列化中保持省略，旧摘要与恢复Task bytes不变，不补库、不迁移
已批准方案、不重写历史Task或verdict、不新增执行器。知识准备localtimeout是独立缺口，
不以本任务宣称已解决，也不依据缺native-start补造执行停止记录。

只运行pure/fake contract增量、Ruff、Mypy及Schema一致性，无MySQL、生产操作、提交或部署。
共享checkout保留workspace_snapshot及根代理其它修改，不碰app.js。

## 验收

1. 新目标授权改变plan digest，旧批准不适用；新批准builder精确复制两policy。
2. 原预算、scope、source digest、issuer职责或policy不一致拒绝；记录不能注入计划外授权。
3. 新目标授权签发不读取当前retry配置；原预算缺失不创建v2。
4. legacy plan/digest及Task字节保持；新字段None在nested dump也省略。
5. 正反、边界pure/fake测试与静态/Schema检查通过。

## 存量与回滚

不改存量计划、批准、Task、Operation或工作区。需要新授权的现有需求必须重新准备并明确
批准新摘要方案；旧已批准计划继续按旧字段执行，无追溯能力。生产流程由根代理另行处理。
发布新字段后回滚需保留新字段读取兼容，不能删除授权事实或把旧批准升级成新授权。
