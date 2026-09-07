from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QFileInfo,
    QObject,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from screen_qq_ocr.ui.appearance import colors, icon


def motion_enabled():
    return not QApplication.instance().property("reduce_motion")


def button(text, primary=False, glyph=None):
    widget = Button(text)
    widget.setProperty("variant", "primary" if primary else "secondary")
    if glyph:
        widget.setProperty("glyph", glyph)
        widget.setIcon(icon(glyph, colors()["on_primary"] if primary else colors()["text"]))
    return widget


def label(text, role="muted"):
    result = QLabel(text)
    result.setProperty("role", role)
    result.setWordWrap(True)
    return result


class Button(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._wash = 0.0
        self._hover = False
        self.animation = QVariantAnimation(self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._update_wash)
        self.pressed.connect(lambda: self.fade(0.12, 180))
        self.released.connect(lambda: self.fade(0.04 if self._hover else 0, 300))

    def _update_wash(self, value):
        self._wash = value
        self.update()

    def fade(self, value, duration):
        self.animation.stop()
        if not motion_enabled():
            self._update_wash(0.0)
            return
        self.animation.setStartValue(self._wash)
        self.animation.setEndValue(value)
        self.animation.setDuration(duration)
        self.animation.start()

    def enterEvent(self, event):
        self._hover = True
        self.fade(0.04, 300)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.fade(0.0, 300)
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._wash and self.isEnabled():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            color = QColor(
                colors()["on_primary"] if self.property("variant") == "primary" else colors()["text"]
            )
            color.setAlphaF(self._wash)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)


class ComboBox(QComboBox):
    def __init__(self, *args):
        super().__init__(*args)
        view = QListView()
        view.setObjectName("comboPopup")
        view.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setItemDelegate(QStyledItemDelegate(view))
        self.setView(view)
        self.setMaxVisibleItems(9)
        self.setMinimumContentsLength(10)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.currentTextChanged.connect(self.setToolTip)

    def showPopup(self):
        self.view().setMinimumWidth(self.width())
        super().showPopup()


class Card(QFrame):
    def __init__(self, title=None):
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(12)
        if title:
            self.body.addWidget(label(title, "section"))


class GlowSurface(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(colors()["bg"]))
        gradient = QRadialGradient(self.width() * 0.94, 0, max(300, self.width() * 0.68))
        color = QColor(colors()["glow"])
        color.setAlpha(145 if not QApplication.instance().property("dark_theme") else 110)
        gradient.setColorAt(0, color)
        color.setAlpha(0)
        gradient.setColorAt(1, color)
        painter.fillRect(self.rect(), gradient)


class TitleBar(QWidget):
    def __init__(self, window, compact=False):
        super().__init__(window)
        self.target = window
        self.setObjectName("titleBar")
        self.setFixedHeight(48 if compact else 52)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 8, 0)
        brand = QLabel()
        brand.setObjectName("brandIcon")
        brand.setPixmap(icon("app").pixmap(22, 22))
        row.addWidget(brand)
        self.title = QLabel(window.windowTitle())
        self.title.setProperty("role", "brand")
        window.windowTitleChanged.connect(self.title.setText)
        row.addWidget(self.title)
        row.addStretch()
        controls = (
            [("close", window.close)]
            if compact
            else [
                ("theme", window.toggle_theme),
                ("minimize", window.showMinimized),
                ("maximize", self.maximize),
                ("close", window.close),
            ]
        )
        for name, callback in controls:
            control = QToolButton()
            control.setObjectName("closeButton" if name == "close" else "windowButton")
            control.setProperty("glyph", name)
            control.setIcon(icon(name))
            control.setAccessibleName(
                {"close": "关闭", "theme": "切换明暗主题", "minimize": "最小化", "maximize": "最大化或还原"}[
                    name
                ]
            )
            control.setToolTip(control.accessibleName())
            control.clicked.connect(callback)
            row.addWidget(control)

    def maximize(self):
        self.target.showNormal() if self.target.isMaximized() else self.target.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.target.windowHandle():
            self.target.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        if isinstance(self.target, QDialog):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize()


def decorate_dialog(dialog):
    if dialog.property("decorated"):
        return
    dialog.setProperty("decorated", True)
    old = dialog.layout()
    if old:
        holder = QWidget()
        holder.setLayout(old)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(dialog, compact=True))
        layout.addWidget(holder)


class Dialog(QDialog):
    def __init__(self, *args):
        super().__init__(*args)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

    def showEvent(self, event):
        decorate_dialog(self)
        super().showEvent(event)


class FileIcons(QFileIconProvider):
    def icon(self, entry):
        directory = (
            entry.isDir() if isinstance(entry, QFileInfo) else entry == QFileIconProvider.IconType.Folder
        )
        return icon("folder" if directory else "file")


class DialogStyler(QObject):
    def eventFilter(self, watched, event):
        if isinstance(watched, QDialog):
            if event.type() == QEvent.Type.Polish:
                watched.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            elif event.type() == QEvent.Type.Show:
                decorate_dialog(watched)
                if motion_enabled():
                    animation = QPropertyAnimation(watched, b"windowOpacity", watched)
                    animation.setDuration(300)
                    animation.setStartValue(0.0)
                    animation.setEndValue(1.0)
                    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                    watched._entrance = animation
                    animation.start()
                else:
                    watched.setWindowOpacity(1.0)
        return super().eventFilter(watched, event)


class FileDialog(QFileDialog):
    """The same Qt surface on every Windows version, including the file chooser."""

    def __init__(self, *args):
        super().__init__(*args)
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.resize(820, 560)
        self._icons = FileIcons()
        self.setIconProvider(self._icons)

    def showEvent(self, event):
        decorate_dialog(self)
        super().showEvent(event)

    @staticmethod
    def getOpenFileName(parent=None, caption="", directory="", filter="", **kwargs):
        dialog = FileDialog(parent, caption, directory, filter)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        result = dialog.exec()
        return (dialog.selectedFiles()[0], dialog.selectedNameFilter()) if result else ("", "")

    @staticmethod
    def getSaveFileName(parent=None, caption="", directory="", filter="", **kwargs):
        dialog = FileDialog(parent, caption, directory, filter)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        result = dialog.exec()
        return (dialog.selectedFiles()[0], dialog.selectedNameFilter()) if result else ("", "")

    @staticmethod
    def getExistingDirectory(parent=None, caption="", directory="", **kwargs):
        dialog = FileDialog(parent, caption, directory)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        return dialog.selectedFiles()[0] if dialog.exec() else ""


class TaskDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QStyle

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        rect = QRectF(option.rect).adjusted(0, 2, -10, -5)
        c = colors()
        painter.setBrush(QColor(c["tint"] if selected else c["surface"]))
        painter.setPen(QPen(QColor(c["orange"] if selected or focused else c["line"]), 1))
        painter.drawRoundedRect(rect, 11, 11)
        parts = index.data().split(" · ", 2)
        name = parts[0]
        status = parts[1] if len(parts) > 1 else "停止"
        source = parts[2] if len(parts) > 2 else "未选择来源"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["green"] if status == "运行" else c["muted"]))
        painter.drawEllipse(rect.left() + 12, rect.top() + 18, 5, 5)
        painter.setPen(QColor(c["text"]))
        painter.drawText(rect.adjusted(24, 8, -12, -29), Qt.AlignmentFlag.AlignVCenter, name)
        painter.setPen(QColor(c["muted"]))
        text = option.fontMetrics.elidedText(
            f"{source} · {status}", Qt.TextElideMode.ElideMiddle, int(rect.width() - 30)
        )
        painter.drawText(rect.adjusted(12, 32, -12, -8), Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


class TaskSelector(QListWidget):
    currentIndexChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("taskSelector")
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setFixedHeight(84)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setItemDelegate(TaskDelegate(self))
        self.currentRowChanged.connect(self.currentIndexChanged)

    def addItem(self, title, data=None):
        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, data)
        item.setToolTip(title)
        item.setSizeHint(QSize(max(190, self.viewport().width() // 3), 70))
        super().addItem(item)

    def currentData(self):
        return self.currentItem().data(Qt.ItemDataRole.UserRole) if self.currentItem() else None

    def findData(self, data):
        return next(
            (i for i in range(self.count()) if self.item(i).data(Qt.ItemDataRole.UserRole) == data), -1
        )

    def setCurrentIndex(self, index):
        if isinstance(index, int):
            self.setCurrentRow(index)
        else:
            super().setCurrentIndex(index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for i in range(self.count()):
            self.item(i).setSizeHint(QSize(max(190, self.viewport().width() // min(3, self.count())), 70))


class MessageBox(Dialog):
    @staticmethod
    def critical(parent, title, text):
        dialog = MessageBox(parent)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.addWidget(label(text, "section"))
        close = button("确定", True)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        return dialog.exec()
