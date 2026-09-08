from PySide6.QtCore import QEvent, QObject, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel

from screen_qq_ocr.ui.appearance import colors


class ToastStack(QObject):
    """Window-local notifications; newest at the bottom, bounded by available height."""

    def __init__(self, window, duration=3200):
        super().__init__(window)
        self.window = window
        self.duration = duration
        self.items = []
        self.retiring = []
        window.installEventFilter(self)

    def show(self, text, error=False):
        toast = QLabel(("✕ " if error else "√ ") + text, self.window)
        toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        toast.setTextFormat(Qt.TextFormat.PlainText)
        toast.setWordWrap(True)
        toast.setFixedWidth(min(340, max(160, self.window.width() - 48)))
        c = colors()
        toast.setStyleSheet(
            f"background:{c['surface']}; color:{c['danger'] if error else c['green']};"
            f"border:1px solid {c['line']}; border-radius:12px; padding:12px 16px;"
        )
        toast.setFixedHeight(min(96, max(48, toast.heightForWidth(toast.width()))))
        toast.setToolTip(text)
        toast.effect = QGraphicsOpacityEffect(toast)
        toast.effect.setOpacity(1.0)
        toast.setGraphicsEffect(toast.effect)
        toast.motion = QPropertyAnimation(toast, b"pos", toast)
        toast.fade = QPropertyAnimation(toast.effect, b"opacity", toast)
        toast.timer = QTimer(toast)
        toast.timer.setSingleShot(True)
        toast.timer.timeout.connect(lambda: self.dismiss(toast))
        toast.move(self.window.width() - toast.width() - 24, self.window.height() - toast.height() - 24)
        self.items.append(toast)
        toast.show()
        toast.raise_()
        self.reflow()
        toast.timer.start(self.duration)

    def dismiss(self, toast, reflow=True):
        if toast not in self.items:
            return
        self.items.remove(toast)
        self.retiring.append(toast)
        toast.timer.stop()
        toast.motion.stop()
        toast.fade.setDuration(0 if QApplication.instance().property("reduce_motion") else 220)
        toast.fade.setStartValue(toast.effect.opacity())
        toast.fade.setEndValue(0)
        toast.fade.finished.connect(lambda: self.remove(toast))
        toast.fade.start()
        if reflow:
            self.reflow()

    def remove(self, toast):
        self.retiring.remove(toast)
        toast.hide()
        toast.deleteLater()

    def reflow(self):
        maximum = min(300, max(48, self.window.height() * 0.4))
        while len(self.items) > 1 and sum(t.height() + 8 for t in self.items) - 8 > maximum:
            self.dismiss(self.items[0], reflow=False)
        y = self.window.height() - 24
        for toast in reversed(self.items):
            y -= toast.height()
            toast.motion.stop()
            toast.motion.setDuration(0 if QApplication.instance().property("reduce_motion") else 160)
            toast.motion.setStartValue(toast.pos())
            toast.motion.setEndValue(QPoint(self.window.width() - toast.width() - 24, y))
            toast.motion.start()
            y -= 8

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.reflow()
        return False
