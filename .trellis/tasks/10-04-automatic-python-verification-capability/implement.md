# 实现

`CandidateVerificationEntry.propose()` 现在在没有显式 UI/Python 选择时调用
`_automatic_python_mysql_tests()`。该函数读取当前候选的 sealed Plan/implementation artifacts 和
RepositoryProfile，只接受 exact `tests/**/test_*.py::node` selector，并合并重复节点的 criterion
集合；覆盖不完整或超过受控上限时返回 `None`，继续要求人工选择。派生的 selections 进入现有
`_python_capability()`，所以 Docker、Python runtime、runner、deny inventory 和候选 SHA 仍由既有
discovery 绑定，计划仍走 exact human approval。

新增 `tests/recovery/test_python_verification_plan.py` 覆盖完整映射和不完整映射。未修改现有
delivery/Task/StateEvent/Artifact/approval 数据。
