# 客户端读调度设计

## 调用链与端口

`refresh → refreshSnapshot → readTeamJson → withTeamRead → fetch + body → exact验证与summary发布`
以及 `renderDetail → readSelectedTeamDetail → readTeamJson → withTeamRead → complete detail验证`
共用浏览器 `teamReadFlight`。辅助 Console、Operations、preparation reads不占此端口。

`waitForTeamRead(signal)`只保存轻量resume callback到Set；abort立即移除并reject。HTTP完成
清理实际owner后唤醒当前等待者，每个在while中重新争取；取消的导航不排成长队或绑定慢
promise的累计回调。正常调用最多一个refresh和最新正文等待者；无新的业务queue/state。

summary的`publish`在owner内完成精确验证、snapshot赋值与source更新，之后才唤醒正文。
正文`current`在实际GET前、读完body后再次验证当前selection/source，不发已失效locator。
摘要也必须传入superseded/current；否则旧Project在等待正文结束后仍先发旧GET，拖住最新
Project。已进入旧GET与尚在客户端等待是不同事实：前者仍等待完整HTTP并丢弃旧发布，后者
可以在发GET前跳过。两类场景各自有精确请求次数回归。
原summary latest Project drain仍在原refreshFlight处理，不增加新的导航owner或取消辅助事实。

## 有限外部busy

只解析固定错误code，不呈现服务异常message。TEAM_READ_IN_PROGRESS最多额外重试三次，
延迟1、2、4秒，每次同frozen owner并重过读调度；busy等待不占Team读取owner。单一40秒
原正文deadline包括排队与退避；close/source变更abort会释放timer和等待callback。

真正不可用、409、body/schema/scope失败保留原分类并停止自动重试。已成功同source正文
继续只读取一次。waiting/error均不能为Product批准提供READY正文；手动retry重新绑定当前
source，原精确批准与submitOperation recheck不变。全部原历史和文本保持完整。

## 失败/回滚与验证范围

这是浏览器HTTP协调，不是服务worker生命周期证明。HTTPabort后服务可能仍在读取；新GET
必须继续接受后端busy，不提前释放后端gate、不从active lease空推断读取完成。

无API、Schema或持久化变更；恢复部署只需受控加载资产后刷新浏览器。回滚app.js/spec/test
提交并刷新浏览器，不改SQL/Requirement/Task/Operation/批准/工作区。
