# 设计

`successor_branch(original, purpose)` 在解析 `ai/<kind>/<slug>` 后，从 slug 尾部移除连续的
平台生成后缀，再追加当前 purpose。这样 `trends-recovery-review-fixes-recovery` 的下一轮
仍从 `trends` 派生。没有后缀的业务 slug 保持原样，`None` 继续表示旧的无命名 Task。

调用方继续负责检查 Git 分支冲突；本修复不做截断、rename、rebase 或历史数据迁移。
