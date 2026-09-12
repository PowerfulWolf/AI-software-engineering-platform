# M16：公司管理、本地文档知识库与设置页

## 阶段目标

把 Web Console 从“需求交付入口”补全为 v0.1 的本地管理入口：用户可以接入公司、导入公司知识，
并维护当前生产 Host 支持的无密钥配置。飞书 Wiki/Docs 连接器不在本阶段范围内。

## 完成能力

- 浏览器创建 Company，使用既有不可变 `CompanyWorkspace` 身份和公司隔离边界；
- 导入 Markdown、TXT、PDF、DOCX，保存原文件、规范化 `content.md` 和内容寻址 manifest；
- 明确选择哪些文档进入新需求上下文，未选择文档不会被递归或隐式加载；
- 设置页维护平台数据根、活动公司、公司知识选择、MySQL DSN 变量名、模型路由、Codex
  可执行文件、真实模型开关和 Console 端口；
- 设置只保存 secret 环境变量名，页面只显示“已提供/未提供”，不读取或回显 DSN/API Key；
- 切换新 `platform_root` 时只初始化当前 Company，不静默迁移旧 organization、知识、项目、需求或
  worktree，并明确要求重启 Host；
- README、生产部署、架构、JSON Schema、AGENTS 和 Trellis 可执行契约同步更新。

## 关键不变量

1. 公司知识属于 Company sidecar，不属于 Agent、平台源码仓库或目标代码仓库；
2. 文档原始正文不经模型静默改写，规范化结果可由来源哈希和 manifest 重验；
3. 上传不接受服务端文件路径，仅接收受限浏览器正文；单文件原始上限 10 MB，规范化正文上限
   256 KB；
4. 配置变化不热切换已构造的 Host，也不重新解释已有批准；页面以 `restart_required` 明示边界；
5. Web 管理接口仍限定可信本机 loopback、同源和单用户，不扩展成远程多租户控制面。

## 验证

- 本次 focused Python cases：96 passed；
- 前端 Node DOM 交互测试：通过；
- Ruff format/check、strict Mypy、`git diff --check`：通过；
- `uv lock --check --offline` 与离线 sdist/wheel 构建：通过；
- 2026-09-12 人工执行全量 pytest 并报告通过。

## 后续边界

- 飞书 Wiki/Docs、其他远程知识连接器及增量同步留待后续任务；
- v0.1 不做 AI 自动摘要或知识改写，Agent 使用人工明确选择的规范化全文；
- 当前配置保存后通过重启生效；安全自动重启仍依赖未来的 Keychain/Secret Service 与服务托管能力；
- Web Console 仍不自动 merge、push 或 deploy Candidate。
