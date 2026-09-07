from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from screen_qq_ocr.ui.widgets.controls import Button as QPushButton
from screen_qq_ocr.ui.widgets.controls import Card, label
from screen_qq_ocr.ui.widgets.controls import ComboBox as QComboBox
from screen_qq_ocr.ui.widgets.policy_editor import PolicyEditor


class SendConfigPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.editor = PolicyEditor()
        policy_card = Card("默认发送策略")
        policy_card.body.addWidget(self.editor)
        layout.addWidget(policy_card)
        self.apply = QPushButton("应用发送配置")
        self.apply.setProperty("variant", "primary")
        layout.addWidget(self.apply)
        row = QHBoxLayout()
        self.rule = QComboBox()
        self.preview = QPushButton("使用最近结果试算")
        self.sample_preview = QPushButton("使用示例试算")
        row.addWidget(self.rule)
        row.addWidget(self.preview)
        row.addWidget(self.sample_preview)
        layout.addLayout(row)
        self.sample = QPlainTextEdit()
        self.sample.setPlaceholderText("输入示例 OCR 文本")
        self.sample.setMaximumHeight(90)
        layout.addWidget(self.sample)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        layout.addWidget(self.result)
        self.test_target = label("请先完成试算并核对接收对象")
        layout.addWidget(self.test_target)
        self.test = QPushButton("测试发送")
        self.test.setEnabled(False)
        layout.addWidget(self.test)
