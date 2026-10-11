# 增量验证与交付说明

## 修复内容

core 新 resolution 原先未进入 engineeringResolutionLabels，导致人工授权按钮被 unknown-kind
门禁隐藏，自动 RESOLVED 的决定也被忽略。两个新 missing proof 在当前区、历史和复制报告
落入“未识别检查项”。只补枚举不足以让用户理解本次决定，所以增加共享窗口说明：原窗口、
下一次窗口、冻结上限、扩窗次数、一次原任务剩余工作额度及保留原需求/进度/历史。

知识准备使用“让平台处理知识准备”入口；人工方案显示“扩大知识准备窗口并继续”。窗口事实
直接显示，工程技术摘要继续折叠。自动策略与人工决定区别保留到当前、完整历史和复制报告。
工程负责人/平台维护者负责事项中文明确。达到工作或窗口上限不展示必败处理/继续按钮，旧
HANDLE 闭包遇到新的精确耗尽 proof 也拒绝提交。

## Red → green

最初新增 8 个 DOM case 全部失败，准确暴露缺少窗口说明、未知 resolution 导致按钮消失、
自动决定未识别、missing 中文缺失与产品入口命名不一致。最小前端实现后 8 个全部通过。
后续补齐工作预算、第二次/最后扩窗、历史、复制授权来源、陈旧 HANDLE 及原门禁回归，目前
新增知识准备专项共 12 个。

最终相关 7 文件 **201 passed**，只使用 DOM 假数据，不调用真实模型或生产服务：

```sh
node --test --test-reporter=dot \
  tests/team_view/engineering-wait.test.cjs \
  tests/team_view/product-execution.test.cjs \
  tests/team_view/operation-capabilities.test.cjs \
  tests/team_view/delivery-status.test.cjs \
  tests/team_view/operation-progress.test.cjs \
  tests/team_view/knowledge-preparation-timeout.test.cjs \
  tests/team_view/knowledge-gap.test.cjs
```

独立 reviewer 建议“另行精确资源授权”不能暗示页面已有追加入口。按该建议把窗口耗尽的复查
说明改为原因修复、工程资源重新评估，并明确本页没有追加窗口授权入口。该最后文案修改后，
`engineering-wait.test.cjs` 的 **83 个测试**再通过。JS syntax 与 diff check 通过：

```sh
node --test --test-reporter=dot tests/team_view/engineering-wait.test.cjs
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```

原精确门禁保留，并新增知识证据防御检查。测试覆盖 Project/checkpoint/proof/source、已撤回
manual permission、read freshness、服务能力、当前 Operation、错误 scope/Requirement、缺失
evidence 与无效冻结窗口。提交仍只有现有 typed exact binding + kind + proof SHA，没有
timeout override、process_stopped 或 operator_id。

无 MySQL/全量测试，无生产操作，无 core/domain/schema 修改。root 负责新的 Python 历史字段
和精确 evidence 相等校验；本任务没有回退其他共享工作区改动。

## 存量数据处置

无需改库或重写旧 Operation，刷新现存原需求即可读取新 typed proof/decision 的中文展示。
旧终态知识 timeout 继续使用已有原需求恢复路径，不因为旧英文文本伪造新 claim/proof。
历史缺少窗口字段只保留当次已有记录，不根据热配置推算。

## 回滚 / 限制

回滚时窗口决定入口及文案一起撤回，保留原事实 reader、审计和工作现场。不重建需求或重置
额度。本页没有调整冻结窗口/工作额度的资源授权功能；达到上限需要工程负责人分析原因和
另行评估方案。前端的精确匹配与数字校验是防御展示，实际安全准入和消费仍由服务端执行。
root 对 phase 和本 UI 进行独立 review，完成后统一提交。

## 已核验的 legacy knowledge 父绑定

root 复现旧 QA continuation 的知识作用域为 task ID，但父交付仍为原 Requirement。
core 新增可选 delivery_requirement_id，由服务端严格核验旧 gap/snapshot/native 父归属后填写。
UI 仅使用 `(delivery_requirement_id ?? requirement_id) === request.id`；不按Task命名猜父归属。
新增正确父绑定正例及错误、null、缺失父绑定反例，先 red 再 green；显式错误父绑定不能
回退到 native requirement。最终相关 7 个 DOM 文件共 **202 passed**。
