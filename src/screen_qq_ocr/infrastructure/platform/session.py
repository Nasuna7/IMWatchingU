import ctypes
import os
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter


class SessionFilter(QAbstractNativeEventFilter):
    def __init__(self, hwnd, on_pause):
        super().__init__()
        self.hwnd, self.on_pause = hwnd, on_pause
        if os.name == "nt":
            ctypes.windll.wtsapi32.WTSRegisterSessionNotification(ctypes.c_void_p(hwnd), 0)

    def nativeEventFilter(self, event_type, message):
        if os.name == "nt":
            msg = wintypes.MSG.from_address(int(message))
            if (msg.message == 0x02B1 and msg.wParam == 0x7) or (msg.message == 0x0218 and msg.wParam == 4):
                self.on_pause()
        return False, 0

    def close(self):
        if os.name == "nt":
            ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(ctypes.c_void_p(self.hwnd))
