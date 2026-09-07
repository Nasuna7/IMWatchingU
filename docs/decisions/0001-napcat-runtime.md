# NapCat 适配调查与发布门槛

日期：2026-09-05。状态：源码契约已探测，受管理运行时尚未完成；不视为 M0 通过。

通过 Git 获取并检查的提交是 `eecb02140f77b58cb70a3ec8c0b2e816a346f3fe`。GitHub API 曾返回限流 403，之后使用 Git 获取固定提交进行源码检查。没有将 `main` 的当前行为写成已验证发行版本。

源码依据：

- [管理鉴权](https://github.com/NapNeko/NapCatQQ/blob/eecb02140f77b58cb70a3ec8c0b2e816a346f3fe/packages/napcat-webui-backend/src/helper/SignToken.ts)：管理口的口令摘要使用 SHA-256，管理会话凭据独立于 OneBot Token。
- [登录路由](https://github.com/NapNeko/NapCatQQ/blob/eecb02140f77b58cb70a3ec8c0b2e816a346f3fe/packages/napcat-webui-backend/src/router/QQLogin.ts)及 [登录状态处理](https://github.com/NapNeko/NapCatQQ/blob/eecb02140f77b58cb70a3ec8c0b2e816a346f3fe/packages/napcat-webui-backend/src/api/QQLogin.ts)：原生页按实际状态显示二维码、已登录或离线，不虚构手机确认阶段和二维码倒计时。
- [OneBot 配置](https://github.com/NapNeko/NapCatQQ/blob/eecb02140f77b58cb70a3ec8c0b2e816a346f3fe/packages/napcat-onebot/config/config.ts)：正向 WS 配置与管理 HTTP 是独立通道。
- [官方 Shell 启动说明](https://napneko.github.io/guide/boot/Shell)：Windows 发行包存在不同启动方式，不能统一假定任意目录都有同一个可执行入口。

当前实现了 OneBot echo 关联、有限 pending map、鉴权、账号/目标核验、消息段数组、分项回执及断连/超时语义。自动重连不自动重试发送；重连账号不一致即断开。

`NapCatConfigService` 是带阶段日志的补偿流程，已通过假适配器的写入、重启、校验、回滚失败测试。它尚未接入真实文件/进程适配器或页面，因此不能宣称应用内自动配置完成。`RuntimeCatalog` 校验固定清单的包摘要及路径，拒绝未知包；`packaging/runtime-manifest.json` 的已验证包列表为空，明确禁止把未知包当作发布支持版本。

受管理模式仍需：选择官方固定发行包与 QQ 组合、记录完整摘要和可再分发条件、独立目录和 ACL、配置路径/启动参数契约、Job Object 进程归属、草稿与生效值 UI、崩溃恢复、真实配置回读/回滚及扫码/好友/群文字与 PNG 验收。没有启动 QQ、修改外部 NapCat 目录或发送真实消息。
