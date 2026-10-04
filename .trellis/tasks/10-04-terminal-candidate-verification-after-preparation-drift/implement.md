# 实现

恢复控制器现在把终态候选作为独立验证边界处理：先消费已有 completion，随后直接复用当前候选
验证计划或生成新计划；只有没有候选 revision 时才调用旧原生重试。

新增回归测试覆盖“候选无计划 + preparation 漂移”场景，测试用失败的 native retry 断言确认平台
不会再次进入旧阶段，并且能返回 fresh verification proposal。
