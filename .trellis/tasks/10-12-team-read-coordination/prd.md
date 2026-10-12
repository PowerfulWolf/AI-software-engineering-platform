# 同页 Team 读取协调

## 问题与目标

后端 full/summary/detail 共用一个同步读取 worker。前端摘要 refresh 和选中正文分别派发，
用户在自己的摘要读取期间打开正文，正文立即收到 TEAM_READ_IN_PROGRESS。正文将此归为
不可用，随后同 source 的渲染不再读取；即使摘要成功仍需用户手动重试。

目标是同页只进行一个 Team GET/body 读取；最新选中正文等前一次 HTTP 完成后读取，外部
浏览器造成的固定 busy 只作有限延期重读。保留真实不可用、版本变化和完整性错误。

## 范围

- app.js 统一 full/summary/detail 的客户端调度，保留原摘要 latest Project intent 和独立辅助读取。
- abort/导航移除等待者；当前 owner/source 每次 await 后及发 GET 前重验。
- 固定 busy 最多额外重试三次，延迟 1/2/4 秒；耗尽可显式重读。40秒正文总体 deadline 继续有效。
- 完整当前正文成功读取后同 source 不重复；真正 TEAM_UNAVAILABLE、409、非法正文不自动重试。
- 中文展示忙碌等待与有限重试耗尽；保留旧正文，但不能保留审批资格。

## 验收

1. 真实 refresh 调用链持有 summary 时打开详情，不向后端并发派发 detail；释放后自动 ready。
2. 持有 detail 时摘要等待，辅助 Operations 不阻塞；自动 poll 不与自己的正文竞争。
3. A→B、close、Project、source变化仅当前 owner 发 GET；旧响应不能恢复正文或批准。
4. 外部 busy 三次退避有界；之后显式重试，真实错误零自动重读。
5. 原五秒完成后调度、摘要busy退避、Product精确正文批准和完整14轮历史保持。

## 验证与回滚

先保存原真实 refresh 链 RED；运行精确 Node 测试及相关 Chrome、node --check、diff-check。
不运行全量测试，不访问生产、不调用模型。无需存量数据修复；刷新浏览器即可加载资产。
回滚前端提交后刷新浏览器，全部持久化事实不变。
