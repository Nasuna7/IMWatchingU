"""Compare whole-frame and tiled Windows OCR on synthetic tall regions."""
import asyncio
from datetime import datetime
from time import monotonic

from PIL import Image, ImageDraw, ImageFont

from screen_qq_ocr.domain.models import FrameSnapshot
from screen_qq_ocr.infrastructure.ocr.windows_ocr import WindowsOcr


def main():
    for height in (1800, 3600):
        image = Image.new("RGB", (180, height), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
        positions = (40, height // 2, height - 80)
        for y in positions:
            draw.text((10, y), "测试 Cerb 123", fill="black", font=font)
        frame = FrameSnapshot("synthetic", 0, datetime.now(), monotonic(), *image.size, image.tobytes())
        engine = WindowsOcr()
        before = asyncio.run(engine._recognize_tile(frame))
        after = engine.recognize(frame)
        print(f"180x{height}: whole={before.text!r}, tiled={after.text!r}, {after.elapsed_ms:.0f} ms")
        for y in positions:
            assert any("Cerb" in line.text and abs(line.y - y) < 30 for line in after.lines), after.lines


if __name__ == "__main__":
    main()
