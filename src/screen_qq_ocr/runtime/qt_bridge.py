import threading

from PySide6.QtCore import QObject, QTimer, Signal


class EventBridge(QObject):
    event = Signal(str, object)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._latest = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush_frame)
        self._timer.start(67)

    def publish(self, kind, value):
        if kind == "frame":
            with self._lock:
                self._latest = value
        else:
            self.event.emit(kind, value)

    def _flush_frame(self):
        with self._lock:
            frame, self._latest = self._latest, None
        if frame is not None:
            self.event.emit("frame", frame)
