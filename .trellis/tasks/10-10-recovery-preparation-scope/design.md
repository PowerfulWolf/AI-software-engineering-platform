# 同步准备边界

沿用 ContextVar、有界 complete-text key 与 finally reset，不新增缓存实现或 budget。
六个方法只执行同步准备/核验，均在 provider 运行之前结束。nested scope 共享当前纯检测
facts，standalone call 独立建立/释放。所有原方法体和新鲜观察顺序保持原样。

测试使用真实授权、Builder、sealing、allocator、seed 与文件 record stores；替换外部事实、
Git 与 MySQL authority 端口为有计数的离线 seam。计数完整 source/patch scanner 与干净
generic regex；同时检查真实重复 facts、capture 与 getters。失败测试改变实际文件正文及
模拟 fenced second observation drift，确保缓存不能批准旧结果。provider 边界测试在
authorize 返回后验证 ContextVar 为 None。

未提供 .trellis/scripts/get_context.py，按 core index、Python/runtime、recovery 与共享
thinking guides 手动定位规范。No Schema/state/permission/authority change。
