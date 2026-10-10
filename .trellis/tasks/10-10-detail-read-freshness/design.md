# 设计

详情header增加独立只读freshness槽，内容根据Team读取问题及绑定的显示来源生成。来源为
Team/Project/selection/as_of；用WeakMap保存DOM槽的来源，不写入后台或浏览器持久化。
槽及其内消息使用既有viewBlock/renderView协调，读取失败/恢复仅替换消息，不替换标题、
overview、正文、讨论草稿或历史行。无问题时槽hidden，不占展示间距。

普通详情渲染绑定最新已接纳snapshot来源；Task阅读暂停时保留原槽和原来源，只更新读取
说明。跨Team/Project/selection的来源不显示，不让旧Task暂停状态混入新实体。消息使用
蓝色信息样式和原生role=status，不用红色阻塞样式。

既有canControlCurrentTeam及exact审批签名继续独立负责控制门禁；helper不能建立或释放
执行权。组织契约由root更新incremental-polling，生产资产仅由root在安全空闲边界加载。
