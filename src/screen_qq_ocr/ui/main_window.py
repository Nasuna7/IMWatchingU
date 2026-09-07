from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .appearance import colors, icon, install
from .pages.keywords_page import KeywordsPage
from .pages.monitor_page import MonitorPage
from .pages.qq_page import QQPage
from .pages.records_page import RecordsPage
from .pages.send_config_page import SendConfigPage
from .pages.settings_page import SettingsPage
from .widgets.controls import GlowSurface, TitleBar, label


class MainWindow(QMainWindow):
    quit_requested = Signal()
    stop_requested = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.exiting = False
        app = QApplication.instance()
        install(app, settings.values["appearance"].get("theme", "light"))
        app.setProperty("reduce_motion", settings.values["appearance"]["reduce_motion"])
        self.setWindowTitle("IMWatchingU❤")
        self.setWindowIcon(icon("app"))
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(960, 640)
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1280, area.width()), min(860, area.height()))
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self))
        layout = QHBoxLayout()
        layout.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(164)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 20, 12, 16)
        brand = label("IM\nWATCH", "brand")
        brand.setStyleSheet("color: #F4F4F3; font-size: 19px; padding: 8px;")
        side.addWidget(brand)
        side.addSpacing(18)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setIconSize(QSize(20, 20))
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for title, glyph in zip(
            ["监控工作台", "关键词规则", "QQ 连接", "发送配置", "运行记录", "应用设置"],
            ["monitor", "rules", "chat", "send", "history", "settings"],
        ):
            self.navigation.addItem(QListWidgetItem(icon(glyph, "#E8E8E5"), title))
        side.addWidget(self.navigation, 1)
        layout.addWidget(sidebar)
        surface = GlowSurface()
        content = QVBoxLayout(surface)
        content.setContentsMargins(24, 20, 24, 12)
        content.setSpacing(12)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        self.title = QLabel("监控工作台")
        self.title.setObjectName("pageTitle")
        titles.addWidget(self.title)
        heading.addLayout(titles, 1)
        self.status_labels = {}
        qq = QLabel("QQ：离线")
        qq.setObjectName("connectionBadge")
        qq.setFixedHeight(34)
        heading.addWidget(qq)
        self.status_labels["qq_status"] = qq
        content.addLayout(heading)
        self.stack = QStackedWidget()
        self.monitor = MonitorPage()
        self.keywords = KeywordsPage()
        self.qq = QQPage()
        self.send = SendConfigPage()
        self.records = RecordsPage()
        self.settings_page = SettingsPage(settings.values)
        self.settings_page.theme.currentIndexChanged.connect(self.apply_theme)
        app.styleHints().colorSchemeChanged.connect(
            lambda _: self.apply_theme() if self.settings_page.theme.currentData() == "system" else None
        )
        self.settings_page.motion.toggled.connect(lambda value: app.setProperty("reduce_motion", value))
        for page in (self.monitor, self.keywords, self.qq, self.send, self.records, self.settings_page):
            page.layout().setContentsMargins(0, 0, 0, 0)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        content.addWidget(self.stack, 1)
        footer = QHBoxLayout()
        for key, text in [
            ("capture_status", "采集：未选择"),
            ("ocr_status", "OCR：未检测"),
            ("monitor_status", "监控：停止"),
        ]:
            status = label(text)
            status.setObjectName("footer")
            self.status_labels[key] = status
            footer.addWidget(status, 1)
        content.addLayout(footer)
        layout.addWidget(surface, 1)
        outer.addLayout(layout, 1)
        self.navigation.currentRowChanged.connect(self.change_page)
        self.navigation.setCurrentRow(0)
        self.tray = QSystemTrayIcon(icon("app"), self)
        menu = QMenu(self)
        for title, handler in [
            ("恢复窗口", self.restore),
            ("停止监控", self.stop_requested.emit),
            ("退出", self.request_quit),
        ]:
            action = QAction(title, self)
            action.triggered.connect(handler)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.restore() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.tray_notified = False

    def apply_theme(self):
        theme = self.settings_page.theme.currentData()
        self.settings.values["appearance"]["theme"] = theme
        install(QApplication.instance(), theme)
        for widget in self.findChildren(QPushButton) + self.findChildren(QToolButton):
            if widget.property("glyph"):
                widget.setIcon(
                    icon(
                        widget.property("glyph"),
                        colors()["on_primary"]
                        if widget.property("variant") == "primary"
                        else colors()["text"],
                    )
                )
        for brand in self.findChildren(QLabel, "brandIcon"):
            brand.setPixmap(icon("app").pixmap(22, 22))
        self.update()

    def toggle_theme(self):
        target = "light" if QApplication.instance().property("dark_theme") else "dark"
        self.settings_page.theme.setCurrentIndex(self.settings_page.theme.findData(target))

    def change_page(self, index):
        if index < 0:
            return
        self.stack.setCurrentIndex(index)
        self.title.setText(self.navigation.item(index).text())
        if not QApplication.instance().property("reduce_motion"):
            if hasattr(self, "animation"):
                self.animation.stop()
            effect = QGraphicsOpacityEffect(self.title)
            self.title.setGraphicsEffect(effect)
            self.animation = QPropertyAnimation(effect, b"opacity", self)
            self.animation.setDuration(300)
            self.animation.setStartValue(0.35)
            self.animation.setEndValue(1.0)
            self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.animation.start()

    def mousePressEvent(self, event):
        p = event.position()
        edges = Qt.Edge(0)
        if p.x() < 7:
            edges |= Qt.Edge.LeftEdge
        if p.x() > self.width() - 7:
            edges |= Qt.Edge.RightEdge
        if p.y() < 7:
            edges |= Qt.Edge.TopEdge
        if p.y() > self.height() - 7:
            edges |= Qt.Edge.BottomEdge
        if edges and event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            self.windowHandle().startSystemResize(edges)
        super().mousePressEvent(event)

    def restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def request_quit(self):
        if not self.exiting:
            self.exiting = True
            self.setEnabled(False)
            self.quit_requested.emit()

    def closeEvent(self, event):
        if not self.exiting and self.settings.values["lifecycle"]["close_to_tray"] and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self.tray_notified:
                self.tray.showMessage("IMWatchingU❤", "窗口已收起，监控继续运行。")
                self.tray_notified = True
        else:
            event.ignore()
            self.request_quit()
