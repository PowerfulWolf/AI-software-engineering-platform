# 根因与防复发

## 已复现的事实

新服务 PID 31400 已加载前次修复。10月9日后续三次操作完成进程调查（sealed survey blockers=[]），
然后 capture_mutations 因 secret_assignment 误拒绝两个正常 Python 源码文件。最新失败操作
`operation_1b75e1136e41771035f0f2b03c28629a`，FAILED/MANAGER_FAILURE/WorktreeCaptureRejected。
用户所复制 `5089ac77...` 是随后 HANDLE 的历史未知处理报告，未含准备失败。

首次 survey incomplete 没有留异常类别/errno，无法追溯证明竞态原因；不能将其推断成后续
捕获错误。后三次完整 survey 与真实 capture 调用链已足以区分两种事实。

## 根因

1. 跨文本边界隐式假设：日志凭证正则用于完整源码，使属性引用/路径表达式冒充秘密值。
2. 跨层遗漏风险：body、patch、wire、baseline replay、required Context 反复检查同一内容，
   仅修一个节点会把用户推进到下一次相同假阻塞。
3. 前端只读取 SUCCEEDED 的 preparation，FAILED/INTERRUPTED 直接丢弃，历史泛化报告盖住实际失败。

## 失败分析与修复边界

不能直接全局放宽 secret_assignment 或假定任意 dotted value是代码；真实.env和JWT会绕过。
独立复核进一步发现初稿跨 quoted/comment/f-string和diff metadata的豁免漏洞，均在提交前修复。
source_path只存在内存，不改wire/hash；只能由actual RelativePath父级授予.py AST/token模式。
源码例外不适用于字符串/注释/插值/配置，强特征无条件扫描整个原文；diff计数/解析资源异常保守。
用排序span游标消除O(matches×strings)；246KB/6000行例测约0.085s。

## 防复发

- 每个恢复修改都沿 capture→wire→plan→replay→required Context 追踪同一完整原输入。
- 本轮36个source边界用例覆盖quoted/f/嵌套字符串、.env、强key、diff header/count和parser限制。
- 三个delivery角色使用真实Git完整草稿与Context测试，typed Console等待无plan/approval。
- 当前失败/复制报告/11类外来与stale绑定浏览器验证，保留重新检查原需求的入口。
- 组织知识写入legacy-execution-rescue/web-console/recovery-thinking/user guide。

v1 recovery/普通日志/知识/Evidence仍使用原通用规则，不声称扩展所有语言或旧恢复协议。
无数据库迁移、历史重写、需求重建或执行审批。旧真实结果仍UNKNOWN。
