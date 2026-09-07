# IMWatchingU❤ · Windows 桌面开发版

本目录已从仅含 `legacy/` 的规划项目建立 Python 3.12 + PySide6 原生应用。代码按 `domain / application / infrastructure / runtime / ui` 分层，旧 Node、浏览器页面和 PowerShell 业务脚本不参与新程序运行或打包。

**当前为可运行开发版，不是 PRD 全部 P0 已完成的正式版。** 最新修正见 [功能修正验收记录](docs/acceptance/2026-09-05-function-fixes.md)，原始交付范围见 [重构验收记录](docs/acceptance/2026-09-05-refactor.md)。已接入本地 NapCat Shell 启动与配置读取；自动下载、安装、升级、完整配置事务恢复以及真实 QQ 扫码收发验收仍未完成。

## 启动

本工作区已有 `.venv`，可运行：

```powershell
.\.venv\Scripts\python.exe -m screen_qq_ocr
```

当前登录修正版可双击 `dist/qq-login-fix/IMWatchingU❤/IMWatchingU❤.exe`。旧版仍在 `dist/crop-live/ScreenQQOCR/`、`dist/redesign/ScreenQQOCR/`、`dist/lifecycle/ScreenQQOCR/`、`dist/ScreenQQOCR/` 和 `dist/fixes/ScreenQQOCR/`；请先从旧版托盘菜单退出，再启动新版。需保留整个 `IMWatchingU❤` 文件夹；这是开发构建，未完成干净系统发布验收。

新开发环境使用唯一依赖锁 `uv.lock`：

```powershell
py -3.12 -m pip install uv
py -3.12 -m uv sync --frozen --extra dev
.\.venv\Scripts\python.exe -m screen_qq_ocr
```

首次启动不自动监控、不自动连接 QQ、不自动导入旧规则。默认数据目录是 `%LOCALAPPDATA%/IMWatchingU/`；测试可用 `--data-dir artifacts/local-test` 隔离。构建时若本机存在 `D:\NapCat.Shell` 或 `E:\NapCat.Shell`，发行包会内置到 `_internal/runtime/NapCat.Shell` 并作为默认 NapCat 运行时；账号配置、管理端 token、passkey、备份和日志不会进入发行包。首次没有账号配置时，QQ 登录页会启动 NapCat、生成干净配置并显示二维码，扫码后由 NapCat 落盘账号配置，应用自动记住该账号配置文件。

## 桌面 UI

已按 [Gray / Amber 设计](docs/design/UI-REDESIGN.md)替换桌面界面：炭灰侧栏、橙色背景光晕、柔白卡片，支持深色与跟随系统。标题栏右侧可切换明暗，应用设置中保存外观偏好。监控任务使用卡片切换，规则编辑使用独立弹窗。

下拉列表、数字步进、复选框、标签页、滚动条、右键与托盘菜单、文件选择和错误弹窗使用统一 Qt 自定义样式及 SVG 图标。按钮悬停/按下、页面标题与弹窗使用短时渐变；“减少动画”即时生效。窗口可拖动标题栏、双击最大化或从边缘调整尺寸。

实际界面截图在 `artifacts/visual/`，运行 `.venv/Scripts/python.exe scripts/render_ui.py` 可重新生成隔离的模拟界面，不采集屏幕、不连接 QQ。验收见 [UI 重构记录](docs/acceptance/2026-09-05-ui-redesign.md)。

## 已接通的操作

- 监控：新增多个独立任务，可同时监控不同窗口或同一窗口的不同区域，各自拥有采集线程、OCR 工作进程、裁剪和触发状态。选中任务后设置来源并开始监控；切换任务保留其他任务运行，可单独停止或停止全部。任务列表仅本次运行有效，重启后需重新添加和选择来源。
- 裁剪：预览保留来源原始像素。框外拖拽绘制区域，松手后立即居中并适度缩放，不等待后端采集确认；框内拖动时背景跟随鼠标移动，选框保持固定；八个控制点调整范围。选区外画面压暗，缩放预留微调空间并设倍率上限；Esc 取消当前拖动，重置恢复全画面。运行中修改裁剪会使旧识别失效并恢复当前任务监控。OCR、色块与发送截图均使用裁剪后的画面，最小区域为 16×16 物理像素。
- 采集：修复 mss 显示器附加元数据引起的“已断开”误判；WGC 静态窗口超过两秒仍可使用。窗口最小化、关闭或实际显示器断开仍暂停；同名窗口会拒绝模糊选择。
- 关键词：规则列表可直接调整“目标数量（至少）”并自动保存，也可在编辑区设置，范围 1–999，表示关键词在单帧中的出现次数，区别于连续确认帧数。另含搜索、增删改、批量启停、删除撤销、SQLite 保存、TXT/JSON 导入导出。规则及发送策略由各任务共享；修改后需重新开启关键词监控。
- OCR：默认直接使用 WinRT Windows OCR；Tesseract 使用本地可执行文件及 `chi_sim`、`eng` 模型。设置中选择 `tesseract.exe`；本机尚未安装该引擎，因此未进行真实 Tesseract 验收。
- 色块：独立采样，连续 4 次变化触发，声音 3 秒，冷却不叠音；不依赖 OCR 或 QQ。锁屏/休眠和停止会取消待发送并停止声音。
- 发送：默认策略、逐字段覆盖、字面匹配、连续帧、每轮一次、冷却、白名单模板、同帧截图、串行倒计时、2 秒限速、容量/图片预算、分项回执、未知结果不重试。试算和单次识别不发消息。
- QQ：可连接已有本机 NapCat 正向 WS，核验账号和好友/群；管理端独立鉴权、二维码绘制和登录状态轮询已接线，但没有真实 QQ 扫码/收发验收。连接凭据成功后保存到 Windows Credential Manager。自动重连只恢复连接，遇到不同账号中止，不补发历史任务。
- NapCat Shell：进入“QQ 连接 → 运行与登录”，选择已安装的 Shell 启动文件（bat/cmd/ps1/exe）及其真实 config 目录，选择对应账号的 OneBot JSON，点击“启动 NapCat 并自动配置 / 填写 token”。程序读取已有地址及 token，缺少管理 token 或正向 WS 时生成并在修改前保留 `.bak` 备份。就绪后显示登录状态/二维码，登录成功后尝试核验消息通道；也可仅点击“读取已有配置”。配置目录必须属于所选 Shell，多账号请选择对应 `onebot11_账号.json`。不会自动下载 NapCat；从托盘退出应用会关闭本应用启动的 NapCat 及其 QQ 子进程，也可点击“停止本应用启动的 NapCat / 释放账号”。关闭到托盘仍继续运行。“断开消息连接”不退出 QQ 登录；附加到已有外部实例时只断开连接，需从其启动入口退出。
- 生命周期：系统托盘、同数据目录单实例激活、后台采集、锁屏暂停、OCR 子进程超时与退出回收。正常退出已通过开发和构建启动检查。

首次体验可仅开启色块模块；验证 OCR 可使用“立即识别一次”。真实消息只会在用户启用关键词监控后命中已配置规则，或点击明确目标的测试发送按钮时发出。截图/OCR 在本机执行，通知内容通过 QQ 网络传输。

## 检查与构建

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m screen_qq_ocr --smoke-test --data-dir artifacts/smoke
.\.venv\Scripts\python.exe -m screen_qq_ocr --self-check artifacts/self-check.json
.\.venv\Scripts\python.exe scripts/probe_capture.py
.\.venv\Scripts\python.exe scripts/render_ui.py
powershell -File scripts/build.ps1
```

自动测试只使用合成数据与本地假 OneBot，不连接真实 QQ。`--self-check` 使用合成中英文图片；`probe_capture.py` 只捕获其创建的独立测试窗口。视觉输出在 `artifacts/visual/`。测试/构建不会改写 `legacy/`。

设计依据：[PRD](docs/PRD.md)、[架构](docs/ARCHITECTURE.md)。后续 P0 缺口与发布门槛保留在验收记录中，未降低原需求优先级。

## UI 重设计提案

灰黑主色、橙色背景光晕、柔和灰白表面的 [UI 与动画交互方案](docs/design/UI-REDESIGN.md) 已完成设计稿。覆盖六个页面与关键交互，图稿保存在 `artifacts/ui-design/`。当前为设计预览，尚未替换正式 PySide6 界面。


### 扫码登录提示

如果 NapCat 提示“该账号已登录，无法重复登录”，先退出使用同一账号的其他 QQ / NapCat 会话，再刷新二维码；应用不会自动关闭其他 QQ 实例。登录页现在展示 NapCat 的原始错误，区分重复登录、二维码过期和离线状态。刷新会等待异步生成新码，旧二维码不再继续显示。详见 [登录修正记录](docs/acceptance/2026-09-06-qq-login.md)。
