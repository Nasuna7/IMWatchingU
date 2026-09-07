# 捕获、OCR 和运行线程

日期：2026-09-05。验证环境：Windows 11 build 26200、Python 3.12.3 x64、PySide6 6.10.3、windows-capture 1.5.0、PyWinRT 3.2.1。依赖解算固定在 `uv.lock`，不是 Windows 10 兼容保证。

窗口捕获使用 WGC，显示器使用 mss。WGC 当前 Python 接口按标题子串寻找窗口，适配器会检查唯一候选及 HWND/PID，拒绝同名歧义；不会静默退回桌面裁剪并声称可以捕获遮挡窗口。显示器坐标保存物理像素位置，ROI 保存相对坐标。

`scripts/probe_capture.py` 创建独立合成窗口并通过 WGC 截取左半 ROI，在本机成功得到 452×347 物理像素彩色帧。此结果仅覆盖这一窗口与当前 DPI，不覆盖混合 DPI、遮挡、窗口移动、显示器拔插、受保护内容或所有 Windows 版本。探测不读取用户其它窗口。

Windows OCR 直接使用 WinRT，不调用 PowerShell。本机可用语言包括 `zh-Hans-CN`、`en-GB`、`ja`。合成中文 + Cerb + 数字样本在开发环境及打包 EXE 的子进程中通过；单次引擎耗时约 78–141ms，仅作链路探测，不代表召回率或 P95 性能验收。首次依赖探测发现缺少 `Windows.Foundation` 投影，已补齐 Foundation 与 Collections 直接依赖。

Tesseract 适配器通过本地进程运行，启动前检查 `chi_sim+eng`，识别请求限时 20 秒；本机没有引擎和模型，实际识别待验收。Windows OCR 默认彩色输入，Tesseract 可灰度、拉伸对比度、暗底反色；原始彩色帧独立保存用于截图。

每次 OCR 在独立 Python 子进程中执行，25 秒上限，停止时旧会话结果丢弃，退出时回收本应用拥有的 OCR 进程。当前每次识别重新启动进程，会产生额外开销；尚未测量参考配置 8 小时性能。

Qt GUI 只接收状态和帧，图像桥只保留一个最新预览槽位，主线程创建 Qt 图像，预览限制到 1280×720。网络运行于单独 asyncio 线程；匹配、模板、轮次、冷却和色块判定的领域代码仅依赖标准库。
