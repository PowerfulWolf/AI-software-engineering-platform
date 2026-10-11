# 未知原生退出分类

公开 Host 真实本地 child `rc=1`、无可识别提供方诊断仍返回 PROVIDER_UNAVAILABLE/transient=true。
目标：只有完整可信 main diagnostic 识别的临时服务故障才声明临时；未知退出保持原泛化 code、
非临时且不伪装 AUTH。明确 HTTP408/5xx 和连接失败保持可识别服务故障；不扩大stdout/background
或不完整截断诊断的可信范围。Coder/QA/Review独立门、权限、worktree和原历史不变。

验收：错误矩阵/真实adapter注入、现有 native classifier tests，以及 taxonomy公开Host真实child
原先2红变绿。此分类commit独立提交，taxonomy实现/Schema另一个commit。
