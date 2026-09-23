# 详情设计

在每个 Agent disclosure 内用统一宽度的纵向内容区：主模型标签/帮助、选择器、当前路由元信息；细分割线后为备用模型标题/数量、紧凑行列表、添加选择器。选中主模型只显示 `model`，选项仍显示完整 provider/model/effort/type，避免不同路由看起来相同；元信息独立展示。备用行使用序号、两行身份和三枚有边框的图标按钮，图标保留完整 aria-label/title。修改只发生在渲染/样式，不改 draft 的 route identity 或操作函数。
