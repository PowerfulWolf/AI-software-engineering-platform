# 未修改必要文件的恢复范围审批

## 目标与证据

K1 已接纳 progress `art_coder_40efda15a6167c750fbeb7b2952661d4` 报告 contracts fixture 需更新，但 `tests/contracts/test_json_schema_contracts.py` 不在原冻结写权限。现 D5 只发现实际 dirty omitted paths，导致守规的 Coder 无法提出必要范围；不能先越权改文件触发审批。

## 范围

只扩展 terminal pre-candidate recovery 的 scope 来源：操作者提交绑定已接纳 progress ID/SHA 的最多8个精确已跟踪、未修改文件路径及说明。原有 dirty discovery、两次精确审批、新 Task、独立角色链不变。不能修改运行中的 Task 或扩大命令/网络权限。

## 验收

- 原路径仍可读取，旧 JSON/hash不变。
- 缺/错progress、非terminal、未接纳、dirty requested path、目录/glob/deny/symlink/不在基线的文件拒绝。
- proposal以Git metadata绑定每个文件mode/blob，不能在审批前读取被拒内容。
- 范围审批和plan审批分离；new Task包含批准路径，old Task/dispatch不变。
- Console展示并原样回传typed request；审批/执行重算所有facts，漂移拒绝。
- 只跑相关增量测试；独立QA及Review。

## 允许路径/回滚

recovery models/native/scope/entry/current/resume、Manager/Console command与summary、team_view approval、对应schema/tests/spec/docs。回滚代码保留新facts；已用新contract的计划不能交旧版本重放。存量通过新proposal和审批恢复，不手工SQL/业务worktree。
