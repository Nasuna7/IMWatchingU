"""Capture an owned synthetic fixture process via WGC, never the desktop."""

import json
import multiprocessing
import os
import time
from pathlib import Path

from screen_qq_ocr.infrastructure.capture.windows_capture import Capture, CaptureSource
from screen_qq_ocr.infrastructure.ocr.preprocessing import encode_png


def fixture(connection):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication([])
    window = QLabel("ScreenQQOCR synthetic WGC probe")
    window.setWindowTitle(f"ScreenQQOCR capture probe {os.getpid()}")
    window.setStyleSheet("background: white; color: red; font-size: 24px; padding: 24px;")
    window.resize(600, 200)
    window.show()
    connection.send((int(window.winId()), window.windowTitle(), os.getpid()))
    timer = QTimer()
    animated = True

    def tick():
        nonlocal animated
        if animated:
            window.setText(f"ScreenQQOCR synthetic WGC probe {time.monotonic():.1f}")
        if connection.poll():
            if connection.recv() == "static":
                animated = False
            else:
                app.exit(0)

    timer.timeout.connect(tick)
    timer.start(100)
    app.exec()


def main():
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=fixture, args=(child,))
    process.start()
    child.close()
    capture = Capture()
    second_capture = Capture()
    output = Path(__file__).resolve().parents[1] / "artifacts"
    output.mkdir(exist_ok=True)
    try:
        if not parent.poll(5):
            raise RuntimeError("Synthetic window failed to start")
        metadata = parent.recv()
        source = CaptureSource(f"window:{metadata[0]}", metadata[1], "window", metadata)
        capture.open(source)
        second_capture.open(source)
        deadline = time.monotonic() + 10
        while True:
            try:
                frame = capture.grab(1, (0, 0, 0.5, 1))
                second = second_capture.grab(2, (0.5, 0, 0.5, 1))
                assert frame.width >= 16 and frame.height >= 16
                assert second.width >= 16 and second.session_id == 2
                parent.send("static")
                time.sleep(3)
                static = capture.grab(1, (0, 0, 0.5, 1))
                capture.close()
                assert second_capture.grab(2, (0.5, 0, 0.5, 1)).width == second.width
                (output / "capture-probe.png").write_bytes(encode_png(frame))
                (output / "capture-probe.json").write_text(
                    json.dumps(
                        {
                            "success": True,
                            "width": frame.width,
                            "height": frame.height,
                            "parallel_regions": True,
                            "static_window": static.width == frame.width,
                            "independent_stop": True,
                        }
                    ),
                    encoding="utf-8",
                )
                print("WGC parallel regions, static frame and independent stop:", frame.width, frame.height)
                break
            except ValueError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
    finally:
        capture.close()
        second_capture.close()
        if process.is_alive():
            parent.send("stop")
            process.join(timeout=2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        parent.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
