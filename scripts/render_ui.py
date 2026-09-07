"""Render synthetic UI state for visual inspection, without connecting or capturing."""

from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screen_qq_ocr.domain.models import KeywordRule
from screen_qq_ocr.infrastructure.persistence.settings import Settings
from screen_qq_ocr.ui.main_window import MainWindow
from screen_qq_ocr.ui.widgets.controls import FileDialog


def main():
    app = QApplication([])
    root = Path(__file__).resolve().parents[1]
    app.setProperty("reduce_motion", True)
    window = MainWindow(Settings(root / "artifacts/visual/settings.json"))
    app.setProperty("reduce_motion", True)
    window.monitor.tasks.addItem("监控任务 1 · 运行 · 主显示器", "one")
    window.monitor.tasks.addItem("监控任务 2 · 停止 · QQ 窗口", "two")
    window.monitor.tasks.setCurrentIndex(0)
    window.monitor.sources.addItems(["主显示器 · 2560 × 1440", "QQ 窗口", "副显示器"])
    window.keywords.set_rules([KeywordRule("Cerb", 5), KeywordRule("识别测试", 2)])
    output = root / "artifacts/visual"
    output.mkdir(parents=True, exist_ok=True)
    for width, height in ((1280, 860), (960, 640)):
        window.resize(width, height)
        window.show()
        for index in range(6):
            window.settings.values["appearance"]["reduce_motion"] = True
            window.navigation.setCurrentRow(index)
            app.processEvents()
            QTest.qWait(300)
            window.grab().save(str(output / f"page-{index}-{width}.png"))
            if index == 2:
                from PySide6.QtWidgets import QTabWidget

                tabs = window.qq.findChild(QTabWidget)
                tabs.setCurrentIndex(1)
                app.processEvents()
                window.grab().save(str(output / f"page-2-runtime-{width}.png"))
                tabs.setCurrentIndex(0)
    window.resize(1280, 860)
    for theme in ("light", "dark"):
        window.settings_page.theme.setCurrentIndex(window.settings_page.theme.findData(theme))
        for index in range(6):
            window.navigation.setCurrentRow(index)
            QTest.qWait(300)
            window.grab().save(str(output / f"{theme}-page-{index}.png"))
        window.settings_page.theme.showPopup()
        QTest.qWait(100)
        window.settings_page.theme.view().window().grab().save(str(output / f"{theme}-dropdown.png"))
        window.settings_page.theme.hidePopup()
        window.keywords.new()
        QTest.qWait(350)
        window.keywords.editor.grab().save(str(output / f"{theme}-rule-dialog.png"))
        window.keywords.editor.hide()
        dialog = FileDialog(window, "选择启动文件", str(root), "程序 (*.exe);;所有文件 (*)")
        dialog.show()
        QTest.qWait(350)
        dialog.grab().save(str(output / f"{theme}-file-dialog.png"))
        dialog.hide()
        menu = window.tray.contextMenu()
        menu.popup(window.mapToGlobal(window.rect().center()))
        QTest.qWait(100)
        menu.grab().save(str(output / f"{theme}-tray-menu.png"))
        menu.hide()
    window.tray.hide()
    window.hide()


if __name__ == "__main__":
    main()
