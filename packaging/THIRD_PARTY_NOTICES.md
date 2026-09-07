# 开发构建的第三方组件

当前构建包含 Python、PySide6/Qt、Shiboken、Pillow、NumPy、mss、windows-capture/OpenCV、PyWinRT、httpx、websockets、qrcode 及其锁定依赖。精确 Python 包版本见 `uv.lock`。

开发构建会在本机存在 `D:\NapCat.Shell` 或 `E:\NapCat.Shell` 时，将 NapCat Shell 复制到 `_internal/runtime/NapCat.Shell`，但过滤账号配置、管理端 token、passkey、备份和日志；仍不打包 QQ、Tesseract 可执行文件或语言模型。发行清单中的 verified_packages 仍为空。

当前仅为开发构建。正式发布前须按实际收集文件补齐各组件原始许可证、版权声明、Qt 相关分发义务、对应源代码获取方式与可再分发组件核验；此清单不能代替组件许可证。未完成这些检查前不能标记 M4 通过。
