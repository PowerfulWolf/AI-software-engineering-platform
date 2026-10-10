# 终态恢复的源码敏感信息校验一致性

## 目标与实证

原 K1 的有效执行基线核验已通过，但正式只读恢复 capture 在普通 log redaction 上拒绝
运行时生成 token 的合法源码表达式。相同现场能通过 manager mutation 的 conservative
source/patch detector。终态恢复应复用该已版本化检测规则，保存完整原字节与摘要。

## 范围与验收

- Git tracked/nonignored capture 与 CapturedChanges 使用现有 patch_secret_occurrences；
  不放宽路径、变更类型、字节上限或实际密钥保护。
- 源码秘密字面量、未知 dotted reference、patch metadata 凭证仍拒绝。
- 只读捕获不修改 HEAD、index、工作区、旧 Task 或 verdict。
- 真实原 K1 现场仅做只读复核；正式恢复仍通过当前 exact 计划及用户批准。

## 允许路径、验证与回滚

git/worktree.py、recovery/models.py、tests/git/test_recovery_source_content.py 与既有
capture/model 增量测试、delivery-recovery spec。本次不扩展 redaction parser。
回滚保留已经封存计划的原内容/摘要，不能改写历史记录。
