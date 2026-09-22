# 验证记录

## 增量检查

```text
node --check src/ai_software_engineer/team_view/app.js
PASS

node --test tests/team_view/ui.test.cjs tests/team_view/readiness.test.cjs
25 passed, 0 failed

NODE_PATH=<bundled-runtime>/node_modules node --test \
  tests/team_view/browser/settings-layout.test.cjs \
  tests/team_view/browser/design-budget.test.cjs
5 passed, 0 failed

git diff --check
PASS
```

浏览器测试在 1440、768、390px 验证基础配置和模型路由无横向溢出；同时验证 Basic/MySQL 左右基线、两个 MySQL 模块、模型/Agent disclosure 数量、七个 Agent 策略以及两行 fallback 操作列和按钮宽度一致。

## 契约与存量数据

- Settings API、ProductionConfig、Schema、secret store、保存和重启流程均未改变。
- `live_model_execution` 仍写入原字段并由原后端安全闸门执行；仅修正显示名称和解释。
- 本次只改变浏览器 DOM/CSS，不修改 Requirement、Task、Operation、审批、配置文件或 MySQL 事实，因此无需存量数据修复或迁移。

## 已知风险与回滚

主要风险是不同系统字体导致摘要文字提前换行；固定网格、`min-width: 0` 和三个真实浏览器宽度已覆盖溢出边界。若需回滚，恢复提交 `6ec25b1` 之后的前端、测试和规范变更即可，不涉及数据回滚。
