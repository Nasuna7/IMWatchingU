"""Local synthetic OCR probe: no screenshot and no QQ network traffic."""

from datetime import datetime
from time import monotonic

from PIL import Image, ImageDraw, ImageFont

from screen_qq_ocr.domain.models import FrameSnapshot
from screen_qq_ocr.infrastructure.ocr.windows_ocr import WindowsOcr


def main():
    image = Image.new("RGB", (800, 160), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 40)
    draw.text((25, 40), "屏幕识别测试 Cerb Cerb 12345", fill="black", font=font)
    frame = FrameSnapshot(
        "synthetic", 0, datetime.now().astimezone(), monotonic(), *image.size, image.tobytes()
    )
    result = WindowsOcr().recognize(frame)
    print(result.text)
    print(f"{result.elapsed_ms:.0f} ms")
    assert "Cerb" in result.text


if __name__ == "__main__":
    main()
