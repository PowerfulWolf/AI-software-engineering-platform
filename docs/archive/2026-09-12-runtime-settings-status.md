# M18：运行设置与状态

## 阶段目标

降低本地 Web Console 的首次使用门槛：配置文件或 MySQL 尚未准备时仍能打开设置入口，用户可从
浏览器填写完整运行参数，并在独立状态页确认 Team Host 是否具备真实交付条件。

## 完成能力

- 配置文件不存在时，以只读内置默认值启动 setup Console，不创建配置、Team 或交付任务；
- 设置页直接接收完整 MySQL DSN 和 Responses provider API Key，Codex CLI 继续使用本机登录；
- 运行变量以 `0600` 原子写入配置文件同目录的 `runtime.env`，接口和页面只返回是否配置，不回显正文；
- `ase-console-service.sh` 启动和重启时自动加载 sibling `runtime.env`；
- 独立状态页展示配置来源、重启要求、交付运行时、真实模型开关、MySQL、Codex、Team workspace、
  团队知识与模型路由状态；
- 进入状态页或手动刷新时才探测 MySQL，团队看板的 5 秒轮询不会重复创建探测连接；
- 保存首次配置时显式准备唯一 Team；交付入口只有在 Host 成功绑定 MySQL 和工作空间后才开放；
- README、生产部署文档、架构说明、AGENTS 和 Trellis 可执行契约同步更新。

## 关键不变量

1. 普通 `ProductionConfig` 仍不保存 DSN/API Key 正文；`runtime.env` 是可信本机 MVP 的可替换存储 seam；
2. 运行变量名必须由当前 typed config 显式引用，任意环境变量注入会被拒绝；
3. 保存后的敏感值不得进入 HTTP response、Operation、日志、仓库或 Team/Project sidecar；
4. 配置和运行变量变化不热改已构造的 Team Host，必须明确重启；
5. 已有但损坏的配置必须失败关闭，不能回退默认值或被页面静默覆盖；
6. setup Console 不启动 Agent，不接受交付操作，只开放配置、状态和安全的只读身份视图。

## 验证

- focused Python cases：45 passed；
- 前端 Node DOM 交互测试：通过；
- Ruff check/format、strict Mypy、启动脚本语法与 `git diff --check`：通过；
- 2026-09-12 人工执行全量 pytest 并报告通过。

## 后续边界

- 当前 `runtime.env` 是本地明文文件；后续以 macOS Keychain/Linux Secret Service 替换存储实现；
- Web Console 仍只监听 loopback，不提供远程访问、RBAC/SSO 或多用户管理；
- 启用模型、MySQL 或目录配置后仍需人工重启服务，不做热切换；
- T033 Reporter、自动 merge、push 和 deploy 不属于本阶段。
