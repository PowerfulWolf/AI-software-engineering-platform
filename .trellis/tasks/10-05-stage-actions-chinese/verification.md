# 增量验证记录

## Red

先添加契约与 DOM 回归，在修改生产映射或 renderer 前执行：

```text
.venv/bin/pytest -q tests/team_view/test_blocker_text.py --tb=short
14 failed, 18 passed

node --test tests/team_view/product-execution.test.cjs
1 failed, 7 passed

NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules \
  node --test tests/team_view/browser/product-execution.test.cjs
1 failed, 1 passed
```

最初 13 条固定英文提示和实际 JavaScript renderer 均未得到预期中文；DOM 在执行摘要中观察到
`Review product_spec and approve this exact checkpoint, or reply with revisions.`。

独立 review 另确认初始化字典中的 `Prepare every selected directory.`，补入同一精确集合后
最终为 14 条提示，Python green 为 33 项。此补齐只增加映射与 fixture，没有修改 DOM 路径，
因此不重复已通过的两个 DOM 测试文件。

## Green

```text
.venv/bin/pytest -q tests/team_view/test_blocker_text.py --tb=short
33 passed

node --test tests/team_view/product-execution.test.cjs
8 passed

NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules \
  node --test tests/team_view/browser/product-execution.test.cjs
2 passed, no unhandled browser errors

.venv/bin/ruff check src/ai_software_engineer/team_view/blocker_text.py \
  tests/team_view/test_blocker_text.py
passed

.venv/bin/ruff format --check src/ai_software_engineer/team_view/blocker_text.py \
  tests/team_view/test_blocker_text.py
2 files already formatted

.venv/bin/mypy src/ai_software_engineer/team_view/blocker_text.py \
  tests/team_view/test_blocker_text.py
Success: no issues found in 2 source files

node --check src/ai_software_engineer/team_view/app.js
git diff --check
passed
```

只运行上述三个相关测试文件与局部静态检查，未运行全量测试。真实浏览器验证“批准 ProductSpec
并开始交付”按钮仍存在，原 snapshot.execution.next_action 及 Operation.result.next_action
仍为原英文；没有点击生产审批或改任何生产数据。

## 存量数据处置、风险与回滚

无需迁移或改库。journal、Task、Operation、checkpoint、审批、计数、诊断及历史 bytes/hash
全部保持。更新前端资产后刷新页面即可兼容旧投影；Python reader 仅在当前 Operation 自然
结束且服务空闲后重启。已批准需求继续原流程，不需要重建或重复审批。

未知正文及动态错误不在这 14 条新增精确映射范围内。回滚恢复本次展示提交，服务空闲时重启
reader 并刷新前端，不更改任何持久化交付事实。
