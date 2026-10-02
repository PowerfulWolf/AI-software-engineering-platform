# 定位与契约

优先假设：pytest tmp_path setup 探测 sandbox 未授权的临时目录元数据；其次是 private
MySQL socket 可达性；第三是候选公共 fixture。真实 toy sandbox fixture 使用同一可信 runner
与 scratch 布局，先加入 tmp_path，再检查最小异常栈（仅包内函数/行号，无消息或 locals）。
不扩展根目录、网络或通用 Agent 能力；如需改变执行契约，先记录精确设计，再改代码。
存量只能通过新 hash-bound plan / approval 继续，旧命令 ERROR 不可视为业务 FAIL 或 PASS。

## 已证实根因与实现

外层 TMPDIR=scratch 让 Codex 的 :tmpdir=none 与显式 scratch=write 指向同一路径，deny 优先，
pytest basetemp.mkdir 在 setup 失败。最小真实沙箱两个根目录均红；原候选单节点只移除外层
TMPDIR 即绿。新增纯 python_mysql_sandbox_environment() 与命令编码同属 capability 模块，
生产执行器与真实边界 fixture 共用；不继承宿主 TMPDIR 或完整 env。可信 runner 已在内部
设置 TMPDIR=scratch，保持私有临时文件与缓存位置。capability wire/旧 digest 不变；旧计划
已消费，空闲激活后仅生成新精确计划与审批。新增反例显式注入错误 TMPDIR 验证仍 fail closed。
