# 独立审查

审查本任务相对 `8b31c96` 的 diff，无阻塞问题。

- 资源在应用创建时冻结，旧运行 Schema 不再从磁盘混入新 UI。
- 操作 manifest 与真实 ConsoleIntent union 一致；前端每次 POST 前校验能力，失败清除旧 manifest。
- 操作区及增量展示签名含能力事实，撤销后旧按钮不能继续提交。
- 外部未知 action/非法输入与内部 record 校验错误分别返回中文 409/422/503，不回显 payload。
- 真实 HTTP HANDLE 测试覆盖 FileStore reopen 与幂等；浏览器另验证旧服务零 POST 与状态变化。
- 能力撤销保留 RUNNING 已受理、RESOLVED 决定和既有 handling 的实际建议；通用页面提示只
  限制后续新操作，真正提交 guard/旧 422 才说明本次未受理。
- 存量需求无需改库；加载新服务后仍按原授权、停止和现场事实继续。

独立执行 capability CJS 7/7、Ruff、node check、diff check；其余增量结果来自 Root/UI worker，
审查已核对测试代码，未重复执行。未修改代码、未访问或操作生产 ASE。
