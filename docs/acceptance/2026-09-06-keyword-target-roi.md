## Keyword Policies, Multi Targets And Separate ROIs

本次将发送策略从单对象扩展为多对象，同时保持旧 `target` 配置兼容。默认发送配置和关键词级覆盖策略都可以勾选多个好友或群；发送队列会对同一任务的所有对象逐一发送，并按全部回执汇总状态。

关键词规则新增“消息别名”。模板变量 `{keyword}` 优先使用别名，未设置时继续使用原关键词。

监控区域和发送附图区域已分离。OCR 只读取监控区域，文字+截图或纯截图消息使用独立的截图区域。主监控页预览同时显示两块区域；实际框选通过全屏弹窗完成，主预览不再承担精细拖拽入口。

验证：

- `ruff check src tests`
- `pytest -q`：99 passed
- PyInstaller 构建：`dist/keyword-target-roi/IMWatchingU❤/IMWatchingU❤.exe`
- 打包 smoke test：退出码 0
