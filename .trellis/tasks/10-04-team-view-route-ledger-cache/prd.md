# 限制 Team View 轮询的模型调用记录读取开销

## 问题

浏览器每 5 秒读取一次 Team snapshot。当前读模型为当前 Task、历史 successor/remediation Task 和
候选验证逐项重复解码同一个 `runs/model-routes/run_*` 目录；随着交付轮次增加，单次只读请求会
重复校验数百份不可变记录，导致服务 CPU 持续满载、Team API 超时，页面显示旧的阻塞状态。

## 目标

在一个 snapshot 内复用已完成的模型路由记录解码，并按 Task/run 身份过滤；snapshot 之间不共享
缓存，继续执行 symlink、文件、Schema 和 SHA 校验。不得修改任何 Task、StateEvent、Artifact、
Evaluation、Assignment、Lease、Operation 或 verdict。

## 验收标准

- 同一 snapshot 对一个 sidecar route ledger 只读取并校验一次；多个历史/验证视图仍返回相同 runs。
- 新 snapshot 重新读取目录，新增或损坏记录不会被旧缓存隐藏。
- Team API 在当前 K1 sidecar 上恢复到可完成的有界读取，不改变中文阻塞状态和完整执行历史。
- 只运行 Team View 读模型的增量测试、静态检查和 diff 检查。

## 存量数据与回滚

无需迁移或直接修改存量 sidecar/MySQL。回退平台提交并重启 `ase-console` 即可；旧路由记录和
Delivery checkpoint 保持原样。
