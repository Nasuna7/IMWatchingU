import ctypes
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import mss
from PIL import Image

from screen_qq_ocr.domain.models import FrameSnapshot

from .coordinates import pixel_box


@dataclass(frozen=True)
class CaptureSource:
    id: str
    title: str
    kind: str
    metadata: tuple


def list_sources():
    with mss.mss() as capture:
        sources = [
            CaptureSource(
                f"monitor:{m['left']}:{m['top']}:{m['width']}:{m['height']}",
                f"显示器 {i}{'（主显示器）' if m.get('is_primary') else ''} · {m['width']}×{m['height']} · ({m['left']}, {m['top']})",
                "monitor",
                (m["left"], m["top"], m["width"], m["height"]),
            )
            for i, m in enumerate(capture.monitors[1:], 1)
        ]
    if os.name == "nt":
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @callback_type
        def collect(hwnd, _):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
            if user32.IsWindowVisible(ctypes.c_void_p(hwnd)) and pid.value != os.getpid():
                title = ctypes.create_unicode_buffer(1024)
                user32.GetWindowTextW(ctypes.c_void_p(hwnd), title, 1024)
                if title.value:
                    sources.append(
                        CaptureSource(
                            f"window:{hwnd}",
                            f"{title.value} · PID {pid.value}",
                            "window",
                            (hwnd, title.value, pid.value),
                        )
                    )
            return True

        user32.EnumWindows(collect, 0)
    return sources


class Capture:
    def __init__(self):
        self.source = None
        self.control = None
        self.latest = None
        self.lock = threading.Lock()
        self.closed = False
        self.generation = 0
        self.screen = None

    def open(self, source):
        self.close()
        self.source = source
        self.closed = False
        self.latest = None
        if source.kind == "monitor":
            self.screen = mss.mss()
        if source.kind == "window":
            from windows_capture import WindowsCapture

            candidates = [
                item
                for item in list_sources()
                if item.kind == "window" and source.metadata[1] in item.metadata[1]
            ]
            # windows-capture 1.5 selects by substring, not HWND. Never silently select a different window.
            if source.metadata[2] != os.getpid() and (len(candidates) != 1 or candidates[0].id != source.id):
                raise ValueError("窗口标题已变化或存在同名窗口，请刷新来源；也可选择对应显示器")
            generation = self.generation

            capture = WindowsCapture(cursor_capture=False, draw_border=True, window_name=source.metadata[1])

            @capture.event
            def on_frame_arrived(frame, capture_control):
                # Copy at callback boundary; WGC reuses its original buffer.
                image = Image.fromarray(frame.convert_to_bgr().frame_buffer[:, :, ::-1].copy())
                with self.lock:
                    if generation == self.generation:
                        self.latest = (image, time.monotonic(), str(uuid4()), datetime.now().astimezone())

            @capture.event
            def on_closed():
                if generation == self.generation:
                    self.closed = True

            self.control = capture.start_free_threaded()
            self.wgc = capture

    def grab(self, session, roi=(0, 0, 1, 1)):
        frame_id = str(uuid4())
        capture_time = datetime.now().astimezone()
        capture_monotonic = time.monotonic()
        if not self.source or self.closed:
            raise ValueError("采集源已关闭，请重新选择")
        if self.source.kind == "monitor":
            left, top, width, height = self.source.metadata
            capture = self.screen or mss.mss()
            self.screen = capture
            spec = dict(left=left, top=top, width=width, height=height)
            if not any(all(m.get(k) == v for k, v in spec.items()) for m in capture.monitors[1:]):
                raise ValueError("显示器已断开或分辨率变化，请重新选择")
            shot = capture.grab(spec)
            image = Image.frombytes("RGB", shot.size, shot.rgb)
        else:
            user32 = ctypes.windll.user32
            hwnd = ctypes.c_void_p(self.source.metadata[0])
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd) or pid.value != self.source.metadata[2]:
                raise ValueError("窗口已关闭或最小化，请恢复并重新选择")
            with self.lock:
                # WGC only delivers changed frames. A static window is still a valid source.
                if not self.latest:
                    raise ValueError("窗口尚无有效画面，请重试")
                image = self.latest[0].copy()
                capture_monotonic, frame_id, capture_time = self.latest[1:]
        image = image.crop(pixel_box(roi, *image.size))
        if image.getextrema() == ((0, 0), (0, 0), (0, 0)):
            raise ValueError("采集到黑帧，已暂停，请检查受保护内容或采集源")
        return FrameSnapshot(
            frame_id,
            session,
            capture_time,
            capture_monotonic,
            image.width,
            image.height,
            image.tobytes(),
        )

    def close(self):
        self.generation += 1
        if self.screen:
            self.screen.close()
            self.screen = None
        if self.control:
            self.control.stop()
            self.control = None
        self.source = None
        self.latest = None
