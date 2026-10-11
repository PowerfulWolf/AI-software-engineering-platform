# 空闲 Console 派发退避

## 目标与事实

327 个历史 Operation / 981 个版本约 28 MB 的私有离线副本测量显示，完整 idle
claim 次序校验每次约消耗 0.11 CPU 秒。固定 0.25 秒等待会持续重复完整 inventory。
仅降低无工作时的扫描频率；不把历史数据、mtime 或缓存结论当作执行授权。

## 范围与验收

- 默认空闲等待依次 0.25、1、2、5 秒，并封顶 5 秒；无忙循环。
- 同进程 submit 使用现有 Event 立即唤醒，并重置空闲等待；Operation 执行后也重置。
- begin_shutdown 立即唤醒；cancel_shutdown 保留现有线程/持久化门禁并恢复初始等待。
- 外部同 store 写入最迟在下一次等待结束发现，稳定默认 idle 的等待上界为 5 秒。
- 每次实际 claim 仍调用原 claim_next，完整文件 bytes/hash/path/sequence 校验不变。
- 假事件测试不得真实等待 5 秒；相关 core/shutdown/idle-replay 增量测试、Ruff 和 strict mypy 通过。

## 不变契约

没有 API、Schema、SQL、权限、审批或持久化格式变更。不修剪 Operation，不更改
K1、retry账、verdict、停止记录或工作区，不操作生产服务。

## 存量数据处置与回滚

无需改库或改写 journal：新进程从初始等待开始，每轮仍读取已有可信 store。
仅在平台空闲受控部署后生效。回滚此代码提交恢复原扫描频率，保留所有历史。
