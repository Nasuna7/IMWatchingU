import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from PIL import Image

from screen_qq_ocr.infrastructure.capture import windows_capture as module


def test_monitor_extra_metadata_is_not_disconnected(monkeypatch):
    spec = dict(left=-1920, top=0, width=1920, height=1080)
    monitor = dict(spec, is_primary=True, name="Display", unique_id="id")

    class Desktop:
        monitors = [spec, monitor]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def grab(self, requested):
            assert requested == spec
            return SimpleNamespace(size=(1920, 1080), rgb=b"\xff\x00\x00" * 1920 * 1080)

    monkeypatch.setattr(module.mss, "mss", Desktop)
    capture = module.Capture()
    capture.open(module.CaptureSource("monitor:1", "primary", "monitor", tuple(spec.values())))
    assert capture.grab(1).width == 1920
    Desktop.monitors = [spec]
    with pytest.raises(ValueError, match="断开"):
        capture.grab(1)


def test_monitor_capture_reuses_mss_instance(monkeypatch):
    spec = dict(left=0, top=0, width=32, height=32)
    created = []

    class Desktop:
        monitors = [spec, spec]

        def __init__(self):
            created.append(self)

        def grab(self, requested):
            assert requested == spec
            return SimpleNamespace(size=(32, 32), rgb=b"\xff\x00\x00" * 32 * 32)

        def close(self):
            pass

    monkeypatch.setattr(module.mss, "mss", Desktop)
    capture = module.Capture()
    capture.open(module.CaptureSource("monitor:1", "primary", "monitor", tuple(spec.values())))
    capture.grab(1)
    capture.grab(1)
    assert len(created) == 1


def test_static_window_frame_remains_valid_but_minimized_window_fails(monkeypatch):
    user32 = SimpleNamespace(IsWindow=lambda _: True, IsIconic=lambda _: False)

    def pid(_, pointer):
        pointer._obj.value = 456

    user32.GetWindowThreadProcessId = pid
    monkeypatch.setattr(module.ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    capture = module.Capture()
    capture.source = module.CaptureSource("window:123", "fixture", "window", (123, "fixture", 456))
    capture.latest = (
        Image.new("RGB", (32, 32), "red"),
        time.monotonic() - 60,
        "static-frame",
        datetime.now().astimezone(),
    )
    assert capture.grab(2).frame_id == "static-frame"
    user32.IsIconic = lambda _: True
    with pytest.raises(ValueError, match="最小化"):
        capture.grab(2)
