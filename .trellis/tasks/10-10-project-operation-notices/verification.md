# 验证记录

实际生产只读审查：当前K1 DELIVERING/RUNNING与页面实现·执行中一致，恢复准备五条事实齐全；
1440/390无水平溢出，真实读取失败/恢复保留准备卡与行DOM和scroll。无nonGET、无JS error。
新会话误弹的历史CREATE失败与当前正常交付无target关联，见PRD精确身份。

所有修复测试使用fake HTTP，不操作生产。

## Red → Green

- 新增Node首会话旧创建失败/退休目标两例在实现前2失败：第二次渲染旧创建失败覆盖当前
  ACTIVE，关闭当前真实决定后旧退休目标ACTION_REQUIRED复活。
- 新增真实Chrome历史入口在实现前1失败：旧失败仍绘制modal backdrop，无法进入页面。
- 实现后以上均通过。12条历史用例曾因期望文案写成“阻塞”而真实label是“已阻塞”失败，
  仅修正断言后通过，未改变产品状态文案。

## 增量验证

```bash
node --test tests/team_view/stale-operation-notice.test.cjs tests/team_view/operation-progress.test.cjs tests/team_view/operation-capabilities.test.cjs
```

43 passed，约0.10s。其中通知19例覆盖当前精确目标恢复审批/待处理、跨action覆盖、关闭
不复活、本会话受理和故障、初读失败不建基线、Team/Project隔离、Team级管理兼容。

```bash
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test tests/team_view/browser/notifications.test.cjs
```

21 passed，约15.09s。新增历史显示完整原因与阶段/建议，全部12条不固定8条；时区offset
按实际时刻排序，同刻按ID稳定排序。原通知颜色/草稿/ack/reload/当前审批兼容均通过。
最后补强Operations 503/恢复后单跑项目历史入口1 passed，约0.94s；同历史fold/展开/记录
保留并就近标明旧数据，恢复说明消失。390/1440无横向溢出，键盘Enter展开，无额外GET。

```bash
node --check src/ai_software_engineer/team_view/app.js
node --check tests/team_view/stale-operation-notice.test.cjs
node --check tests/team_view/browser/notifications.test.cjs
git diff --check
```

全部通过。项目未配置独立JS lint/typecheck，无Python生产代码变更，未跑全量测试。

## 存量数据处置与交付边界

无需改库、清历史、补审批或重建需求。已保存Operation字节在Node/Chrome筛选前后相同。
真实当前K1继续由已有运行服务管理；此任务未POST、热换资产或重启服务。兼容前端需由root
在安全空闲维护边界加载后刷新生效；回滚此通知资格/历史入口/样式仅恢复原展示问题，所有
Operation、审批、需求、Task与开发进度保留。最终提交/部署由root处理。

## 独立审核

recovery_preparation_backend只读审查完成，未发现阻止提交的问题。独立Node通知19/19与
新增真实Chrome项目历史2/2通过，JS语法和限定路径diff检查通过。复核首读异步到达、
即时提交失败、ACTIVE后失败、Team/Project/target隔离、12条完整历史、offset排序、空态、
键盘、390px与失败恢复保留DOM、安全textContent和无新增GET。root另核验语法/diff与
规范契约一致；没有把隔离fixture验收声称为生产已加载。
