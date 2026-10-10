# 验证与集成交付

## RED → GREEN

新增artifact-feedback.test.cjs先RED：**7 failed**，实证任意父列表都被称为QA/Review反馈，且
缺少仍须独立验收的边界。修复后最终 **7 passed，0 failed，77.7ms**，覆盖：

- QA与Review实际父产物；implementation-report和coder-progress两种Coder产物。
- 仅plan、coder-progress、implementation普通输入；未知且名字像QA的父ID。
- 选中同TaskView的合法历史反馈；不受其他Project/Task同名产物影响。
- 重复/冲突父ID、缺少SHA、SHA不一致、URI漂移、foreign Task lineage。
- 正向说明使用muted而非验收成功样式；事实bytes不变且submitted=0。

通过的命令：

```sh
node --test --test-reporter=spec tests/team_view/artifact-feedback.test.cjs
node --check src/ai_software_engineer/team_view/app.js
node --check tests/team_view/artifact-feedback.test.cjs
node --check tests/team_view/browser/execution-history.test.cjs
git diff --check
```

无全量测试。浏览器正向fixture的身份与唯一implementation定位已作语法和静态校验。

## 独立复核

`/root/coder_python_tooling_fix` 只读核对真实projector/reader字段、同TaskView的父身份/类型、
合法successor历史、未知/重复/冲突门及输入不等于修改完成的文案，**无remaining blocker**。
独立执行新7case：7 passed，73.9ms。最终静态复审browser定位与muted断言通过，未重复测试。

## 浏览器限制与部署前置条件

仅尝试以下1个isolated fixture case：

```sh
NODE_PATH=/tmp/ase-ui-test-deps/node_modules node --test --test-reporter=spec --test-name-pattern='task detail renders every round with QA findings and Coder feedback lineage' tests/team_view/browser/execution-history.test.cjs
```

环境没有playwright，加载时报MODULE_NOT_FOUND，浏览器未启动。按root要求没有安装依赖或
换外部浏览器。**浏览器实测尚未完成**；不能把Node/静态校验称为视觉验收。

本任务无生产API、审批、数据库、候选worktree、服务操作或提交。root正在通过原K1公开恢复
流程，不为纯前端补丁中断它。服务静态资源在启动时捕获，因此提交本补丁不代表已部署。
root统一提交后，应在当前执行安全结束、服务可受控维护时加载新版本并刷新浏览器；不需
重新创建需求、重写历史或补审批。当前原K1进度和授权继续遵守自身精确方案。

最终diff只涉及产物反馈说明、新窄Node测试、旧browser正向fixture、live-team-view父类型
契约与本任务文档。回滚相同展示改动并受控部署，存量事实保持不变。
