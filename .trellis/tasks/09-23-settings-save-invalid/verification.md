# 增量验证与交付状态

- `node --test tests/team_view/ui.test.cjs tests/team_view/readiness.test.cjs`：25/25 通过；旧版或缺失 Settings 契约版本时，页面提示重启、不发 PUT、不丢草稿；正常版本的保存与原有失败反馈继续通过。
- `NODE_PATH=<Codex bundled node_modules> node --test tests/team_view/browser/settings-layout.test.cjs`：3/3 通过；Chrome 在受限沙箱外运行，新增真实浏览器的旧服务阻断回归。
- `.venv/bin/pytest -q tests/web_console/test_transport.py::test_console_host_missing_config_starts_with_visible_defaults`：1/1 通过，Settings GET 返回版本标记；仅有既存依赖弃用警告。
- `.venv/bin/ruff check`、`.venv/bin/mypy`（受影响 Python 文件）、`node --check`（受影响 JS 文件）、`sh -n scripts/ase-console-service.sh`、`git diff --check`：通过。按用户要求未运行全量测试。

现场证据：旧服务的只读 GET 无契约标记；用户先前人工重启后，设置保存恢复，证明根因为旧 Python 进程与新版静态 UI 不匹配。本次没有对真实服务发测试性 PUT。

存量数据处置：未更改配置文件、`runtime.env`、Requirement、Task、Operation、审批或数据库事实，无需迁移或修复存量记录。尝试从当前受限工具会话重启服务后，子进程随会话结束被回收；用户随后在自己的终端重新启动。只读现场校验：受管服务持续运行，GET Settings 返回 `settings_contract_version=1`、`config_source=saved`、`restart_required=false`。此前用户已确认重启后正常保存；本次没有对真实服务发测试性 PUT。

已知风险：若以后变更 Settings 请求/响应契约但忘记同步递增标记及两端测试，保护无法识别新漂移。回滚方式：还原本次提交，再通过相同受管脚本重启；配置和密钥无需回滚。
