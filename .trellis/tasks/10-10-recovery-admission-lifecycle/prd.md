# 首轮恢复准入的生命周期

## 已复现事实

K1恢复Task task_recovery_edc70b3d943c52d85a079da433d43934 第一轮生成合法
coder-progress art_coder_1cbfcc0ef2253347573fa3b712088a76，并正常 CONTINUE_REQUIRED→
QUEUED→IMPLEMENTING。第二轮 run_7c1dccc000b848f0bcacbe02c6840b23 在provider前被
“Codex worktree violated the execution precondition”拒绝。生产每个request创建adapter，
adapter-local consumed flag又为false，重复调用只允许attempt1的RecoverySeedService.authorize。
旧测试只复用同一adapter，没有覆盖真正的生产生命周期。

## 修复范围

InitialWorkspaceAdmission默认仍每个适用Run检查，以保留BaselineInitialWorkspaceAdmission
对当前claim/完整现场/基线和已接纳checkpoint的fresh校验。新增显式typed首CoderRun scope
wrapper仅用于terminal recovery seed/interruption。Codex/Responses共同解析该scope；
后续正常progress/QA返工沿原HEAD/路径/权限/checkpoint验证，不复用seed授权或跳过安全检查。
禁止通过通用attempt==1判断跳过所有baseline准入，也不依赖adapter对象内的consumed bool。

## 验收

- 真实Git+新adapter每轮创建，seed首轮一次；accepted coder-progress第二轮可到provider。
- 未申报dirty paths、HEAD漂移、checkpoint路径漂移仍provider前拒绝；QA/Review返工从候选
  干净输入走正常检查，不能重放seed。Codex与Responses行为一致。
- 默认baseline admission每个Run（含later attempts）仍调用；拒绝/失败无provider调用。
- 真实Recovery entry配置typed scope（包括interruption），fake factory仍必须显式honor原port。
- 仅关联增量pytest/Ruff/format/strict Mypy。

## 存量处置与回滚

原K1及恢复Task终态不重置；保留最新合法progress/完整dirty worktree/失败run历史。
受控加载修复后，通过同Requirement公开Continue重新准备精确恢复方案，明确新的输入基线和
保留现场，再批准；不重复已消费plan、不直接改库。若公开流程不能从该合法progress保留，
需继续修复该精确路径而不是丢弃开发进度。
回滚scope/adapter接线，不删除任何旧记录；旧版本可能再次误拒正常恢复续跑。
