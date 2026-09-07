import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog

from screen_qq_ocr.infrastructure.persistence.settings import Settings
from screen_qq_ocr.ui.appearance import install
from screen_qq_ocr.ui.main_window import MainWindow
from screen_qq_ocr.ui.widgets.controls import ComboBox, FileDialog, TaskSelector


def test_task_cards_keep_ids_and_support_keyboard(qtbot):
    cards = TaskSelector()
    qtbot.addWidget(cards)
    cards.addItem("第一个 · 运行 · 窗口", "a")
    cards.addItem("第二个 · 停止 · 窗口", "b")
    cards.setCurrentIndex(0)
    cards.show()
    cards.setFocus()
    with qtbot.waitSignal(cards.currentIndexChanged):
        qtbot.keyClick(cards, Qt.Key.Key_Right)
    assert cards.currentData() == "b"
    assert cards.findData("a") == 0
    cards.blockSignals(True)
    cards.clear()
    cards.addItem("重新加载 · 停止 · 窗口", "a")
    cards.setCurrentIndex(cards.findData("a"))
    cards.blockSignals(False)
    assert cards.currentData() == "a"


def test_custom_dropdown_preserves_cancel_and_keyboard_selection(qtbot):
    combo = ComboBox()
    qtbot.addWidget(combo)
    combo.addItems(["第一个", "第二个", "第三个"])
    combo.show()
    combo.showPopup()
    qtbot.keyClick(combo.view(), Qt.Key.Key_Down)
    qtbot.keyClick(combo.view(), Qt.Key.Key_Return)
    assert combo.currentIndex() == 1
    combo.showPopup()
    qtbot.keyClick(combo.view(), Qt.Key.Key_Escape)
    assert combo.currentIndex() == 1
    assert not combo.view().isVisible()


def test_theme_assets_dialogs_and_persistence(qtbot, tmp_path):
    settings = Settings(tmp_path / "settings.json")
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    window.toggle_theme()
    assert QApplication.instance().property("dark_theme")
    settings.save(window.settings_page.value())
    assert Settings(settings.path).values["appearance"]["theme"] == "dark"
    assert all(isinstance(combo, ComboBox) for combo in window.findChildren(QComboBox))
    sheet = QApplication.instance().styleSheet()
    assert "@icons@" not in sheet and "@surface@" not in sheet
    assert all(Path(path).exists() for path in re.findall(r"url\((.*?)\)", sheet))
    window.keywords.new()
    assert window.keywords.editor.property("decorated")
    assert window.keywords.editor.windowFlags() & Qt.WindowType.FramelessWindowHint
    window.keywords.keyword.setText("保留内容")
    window.keywords.editor.hide()
    window.keywords.editor.show()
    assert window.keywords.keyword.text() == "保留内容"
    window.keywords.editor.hide()
    dialog = FileDialog(window, "选择文件", str(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
    assert dialog.property("decorated")
    assert dialog.layout().count() == 2
    dialog.reject()
    window.tray.hide()
    window.hide()
    install(QApplication.instance(), "light")
