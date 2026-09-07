from collections import deque
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from screen_qq_ocr.ui.widgets.controls import Button as QPushButton
from screen_qq_ocr.ui.widgets.controls import ComboBox as QComboBox
from screen_qq_ocr.ui.widgets.controls import FileDialog as QFileDialog


class RecordsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.entries = deque(maxlen=1000)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItems(["全部", "发送", "error", "info"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索任务 ID、状态或事件")
        self.pause = QCheckBox("暂停滚动")
        clear = QPushButton("清空视图")
        export = QPushButton("导出当前事件")
        for widget in (self.category, self.search, self.pause, clear, export):
            filters.addWidget(widget)
        layout.addLayout(filters)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(1000)
        layout.addWidget(self.text)
        self.category.currentTextChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        clear.clicked.connect(self.clear_view)
        export.clicked.connect(self.export)

    def appendPlainText(self, text):
        # Caller supplies metadata only. OCR text, tokens and QR payloads aren't log entries.
        self.entries.append(text)
        self.refresh()

    def refresh(self):
        scroll = self.text.verticalScrollBar().value()
        search = self.search.text().casefold()
        category = self.category.currentText()
        self.text.setPlainText(
            "\n".join(
                x for x in self.entries if search in x.casefold() and (category == "全部" or category in x)
            )
        )
        self.text.verticalScrollBar().setValue(
            scroll if self.pause.isChecked() else self.text.verticalScrollBar().maximum()
        )

    def clear_view(self):
        self.entries.clear()
        self.refresh()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出事件元数据（不含 OCR 正文和图片）", "events.txt", "文本 (*.txt)"
        )
        if path:
            Path(path).write_text(self.text.toPlainText(), encoding="utf-8")
