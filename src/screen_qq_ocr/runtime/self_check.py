import json
import platform
import time
from datetime import datetime

import PySide6
from PIL import Image, ImageDraw, ImageFont

from screen_qq_ocr.domain.models import FrameSnapshot

from .workers import OcrWorker


async def run(path):
    from windows_capture import WindowsCapture
    from winrt.windows.media.ocr import OcrEngine

    report = {
        "python": platform.python_version(),
        "windows": platform.platform(),
        "pyside6": PySide6.__version__,
        "windows_capture_import": WindowsCapture is not None,
        "languages": [x.language_tag for x in OcrEngine.available_recognizer_languages],
    }
    image = Image.new("RGB", (800, 160), "white")
    ImageDraw.Draw(image).text(
        (20, 40),
        "屏幕识别测试 Cerb 12345",
        fill="black",
        font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 40),
    )
    frame = FrameSnapshot(
        "synthetic", 0, datetime.now().astimezone(), time.monotonic(), *image.size, image.tobytes()
    )
    try:
        result = await OcrWorker().recognize(frame, {"engine": "windows", "max_edge": 1920})
        report.update(ocr_success="Cerb" in result.text, ocr_text=result.text, elapsed_ms=result.elapsed_ms)
    except Exception as error:
        report.update(ocr_success=False, error=str(error))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report["ocr_success"]
