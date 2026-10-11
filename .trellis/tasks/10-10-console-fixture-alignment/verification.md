# 增量验证

原两处失败已由独立研究在b2d2e68干净资产复现。Node interval fixture实际没有等待
refreshFlight，当前Task Chrome fixture实际挂在非交付空scope父需求，均与测试意图不符。

修复等待后完整大型Node用例继续揭示旧断言与现代交互约定不符：审批改用用户可理解的
“执行重启方案/待工程确认/原执行历史”；旧checkpoint按钮已从DOM断开，不能提交；
删除需求后Project操作历史仍保留标题。没有改生产或删掉历史断言，新增旧callback零POST
后显式重新取当前按钮；DOM mock具备连接/断开、正确replaceChildren/remove与根节点身份。

```sh
node --test tests/team_view/ui.test.cjs
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
node --test tests/team_view/browser/task-detail-reading.test.cjs
```

结果分别6/6与4/4通过。QA/Reviewer不同需求两代表行、真实所有Task历史、当前/历史
章节、390px长报告布局、阅读暂停及选区/DOM/scroll保持断言全部继续有效。
独立审核发现当前审批提示仍引用旧section，已重新从当前#detail读取section并断言连接，
保留旧button零POST；再运行Node6/6通过。合并readiness/operation-progress/knowledge
timeout相关Node79/79通过。独立Chrome4/4及Node6/6通过，未见剩余发现。
没有跑全量测试，没有数据库、API、模型或服务操作。回滚仅测试fixture与本规范测试说明。
