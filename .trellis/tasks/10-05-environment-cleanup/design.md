# 设计与操作边界

## 平台缺口

当前ProjectRegistry只有create/register/open/discover。直接移动sidecar会让同名create或配置默认Project重用原ID，且丢失旧Requirement retirement读取，不能作为永久删除。

## 最小闭环

ProjectWorkspaceRegistry.retire_empty接受精确ID/manifest摘要、可信Product主体及必填停止guard。内部验证全部Requirement history和retirement、没有任何Task/角色执行目录事实，完整文件inventory绑定。Team永久retirement先落盘，原Project sidecar随后原子归档；重启可完成同一未完成移动，旧ID的register/open/create均拒绝，discover过滤。归档不改原manifest的绝对路径/字节，只作不可执行历史取证。

root停止Console服务、核验所有Operation idle、精确Project默认配置、完整目录及锁，再调用typed入口。当前Project所有历史仅Product讨论，无Task/Artifact/Run，唯一K1已retired；不得将可见列表0当普遍删除授权。

## 临时清理

受控清单对路径绑定uid/dev/inode/mtime/type；删除前重新检查lsof和进程引用，目录不跟随symlink。425个普通临时文件已清理。保留seed-preflight完整Git及binary patch/index/HEAD清单，原子移到外置maintenance；浏览器工具原子移到Library/Caches/ase-validation/node，Chrome启动已验证。pytest缓存等最后增量验证结束后删除。

## 验证与回滚

增量正向、stale/权限/活跃/损坏/新旧身份拒绝、重启幂等和archive完整性。Project永久退休不可通过删receipt或回退旧版本恢复。源仓库与独立worktree不动，其他Project与Task/候选事实逐项前后比较。缓存可重建，唯一未提交的测试现场已保留。
