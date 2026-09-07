import asyncio
import time
from io import BytesIO

from screen_qq_ocr.domain.models import OcrLine, OcrResult

from .preprocessing import merge_tile_lines, prepare, recognition_tiles


class WindowsOcr:
    def __init__(self, max_edge=1920):
        self.max_edge = max_edge

    def recognize(self, frame):
        return asyncio.run(self._recognize(frame))

    async def _recognize(self, frame):
        started = time.monotonic()
        parts = []
        results = []
        for tile, offset in recognition_tiles(frame, self.max_edge):
            result = await self._recognize_tile(tile)
            results.append(result)
            parts.append((result.lines, offset))
        if len(results) == 1:
            return results[0]
        lines = merge_tile_lines(parts)
        return OcrResult(
            frame,
            "Windows OCR",
            "\n".join(line.text for line in lines),
            (time.monotonic() - started) * 1000,
            lines,
        )

    async def _recognize_tile(self, frame):
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        started = time.monotonic()
        engine = OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
        if engine is None:
            raise ValueError("Windows 缺少简体中文 OCR 组件，请安装语言组件或在设置中切换 Tesseract")
        image = prepare(frame, min(self.max_edge, OcrEngine.max_image_dimension), False)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        try:
            writer.write_bytes(buffer.getvalue())
            await writer.store_async()
            writer.detach_stream()
            stream.seek(0)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            if bitmap.bitmap_pixel_format != BitmapPixelFormat.BGRA8:
                from winrt.windows.graphics.imaging import SoftwareBitmap

                bitmap = SoftwareBitmap.convert(bitmap, BitmapPixelFormat.BGRA8)
            try:
                result = await engine.recognize_async(bitmap)
                text = "\n".join(line.text for line in result.lines)
                scale_x = frame.width / image.width
                scale_y = frame.height / image.height
                lines = tuple(
                    ocr_line
                    for line in result.lines
                    if (ocr_line := self.ocr_line(line, scale_x, scale_y)) is not None
                )
            finally:
                bitmap.close()
        finally:
            writer.close()
            stream.close()
        return OcrResult(frame, "Windows OCR", text, (time.monotonic() - started) * 1000, lines)

    @staticmethod
    def ocr_line(line, scale_x, scale_y):
        boxes = [word.bounding_rect for word in line.words if getattr(word, "bounding_rect", None)]
        if not boxes:
            return None
        left = min(box.x for box in boxes)
        top = min(box.y for box in boxes)
        right = max(box.x + box.width for box in boxes)
        bottom = max(box.y + box.height for box in boxes)
        return OcrLine(
            line.text,
            left * scale_x,
            top * scale_y,
            (right - left) * scale_x,
            (bottom - top) * scale_y,
        )
