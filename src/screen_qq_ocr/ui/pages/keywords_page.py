from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from screen_qq_ocr.domain.models import KeywordRule
from screen_qq_ocr.ui.widgets.controls import Button as QPushButton
from screen_qq_ocr.ui.widgets.controls import Dialog
from screen_qq_ocr.ui.widgets.policy_editor import PolicyEditor


class KeywordsPage(QWidget):
    save = Signal(object)
    delete = Signal(str)
    import_clicked = Signal()
    export_clicked = Signal()
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.rules = []
        self.editing = None
        self.deleted = None
        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索关键词")
        self.search.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search)
        for title, action in (
            ("新增", self.new),
            ("导入", self.import_clicked.emit),
            ("导出", self.export_clicked.emit),
        ):
            button = QPushButton(title)
            button.clicked.connect(action)
            toolbar.addWidget(button)
        left.addLayout(toolbar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["启用", "关键词", "目标数量（至少）", "发送策略"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.edit)
        left.addWidget(self.table)
        actions = QHBoxLayout()
        for title, action in (
            ("编辑", lambda: self.edit(self.table.currentRow(), 0)),
            ("删除", self.remove),
            ("撤销删除", self.undo),
            ("启用所选", lambda: self.toggle(True)),
            ("停用所选", lambda: self.toggle(False)),
        ):
            button = QPushButton(title)
            button.clicked.connect(action)
            actions.addWidget(button)
        left.addLayout(actions)
        layout.addLayout(left, 3)
        self.editor = Dialog(self)
        self.editor.setWindowTitle("关键词规则")
        self.editor.resize(720, 600)
        editor_layout = QVBoxLayout(self.editor)
        form = QFormLayout()
        self.keyword = QLineEdit()
        self.keyword.setMaxLength(100)
        self.keyword.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.alias = QLineEdit()
        self.alias.setMaxLength(100)
        self.alias.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.alias.setPlaceholderText("留空时使用关键词本身")
        self.count = QSpinBox()
        self.count.setRange(1, 999)
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.enabled = QCheckBox("启用规则")
        self.enabled.setChecked(True)
        form.addRow("关键词", self.keyword)
        form.addRow("目标数量（单帧至少）", self.count)
        self.count.setToolTip("同一帧中关键词出现次数达到该值才算命中，范围 1–999；不是连续帧数。")
        form.addRow("消息别名", self.alias)
        form.addRow(self.enabled)
        editor_layout.addLayout(form)
        self.policy = PolicyEditor(overrides=True)
        editor_layout.addWidget(self.policy)
        buttons = QHBoxLayout()
        save = QPushButton("应用")
        save.setProperty("variant", "primary")
        save.clicked.connect(self.submit)
        close = QPushButton("收起")
        close.clicked.connect(self.editor.hide)
        buttons.addWidget(save)
        buttons.addWidget(close)
        editor_layout.addLayout(buttons)
        self.editor.hide()

    def set_rules(self, rules):
        self.rules = list(rules)
        self.refresh()

    def refresh(self):
        query = self.search.text().casefold()
        self.visible_rules = [
            r for r in self.rules if query in r.keyword.casefold() or query in r.alias.casefold()
        ]
        self.table.setRowCount(len(self.visible_rules))
        for row, rule in enumerate(self.visible_rules):
            custom = any(
                getattr(rule.send_overrides, f) is not None for f in rule.send_overrides.__dataclass_fields__
            )
            for column, value in enumerate(
                (
                    "是" if rule.enabled else "否",
                    f"{rule.keyword} / {rule.alias}" if rule.alias else rule.keyword,
                    str(rule.min_count),
                    "自定义" if custom else "继承默认",
                )
            ):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
            count = QSpinBox()
            count.setRange(1, 999)
            count.setValue(rule.min_count)
            count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            count.setKeyboardTracking(False)
            count.setToolTip("关键词在单帧中至少出现多少次；调整后自动保存")
            count.valueChanged.connect(lambda value, rule_id=rule.id: self.update_count(rule_id, value))
            self.table.setCellWidget(row, 2, count)

    def update_count(self, rule_id, value):
        rule = next(r for r in self.rules if r.id == rule_id)
        updated = replace(rule, min_count=value, revision=rule.revision + 1)
        self.rules[self.rules.index(rule)] = updated
        if self.editing and self.editing.id == rule_id:
            self.editing = updated
            self.count.setValue(value)
        self.save.emit(updated)

    def new(self):
        from screen_qq_ocr.domain.models import SendOverrides

        self.editing = None
        self.keyword.clear()
        self.alias.clear()
        self.count.setValue(1)
        self.enabled.setChecked(True)
        self.policy.load(SendOverrides())
        self.editor.show()

    def edit(self, row, _):
        if row < 0 or row >= len(self.visible_rules):
            return
        self.editing = self.visible_rules[row]
        self.keyword.setText(self.editing.keyword)
        self.alias.setText(self.editing.alias)
        self.count.setValue(self.editing.min_count)
        self.enabled.setChecked(self.editing.enabled)
        self.policy.load(self.editing.send_overrides)
        self.editor.show()

    def submit(self):
        try:
            values = dict(
                keyword=self.keyword.text(),
                alias=self.alias.text(),
                min_count=self.count.value(),
                enabled=self.enabled.isChecked(),
                send_overrides=self.policy.value(),
            )
            rule = (
                replace(self.editing, **values, revision=self.editing.revision + 1)
                if self.editing
                else KeywordRule(**values, sort_order=len(self.rules))
            )
            self.save.emit(rule)
            self.editing = rule
        except ValueError as error:
            self.error.emit(str(error))

    def saved(self, rule):
        if self.editing and self.editing.id == rule.id:
            self.editor.accept()

    def remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.deleted = self.visible_rules[row]
            self.delete.emit(self.deleted.id)

    def undo(self):
        if self.deleted:
            self.save.emit(self.deleted)
            self.deleted = None

    def toggle(self, enabled):
        for row in {index.row() for index in self.table.selectedIndexes()}:
            rule = self.visible_rules[row]
            self.save.emit(replace(rule, enabled=enabled, revision=rule.revision + 1))
