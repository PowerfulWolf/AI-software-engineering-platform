# 同一需求未接纳开发报告的可读恢复入口

目标：让产品使用者从当前事实理解报告被拒、完整草稿是否已核验，以及精确批准后如何继续；复用已有准备、工程 PAUSE 和独立 RESUME，不引入新恢复引擎。

范围：Console UI、中文 read-side 原因、相关真实 JS 控件与 Python/JS parity 测试。运行服务、生产数据库和保留的 Coder checkout 不在实现操作范围内。

验收：

- INVALID_OUTPUT 仅在 Console contract >=7 允许提交；旧 WORK_INTERRUPTED >=5 保持兼容。版本撤回、异 Project、原 scope/proof/cause 漂移和已接纳结果均零写。
- completed proof 的原错误与普通额度原因精确对应；同基线保留 target-free 输入，不同目标复用完整规范审阅、冲突 reapply 和人类 PAUSE。
- 当前 SOURCE 恢复方案与同基线方案择最新精确方案，既往调查标为历史，不重复呈现无用操作。
- WORK_SLICE 固定枚举展示中文原因；旧 GIT_CONTRACT 不猜具体子因、不宣称完整原 JSON 可读或业务已完成。
- 只跑相关增量测试；独立 reviewer 审查后才集成。

回滚：通过受控关闭部署兼容版本。保留所有旧执行、审批和新恢复记录；不得删除记录或复活终态任务。
