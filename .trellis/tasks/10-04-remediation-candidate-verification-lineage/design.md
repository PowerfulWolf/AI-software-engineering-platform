# 设计

`validate_candidate_artifact_lineage` 统一验证候选 Artifact 的 Plan、supersedes 和反馈父链。
首次候选只允许 Plan 与 Coder progress 父项；修复候选必须 supersedes 前一版
Implementation，并且包含一个同一旧 candidate 的 QA FAIL 或 Review REJECT。Review finding
还必须指向该旧 candidate 的 QA PASS。Native source reader、Verifier runner 和受控 prompt
绑定共同使用该契约，避免只在其中一层放宽检查。
