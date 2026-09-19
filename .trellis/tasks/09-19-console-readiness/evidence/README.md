# Console readiness 工程证据

原报告由独立 QA/Reviewer 在前次修复会话产生，归档保留原始字节和哈希。
这些是工程验证记录，不是平台 ArtifactStore 中的正式 verdict，也不会驱动平台 Task 状态迁移。

最终报告：[QA v4](ase-console-readiness-qa-v4.md)、[Review v3](ase-console-readiness-review-v3.md)。
旧报告和各轮 red/green 日志保留以追溯发现及修复。原文中的临时路径按
[manifest.json](manifest.json) 的 source_path 映射到本目录文件；报告内部引用保持原样。

[reproductions.tar.gz](reproductions.tar.gz) 保存三个中间版本脚本，供复现对应失败测试。
在临时目录解包所需脚本后，以 ASE_READINESS_APP_JS 指向该文件，运行当前
tests/team_view/readiness.test.cjs；旧版本出现预期失败不能作为当前版本失败。
最初基线脚本可从 Git b8983b8 读取，最终版本与完整测试可从 c280310 读取。

完整性核对须逐文件及压缩包计算 SHA-256；解包后的各成员也有独立摘要。

The 8 original test logs are stored as gzip files to retain framework whitespace and byte identity.
The manifest records both the stored gzip digest and the original uncompressed digest; use gzip -dc
to read a log. Independent Markdown reports remain byte-for-byte originals.
