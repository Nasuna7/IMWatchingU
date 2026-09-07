from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QWidget,
)

from screen_qq_ocr.domain.models import SendOverrides, SendPolicy
from screen_qq_ocr.ui.widgets.controls import ComboBox as QComboBox


class PolicyEditor(QTabWidget):
    def __init__(self, overrides=False):
        super().__init__()
        self.overrides = overrides
        self.fields = {}
        self.target_value = None
        self.target_values = ()
        conditions = QWidget()
        form = QFormLayout(conditions)
        for key, label, maximum in (("confirm_frames", "连续确认帧数", 10), ("cooldown", "冷却秒数", 86400)):
            spin = QSpinBox()
            spin.setRange(-1 if overrides else (1 if key == "confirm_frames" else 0), maximum)
            if overrides:
                spin.setSpecialValueText("继承默认")
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.fields[key] = spin
            form.addRow(label, spin)
        self._combo(form, "repeat", "重复方式", [("按冷却重复", "cooldown"), ("每轮仅一次", "once")])
        self._combo(form, "countdown", "发送前倒计时", [("立即", 0), ("3 秒", 3), ("5 秒", 5)])
        self.addTab(conditions, "发送条件")
        body_page = QWidget()
        body_form = QFormLayout(body_page)
        self._combo(
            body_form,
            "message_type",
            "消息类型",
            [("仅文字", "text"), ("文字与区域截图", "text_image"), ("仅区域截图", "image")],
        )
        self._combo(
            body_form,
            "body_source",
            "正文来源",
            [
                ("首个命中行", "hit_line"),
                ("完整识别文本", "ocr_text"),
                ("固定文本", "fixed"),
                ("消息模板", "template"),
            ],
        )
        self.body = QPlainTextEdit()
        self.body.setFixedHeight(108)
        self.inherit_body = QCheckBox("继承默认正文内容")
        self.inherit_body.setVisible(overrides)
        self.inherit_body.toggled.connect(lambda checked: self.body.setEnabled(not checked))
        self.body.setPlaceholderText(
            "固定文本原样发送。模板变量：{keyword} {count} {threshold}\n"
            "{hit_line} {ocr_text} {capture_time}；{{ }} 表示字面花括号。"
        )
        body_form.addRow("正文", self.body)
        if overrides:
            body_form.addRow(self.inherit_body)
        self.addTab(body_page, "消息格式")
        target_page = QWidget()
        target_form = QFormLayout(target_page)
        self.target_search = QLineEdit()
        self.target_search.setPlaceholderText("搜索好友 / 群名称或 ID")
        target_form.addRow("搜索对象", self.target_search)
        self.target = QListWidget()
        self.target.setMinimumHeight(190)
        target_form.addRow("好友或群", self.target)
        self.target_search.textChanged.connect(self.filter_targets)
        self.addTab(target_page, "发送对象")
        self.load(SendOverrides() if overrides else SendPolicy())

    def filter_targets(self, text):
        for index in range(self.target.count()):
            item = self.target.item(index)
            self.target.setRowHidden(index, text.casefold() not in item.text().casefold())

    def _combo(self, form, key, label, items):
        widget = QComboBox()
        if self.overrides:
            widget.addItem("继承默认", None)
        for title, data in items:
            widget.addItem(title, data)
        self.fields[key] = widget
        form.addRow(label, widget)

    def selected_targets(self):
        return tuple(
            self.target.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.target.count())
            if self.target.item(i).checkState() == Qt.CheckState.Checked
        )

    def set_targets(self, targets):
        selected = self.selected_targets() or tuple(self.target_values)
        self.target.clear()
        for target in targets:
            if target is None:
                continue
            item = QListWidgetItem(
                f"{'群' if target.type == 'group' else '好友'} · "
                f"{target.display_name} ({target.id}) · 账号 {target.account_id}"
            )
            item.setData(Qt.ItemDataRole.UserRole, target)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if target in selected else Qt.CheckState.Unchecked)
            self.target.addItem(item)
        for target in selected:
            if target and not any(
                self.target.item(i).data(Qt.ItemDataRole.UserRole) == target
                for i in range(self.target.count())
            ):
                item = QListWidgetItem(f"待核验 · {target.display_name} ({target.id}) · {target.account_id}")
                item.setData(Qt.ItemDataRole.UserRole, target)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                self.target.addItem(item)
        self.target_values = tuple(selected)

    def load(self, value):
        for key, widget in self.fields.items():
            data = getattr(value, key)
            if isinstance(widget, QSpinBox):
                widget.setValue(-1 if data is None else data)
            else:
                widget.setCurrentIndex(max(0, widget.findData(data)))
        self.body.setPlainText(value.body or "")
        self.inherit_body.setChecked(self.overrides and value.body is None)
        self.target_value = value.target
        self.target_values = tuple(value.targets or ()) or ((value.target,) if value.target else ())
        self.set_targets(
            [self.target.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.target.count())]
        )

    def value(self):
        values = {}
        for key, widget in self.fields.items():
            data = widget.value() if isinstance(widget, QSpinBox) else widget.currentData()
            values[key] = None if data == -1 else data
        values["body"] = self.body.toPlainText()
        if self.overrides and self.inherit_body.isChecked():
            values["body"] = None
        targets = self.selected_targets()
        values["target"] = targets[0] if targets else None
        values["targets"] = None if self.overrides and not targets else targets
        result = SendOverrides(**values) if self.overrides else SendPolicy(**values)
        if not self.overrides:
            result.validate()
        return result
