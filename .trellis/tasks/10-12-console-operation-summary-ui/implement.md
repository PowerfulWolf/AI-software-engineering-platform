# 实现

前端识别v0.1 operation summary能力，改为scoped摘要/ETag轮询。当前Requirement只保留
最新checkpoint/task相符的摘要locator，再读取对应真实完整Operation；旧server保持完整
GET兼容。阅读accessor不生成伪intent/result，当前authority仍只由真实fullrecords构成。

摘要3scope、历史2scope（当前页+最近4前页）、完整8条/32MiB、单条16MiB有界。
历史显式上一页/下一页/返回最新，全历史可达；展开按需fullGET、关闭释放包括pending
请求的latefullresponse。首次空历史、分页DOM签名、选中/Team切换与cache逐出精确门已补。

所有submitOperation共享写前fresh摘要+必需单条完整GET。原request/task/source、
snapshot/ConsoleTeam、专用owner generation、selection/Project与capability签名在每await
及POST前一致；无source的create也不能跨Team或在manifest降级后提交。304重验旧页
scope/owner/cache实例；旧callback不能publish或撤销新owner。原六类工程proof/plan
predicates及服务端审批fences保留，历史审批只能阅读。

Core规范同步真实签名、wire、缓存生命周期、good/base/bad矩阵、测试、存量和回滚。
Root做展示/cache复核，独立Agent做授权终复核；224相关Node与13真实隔离Chrome通过。
无生产service/API/SQL、原K1、候选workspace或主checkout改动。
