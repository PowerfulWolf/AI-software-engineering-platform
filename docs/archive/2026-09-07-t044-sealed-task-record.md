# T044 D1 — 恢复 Task 输入封存

本阶段是 Astra 的平台开发，尚未运行原需求的恢复交付。

- 新增 RecoveryTaskRecord：计划/批准摘要、重新绑定的 Request、NEW Task 和记录摘要。
- 复用恢复目录的不可变发布，支持重开、精确重放、冲突拒绝和完整性检查。
- RecoveryTaskSealingService 在封存及执行前重新校验当前事实；历史读取不能替代当前授权。
- 无新资源分配、dispatch、MySQL Task 行、worktree 改动或模型调用；原失败现场保留。

## 验证与剩余边界

Schema/model/store 测试覆盖未批准、Task 状态/身份/元数据、改动冲突、腐败、secret和base/auth
不匹配；真实临时Git/MySQL的离线夹具覆盖封存/重开/当前漂移。没有真实业务恢复批准。
下一步仍是资源分配与新执行、CLI及seed receipt/provider admission，再做真实三角色交付。
回滚为撤销本源码提交；没有修改现有数据库结构或旧交付历史。

## Bug Analysis: Schema 注册遗漏

1. Root cause：B/D，生成模型Schema缺少仓库全局注册要求的`$id/$schema`；专项验证未加载注册表。
2. 初版专项通过，全量在collection阶段报`KeyError: '$id'`，未运行任何真实任务。
3. P0已修复：补齐Draft 2020-12与唯一URI，专项断言标识及Schema合法性，全量复验。
4. 扩展检查：全局注册表加载所有schema；不改为忽略缺失标识，避免掩盖后续遗漏。
5. 已将生成与注册的区别写入恢复spec，后续重新生成必须保留标识。

## 最终质量结果

恢复专项61 passed /46.65s；修复注册遗漏后全量879 passed /153.94s。
Ruff/format497files、Mypy277files、offline lock/build、diff-check通过。
无真实模型调用、业务恢复记录、需求提交或GitHub push。
