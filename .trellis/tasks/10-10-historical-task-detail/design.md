# 设计与契约

## 精确身份与依赖

复用 currentRequestTasks/isHistoricalRequestTask 的当前 scope 身份，增加共享 exact 父需求查询，
不能以 Task.title 推断父归属。Task 详情的 pollingDetailFacts 纳入该父需求及其拥有的任务，
以捕获父状态、当前 sibling 心跳/租约和 scope 变化；Task 本身未改变也能撤换历史标签。

## 只读展示

历史 masthead 直接显示“历史执行记录”“当次 · …”、当前需求阶段/状态及只读导航。
用现有 masthead、product-execution-summary、row/badge 视觉元素保持统一节奏，不新增 CSS。
第一章节沿 shared detailChapter 结构使用“当次执行结果”与历史说明，后三章保持完整。
历史概要只展示原 Task/typed execution 的历史事实与历史建议，不用 live task presentation
推导旧进程仍在执行。原始队列与完整证据保留在工程参考。

导航 callback 再检查当前 selected Task、exact Project/Requirement 归属及当前 Project scope，
失效时不跳转到同名其他项目，不执行交付命令。历史关系变化会替换对应 keyed viewBlock。
父状态变化只替换历史上下文 block，保留未改变的正文/完整历史 DOM 与阅读暂停规则。

## 验证矩阵

Good：同名当前 Coder 正在执行，旧 BLOCKED 详情明示历史，父需求显示“实现 · 执行中”。
Base：当前 scopes 为空，旧记录仍历史；父状态沿现有未知契约显示，不能猜新 Coder 已启动。
Bad：父归属缺失或跨 Project，不合成当前需求；旧非终态 RUNNING 不冒充实时执行；
旧恢复建议不能显示成当前下一步或业务确认。

测试真实 buildDetail DOM、首屏 visible 文本、导航无 POST、未改变 snapshot bytes、12+历史记录
与源 hash；增量签名验证 parent-only/sibling-only/scope 变化，现有 browser fixture 补相同断言。
