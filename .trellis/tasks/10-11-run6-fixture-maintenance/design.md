# 一次性维护设计

`fixture_correction.py` 只面向 plan 中的 Task/run/work/path，不提供通用维修 API。
`MaintenancePlan` 绑定 Task/intent/queue step、invocation start、真实 capture start/stop、
完整 inventory、文件前后摘要、diff 摘要、HEAD/分支/index 和权限模式。

读取通过现有 Task flock、MySQL idle-task fence、既有 queue facts 和
`validate_capture_stop`。不初始化 schema；状态必须仍为 IMPLEMENTING/attempt6 与
WAITING_DEPENDENCY/EXECUTION_UNCERTAIN，不能存在已接受产物、outcome 或 receipt。
prepare 两次读同一组完整事实后，只在这个隔离任务目录写计划和脱敏补丁。

apply 只接受已冻结 plan digest。受控 sidecar 的 `state/external-test-maintenance/<digest>/`
先不可变发布 plan、完整 correction.patch、before.py、after.py、authorization.json，
并追加唯一 `HumanActionEvent(MODIFY_TESTS)`。审计文件 0600；正文不提交仓库。

源路径逐层 nofollow 打开，读取验证 fd 与命名文件的 inode/mode/size/mtime/ctime 一致。
唯一测试文件通过同目录私有临时文件、显式 fchmod、fsync 和 dirfd 原子 replace 更新。
后验验证完整 inventory 只改变 exact path，所有 K1 源码重新完整 capture、wire roundtrip、
verify，并校验 Task、队列、HEAD、branch、index 未变，最后发布 completion。

崩溃重放只接受 exact 后态，且必须已有匹配授权、人工事件、完整 plan/diff/before/after。
由完整后 inventory 反推 exact 前 inventory 与计划相等。没有这些记录的外部修改拒绝。
审计事件说明“准备修改”，实际完成以 completion 为准，不能把一次中途失败当成完成。

`verify_isolated.py` 使用真实前态的只读快照，在 disposable clone 上复现全部 28 项变更。
先验证旧 capture 拒绝，再验证一文件修正后 capture/wire/verify。真实目标测试和全文件测试
使用该副本的 src；专用外置 launcher 把子进程也绑定到副本，不依赖宿主密钥或 MySQL。
只保存脱敏 pytest 摘要与哈希，不保存原模型输出、思考或原始测试字面值。

公开补丁是通用 redactor 的展示记录，不能用于执行 apply。它保守遮盖敏感字段赋值，
包括新增的安全属性引用；实际新增代码可由以下明确替换和 `corrected_source` 检查：

```python
        _, foreign_claim = _ledger(tmp_path / "foreign")
        assert foreign_claim.token and foreign_claim.token != claim.token
        for wrong in (
            replace(claim, token=foreign_claim.token),
            replace(claim, token=""),
        ):
```

该表达先经完整 Python 源码检测，再经完整 capture/wire/verify；不修改 redactor 的保守策略。
