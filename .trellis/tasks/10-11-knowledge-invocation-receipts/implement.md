# 实施顺序

1. 通过真实 KnowledgeConsultationService + fake limit client 捕获全七角色缺少失败start的红测。
2. 添加独立 typed intent/outcome、immutable record observer、exact replay guard。
3. 在所有 knowledge `_call` 接入，不扩大 StructuredModelClient 输入与工具权限。
4. 增量覆盖真实 owned structured runner 的记录顺序、失败、重放与安全反例。
5. 同步独立 schemas / active-knowledge spec，独立review后提交。
