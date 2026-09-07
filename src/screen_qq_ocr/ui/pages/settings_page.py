import copy

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from screen_qq_ocr.ui.widgets.controls import Button as QPushButton
from screen_qq_ocr.ui.widgets.controls import Card
from screen_qq_ocr.ui.widgets.controls import ComboBox as QComboBox
from screen_qq_ocr.ui.widgets.controls import FileDialog as QFileDialog


class SettingsPage(QWidget):
    def __init__(self, values):
        super().__init__()
        self.values = copy.deepcopy(values)
        layout = QVBoxLayout(self)
        general = Card("外观与识别")
        layout.addWidget(general)
        form = QFormLayout()
        general.body.addLayout(form)
        form.setVerticalSpacing(14)
        self.theme = QComboBox()
        for text, data in [
            ("柔白 · 炭灰与橙光", "light"),
            ("深色 · 石墨与橙光", "dark"),
            ("跟随系统", "system"),
        ]:
            self.theme.addItem(text, data)
        self.theme.setCurrentIndex(max(0, self.theme.findData(values["appearance"].get("theme", "light"))))
        form.addRow("工作区主题", self.theme)
        self.engine = QComboBox()
        self.engine.addItem("Windows OCR", "windows")
        self.engine.addItem("本地 Tesseract", "tesseract")
        self.engine.setCurrentIndex(max(0, self.engine.findData(values["ocr"]["engine"])))
        self.interval = QComboBox()
        for value in (2, 3, 5, 10):
            self.interval.addItem(f"{value} 秒", value)
        self.interval.setCurrentIndex(self.interval.findData(values["ocr"]["interval"]))
        self.edge = QComboBox()
        for value in (1280, 1920, 2560):
            self.edge.addItem(str(value), value)
        self.edge.setCurrentIndex(self.edge.findData(values["ocr"]["max_edge"]))
        self.preprocess = QCheckBox("Tesseract 灰度、对比度与暗底反色")
        self.preprocess.setChecked(values["ocr"]["preprocess"])
        self.path = QLineEdit(values["ocr"]["tesseract"])
        self.browse = QPushButton("选择 Tesseract 引擎")
        self.browse.clicked.connect(self.choose)
        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 86400)
        self.cooldown.setValue(values["flash"]["cooldown"])
        self.sound = QComboBox()
        self.sound.addItems(["急促警报", "双短鸣", "长鸣", "柔和提示", "静音"])
        self.sound.setCurrentText(values["flash"]["sound"])
        self.audition = QPushButton("试听 3 秒")
        self.low = QCheckBox("低资源预览（8fps）")
        self.low.setChecked(values["appearance"]["low_resource"])
        self.motion = QCheckBox("减少动画")
        self.motion.setChecked(values["appearance"]["reduce_motion"])
        self.tray = QCheckBox("关闭窗口时最小化到托盘")
        self.tray.setChecked(values["lifecycle"]["close_to_tray"])
        for label, widget in (
            ("OCR 引擎", self.engine),
            ("识别结束后的等待", self.interval),
            ("输入最大边", self.edge),
            ("预处理", self.preprocess),
            ("引擎路径", self.path),
            ("", self.browse),
            ("色块冷却秒数", self.cooldown),
            ("声音", self.sound),
            ("", self.audition),
            ("预览", self.low),
            ("外观", self.motion),
            ("关闭行为", self.tray),
        ):
            form.addRow(label, widget)
        self.save = QPushButton("保存设置并停止监控")
        self.save.setProperty("variant", "primary")
        layout.addWidget(self.save)
        layout.addStretch()

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Tesseract", "", "程序 (*.exe)")
        if path:
            self.path.setText(path)

    def value(self):
        values = copy.deepcopy(self.values)
        values["ocr"].update(
            engine=self.engine.currentData(),
            interval=self.interval.currentData(),
            max_edge=self.edge.currentData(),
            preprocess=self.preprocess.isChecked(),
            tesseract=self.path.text(),
        )
        values["flash"].update(cooldown=self.cooldown.value(), sound=self.sound.currentText())
        values["appearance"].update(
            low_resource=self.low.isChecked(),
            reduce_motion=self.motion.isChecked(),
            theme=self.theme.currentData(),
        )
        values["lifecycle"]["close_to_tray"] = self.tray.isChecked()
        return values
