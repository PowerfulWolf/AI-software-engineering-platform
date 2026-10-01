# 契约

`RecoveryScopeRequest(progress_artifact_id, progress_sha256, paths, reason)`：paths排序唯一、最多8个exact RelativePath；reason有界脱敏。`ResumeProjectDelivery/ContinueDeliveryIntent.coder_scope_request`可与scope审批配对，不可与plan/repair/UI请求配对；缺省None保持历史身份。

`RecoveryScopeSupplement.request`及`requested_files`可选，后者精确绑定每个path的基线Git blob ID。历史digest排除新增None字段。`NativeRecoverySource.accepted_progress`仅来自当前可恢复run且被StateEvent接纳的sealed CoderProgress；请求必须匹配该artifact ID/SHA。

scope discovery在原policy+deny上检测每个路径，只允许“缺allowlist”，拒绝所有显式deny、symlink、目录、glob、dirty和已经允许的无效请求；Git ls-tree读取metadata，必须regular tracked file，不能读取原policy不允许的内容。新增路径与原dirty omissions合并进入同一个digest。

审批前、capture前、plan admission、execution均以原请求重算。新的请求不能复用内容不同的历史plan。Console scope approval绑定原请求，按钮传回request+digest，后续plan审批仅按immutable plan。

Good：已接纳progress+测试文件→scope审批→plan审批→new Task。Base：无request保留D5。Bad：仅自然语言要求、孤立artifact、任意路径追加、旧Task扩权、过期审批执行。
