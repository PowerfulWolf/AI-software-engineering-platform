# 实现

从现有 producer 确认 14 条固定英文 `next_action`，逐条加入 `blocker_text.py::_EXACT` 与
`app.js::humanizeBlockingText` 的精确映射。没有改变 `multi_directory/service.py`、阶段流转、
重试预算、API 字段、Schema、审批准入或任何 persisted fact。

浏览器执行摘要的原因/下一步、阻塞区建议操作、历史 Operation 下一步及工程历史下一步现在
调用既有 renderer，兼容尚未重启的旧 server 投影。翻译函数仅返回显示值，原事实对象保持不变。
动态错误与未知正文使用原有逻辑，未加入新宽泛匹配。

Python 参数化测试验证 14 条精确提示以及用户引用不被替换，并实际运行浏览器函数验证两端
输出相同。轻量 DOM 验证 summary 与 suggested action 路径；真实浏览器验证待产品审批页面
中文、历史记录中文、原 snapshot/Operation 内容不变及既有审批按钮保持。

对修改文件运行 strict mypy 时发现两处旧测试缺少 `str | None` 的显式 None 断言，只补了
`assert localized is not None`，未改变生产行为或既有测试预期。

独立 review 补齐初始化 checkpoint 字典中的 `Prepare every selected directory.`，该提示没有
使用 `next_action=` 关键字写法，首轮关键字检查未涵盖。最终有限集合为 14 条，包含此准备提示。
