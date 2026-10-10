# 恢复准备明细

## 问题与目标

真实 K1 的精确恢复批准已接纳，但准备曾持续超过一小时；Team GET 被长读取占用，
Operation 只有 RUNNING，没有给用户可理解的已完成准备事实。用户无法判断当前由谁处理，
也容易再次提交或重启。为以后真实执行的恢复准备记录独立、有界、持久化的观察明细。

## 范围与契约

- 不改变 Operation hash chain、状态机、原审批、claim、role、verdict 或执行身份。
- 只有精确 CONTINUE_DELIVERY 恢复批准的执行 scope 产生记录；绑定 Operation/Team/Project/
  Requirement/发起 checkpoint/批准 plan。同步边界成功返回后记录真实授权、Task封存、
  dispatch提交、seed核验、首轮实际Coder领取五种 milestone。
- 不捕获 provider prose、路径、环境、owner token，不显示百分比、心跳或推断当前模型执行。
- typed observer 构建/保存失败仅影响观察；不使已经成功的命令失败、重复执行或计费。
- 独立 GET /api/v1/operations/{id}/preparation-progress，不调用 TeamReader、Host或SQL初始化。
- 前端独立串行短时限读取当前需求的精确恢复操作，不能被 Team refreshFlight 占住；
  切换项目/需求后拒绝旧响应。明细直接可见、字体间距与正文一致，默认无需展开排障信息。
- 所有 milestones 是已记录观察事实，领取记录不能冒充当前运行；继续使用原节点与门禁。
- 缺失、损坏、旧服务404使用明确中文说明，保留以前已读明细并标示时间，不恢复操作权限。
- 轮询保持文档DOM、展开、选择和业务草稿，不反复重建详情。

## 验收与增量验证

1. Schema正向、缺证据、额外秘密字段、非法enum、scope/digest漂移拒绝。
2. file/memory store幂等、重开、篡改、symlink、独立锁与大小上限；操作历史bytes/hash不变。
3. 五个真实返回边界，失败不发布后续观察；sink/store失败不重复执行；scope reset。
4. 实际claim提交后观察，预分配/其他Task/QA/Review不能记录为首轮恢复Coder。
5. API GET/405/404/损坏，Team GET正在读取时仍独立响应。
6. Node与真实隔离Chrome：独立轮询、旧回调、legacy空记录、缺中间步骤、coder_reapply中文、
   读取失败与正文DOM/草稿保留、零审批POST。仅跑上述及直接影响的增量检查。

## 存量数据与部署

当前已运行的旧Operation不倒填准备观察，不修改SQL/旧文件、不重复提交审批；
已验证的dispatch/seed/invocation事实仍由原契约负责。新代码仅作用于以后真实启动的操作。
活动需求执行结束或出现明确安全维护边界后，受控重启加载；不得热替换或强杀当前Agent。
目标基线与运行平台版本分开，不静默改变精确批准的工作区。

## 回滚

回滚新增观察代码/API/前端并受控加载；保留已封存明细与所有Operation/Task历史。
观察记录没有授权作用，回滚不会取消批准或推进需求。
