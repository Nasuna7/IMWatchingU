"""Render the interaction update with synthetic data and no external connections."""

from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screen_qq_ocr.domain.models import FrameSnapshot
from screen_qq_ocr.infrastructure.persistence.settings import Settings
from screen_qq_ocr.ui.main_window import MainWindow

app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
app.setFont(QFont("Microsoft YaHei", 9))
output = Path(__file__).resolve().parents[1] / "artifacts" / "feedback"
output.mkdir(parents=True, exist_ok=True)
window = MainWindow(Settings(output / "settings.json"))
window.monitor.tasks.addItem("任务 1 · 运行 · EVE - 示例角色", "one")
window.monitor.tasks.addItem("任务 2 · 停止 · 主显示器", "two")
window.monitor.tasks.setCurrentIndex(0)
window.monitor.sources.addItem("EVE - 示例角色")
frame = FrameSnapshot("demo", 1, datetime.now(), 0, 640, 360, bytes([54, 61, 69]) * 640 * 360)
window.monitor.preview.set_frame(frame)
window.monitor.preview.set_roi((0.15, 0.2, 0.65, 0.6))
window.monitor.ocr.setPlainText("示例识别结果\n监控正在运行")
window.status_labels["monitor_status"].setText("监控：运行")
window.show()
for theme in ("light", "dark"):
    window.settings_page.theme.setCurrentIndex(window.settings_page.theme.findData(theme))
    for size in ((1280, 860), (960, 640)):
        window.resize(*size)
        window.toasts.show("QQ登录成功")
        window.toasts.show("关键词已应用")
        window.toasts.show("监控已启动")
        QTest.qWait(400)
        window.grab().save(str(output / f"{theme}-{size[0]}.png"))
        for toast in list(window.toasts.items):
            window.toasts.dismiss(toast)
        QTest.qWait(300)
window.tray.hide()
window.hide()
