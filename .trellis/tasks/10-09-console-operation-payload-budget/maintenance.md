# Operation 读取修复的生产维护记录

## 授权、范围与结果

用户明确回复“授权你完成本次服务维护重启”。此次仅替换无法正常排空的旧 Console 实例，
加载已提交并推送的修复 `447bf95`。未批准恢复方案、继续 K1、启动 Coder、补造原 Run 结果或
停止记录，也未改写历史预算、Task、Operation、Requirement journal 或审批。

北京时间 2026-10-09 13:48:23 完成验收。新服务 PID `43561`、实例
`console_instance_d110d2c51b206a15fa70177722682434`，状态 `RUNNING`。服务脚本 `status`
返回“服务正在运行, 可以接收新操作。”配置仍是
`/Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json`，平台根目录仍是
`/Users/zhangjunshuai/workspace/code/.ase`，Team 为 `team_ai`，监听 `127.0.0.1:8765`。

## 维护方法与事实边界

原 PID `1797`、supervisor `1846` 的高精度出生身份、可执行文件和精确参数均已重新核验。
原实例 `console_instance_fb9c8b499ecb52a0df9bee79685c0610` 的 request/result 身份匹配、状态
均为 `REFUSED`；请求到拒绝仅 0.091011 秒。旧内存中的 Operation 读取失败锁定无法通过
普通 restart/resume 清除。

维护持有既有 `console-service-replacement.lock`。启动前完整校验 287 个 Operation，全部
终结（211 SUCCEEDED、70 FAILED、6 INTERRUPTED），没有 RUNNING/QUEUED；没有配置应用请求，
已有配置应用状态为 SUCCEEDED。当前本机调查无 blocker，原服务没有子进程或其他进程组成员。
先完整归档原 PID、生命周期记录及日志，再停止精确 supervisor，核验其退出和所有权释放，
按本次授权进入精确服务实例的维护终止路径。

终止核验辅助程序遇到 `ProcessLookupError` 并停止后续步骤；随后独立重新确认两个旧 PID
均不存在、端口已释放、当前调查无 blocker，以及全部 Operation、工作区与索引未变。
重新获取同一替换锁，归档最终完整旧日志，把四份旧 PID/生命周期文件移入受限归档后，
使用既有 `locked start` 及继承的锁 fd 启动修复版。没有把旧 REFUSED 改为 READY，维护归档
不等于普通安全收尾证明，更不等于旧 Coder Run 的历史停止证明。

启动构造正常 Host，允许平台自己的组织配置初始化和知识索引服务启动；“未变”声明仅指
下述实际逐项核验的 K1 业务事实与保留现场，并不宣称平台启动完全只读。

## 存量数据处置与验证

无需改库或数据迁移。现存完整 READY 方案兼容新 reader。

| 验证项 | 结果 |
| --- | --- |
| 实际新服务 Console、Operation 列表与原方案详情 | HTTP200，delivery_ready=true，contract_version=3 |
| 原恢复准备 Operation | `operation_dac65f2d0a4deb7914377f995fe2caa1`，SUCCEEDED / READY |
| Operation 完整目录（含 model-call 记录） | 1,525 个条目、1,154 个文件，维护前后内容、模式和路径完全一致 |
| K1 原工作区与 Git index | 2,000 个条目全部一致，HEAD、branch、dirty inventory 和 index SHA 均未变 |
| K1 Task/角色队列/历史 projection 与 Requirement journal | 维护前后逐项一致 |
| 独立验收 | 另一 agent 仅 GET 与读取归档，再次核验上述结果通过 |

原 Task `task_dc5cf0aee44e5ffe0cb600557204e0d0` 仍为 IMPLEMENTING，attempt 6 的 WorkItem
仍为 WAITING_DEPENDENCY / EXECUTION_UNCERTAIN；原 Run `run_9b76fb2865144f2abb6407923320ec4e`
结果仍保持未知。保留的开发分支仍是 `ai/feature/k1-auto-knowledge-20261005`，HEAD
`0a562f4f64ea5bbc63c371513bb623b1fe5b2101`，没有另建需求或重置现场。

原 Operation SHA：`62d91d5bb611b24fde16934f9586d1876732162e1ff8dff0d15a878b4ca5a21b`。
原方案 SHA：`5a18365a045d1b31e3c98c773a0385002ab83d44c2bc63087016ac41b9ba3e3a`。
两个摘要维护前后及真实 HTTP 返回完全一致。

维护前后的全量清单、原始日志、PID/生命周期原字节及授权事实保存在：

```text
/Users/zhangjunshuai/.local/state/ai-software-engineer/maintenance-archives/20261009-operation-reader-054612
```

归档目录为 0700、所有文件为 0600，不提交原日志或生产 payload 到仓库。
`completion.json` SHA256 为 `d0ffe09cc0ce68138a2a1839149de61e8e37b2942206b66ec7f7a4f6a82a7d63`。

## 用户下一步与回滚

用户刷新**原 K1 需求详情**，查看已准备方案及“批准保留进度并继续原需求”入口。仅在查看
平台检查结果、核实页面列出的实际停止前提后，明确勾选并批准。维护重启没有代替该批准；
旧执行结果保持未知，此后才可依据新 claim 继续 Coder，再经独立 QA/Review 交付。
浏览器自动化连接不可用，因此未声称已通过真实浏览器点击验收；已验证真实服务接口和原方案完整性。

此次没有新增代码；沿用修复提交的 321 项相关增量验证，没有跑全量 test。生产验证命令为：

```bash
ASE_CONFIG=/Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json \
ASE_SERVICE_STATE_DIR=/Users/zhangjunshuai/.local/state/ai-software-engineer \
./scripts/ase-console-service.sh status
```

回滚应先让新服务完成普通受控 stop，再回退代码并使用同一配置启动。不要还原旧 REFUSED
生命周期文件覆盖新实例，也不要强杀正在执行的新服务。回退 256KB reader 会再次使现有大方案
不可读，因此应保留此次读取兼容修复。
