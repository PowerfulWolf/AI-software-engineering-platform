# 删除自验证项目并清理临时环境

用户明确授权删除 ASE Self Validation 2026-09-29，并清理 tmp 无用文件。目标 Project：project_ase_self_validation_20260929。

## 范围

- 空项目安全退休、从 Project catalog 移除，原身份不能因重启/同名创建误复活；不删除源仓库，不修改旧任务/verdict/审批。
- 平台当前无 Project 删除契约，补最窄的 registry retirement + exact guard +不可变记录+可幂等归档，不扩展为一般Project管理重构。
- 只允许完全停止、无活跃需求且没有任何执行 Task/Artifact/Run 的空 Project；存在执行历史的项目拒绝，另走独立范围评估。此次历史仅一条已删 Product讨论需求。
- 停服务核验后执行；归档完整旧 sidecar，保留旧需求retirement及原manifest字节；旧ID不能重新注册/打开。
- 清理本轮产生的 /tmp/ase-*、ase_*、相关已停止测试目录/快照/patch/日志。保留系统、其他应用、生产服务、源代码及dirty工作；有唯一改动的fixture归档，仍有用的Playwright工具移入稳定缓存。

## 验收

- [ ] registry退休契约、Schema、规范和增量正向/拒绝/幂等/不可复活测试一致。
- [ ] 自验证Project从列表消失，旧身份拒绝，其他Project/需求/候选/Operation事实不变。
- [ ] 归档完整性与源代码未改动验证通过；零生产模型/新需求/直接SQL写入。
- [ ] tmp无用项清理，依赖/dirty项安全保留，记录数量/释放大小及保留位置。
- [ ] 提交推送、空闲更新，真实页面与API增量验收完成。

## 允许路径与回滚

允许project_workspace及新的Project retirement模块、对应tests/Schema、.trellis/spec/core/team-workspace.md及本Task文档。生产修改仅限精确Project退休/归档、稳定测试工具缓存和已确认临时文件。禁止runtime.env内容、secret、sidecar入git；禁止force删除worktree。删除已授权，不重复请求确认。退休不能通过回退旧binary或改manifest复活；新版本保留退休读取能力。临时缓存可重建，dirty现场可从归档取证。
