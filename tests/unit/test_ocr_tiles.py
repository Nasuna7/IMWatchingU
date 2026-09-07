from datetime import datetime

import pytest

from screen_qq_ocr.domain.models import FrameSnapshot, OcrLine, OcrResult
from screen_qq_ocr.infrastructure.ocr.preprocessing import merge_tile_lines, recognition_tiles
from screen_qq_ocr.infrastructure.ocr.tesseract import Tesseract
from screen_qq_ocr.infrastructure.ocr.windows_ocr import WindowsOcr


def frame(width=100, height=1800):
    rgb = b"".join(bytes([y % 256]) * width * 3 for y in range(height))
    return FrameSnapshot("test", 1, datetime.now(), 0, width, height, rgb)


def test_tiles_cover_every_row_and_preserve_pixels():
    original = frame()
    covered = set()
    for tile, offset in recognition_tiles(original, 1920):
        assert tile.width == original.width
        assert tile.height <= 256
        assert tile.rgb == original.rgb[offset * 300:(offset + tile.height) * 300]
        covered.update(range(offset, offset + tile.height))
    assert covered == set(range(original.height))


def test_regular_frame_is_unchanged():
    original = frame(800, 600)
    assert list(recognition_tiles(original, 1920)) == [(original, 0)]


def test_overlap_deduplicates_same_location_but_keeps_repeated_text_elsewhere():
    lines = merge_tile_lines([
        ((OcrLine("hello", 10, 210, 60, 20),), 0),
        ((OcrLine("hello", 10, 18, 60, 20), OcrLine("hello", 10, 80, 60, 20)), 192),
    ])
    assert [line.y for line in lines] == [210, 272]
    assert [line.text for line in lines] == ["hello", "hello"]


@pytest.mark.parametrize("engine_type", [WindowsOcr, Tesseract])
def test_engine_restores_middle_line_coordinates(monkeypatch, engine_type):
    original = frame()
    calls = []

    def recognize(tile):
        offset = calls[-1] + 192 if calls else 0
        calls.append(offset)
        lines = (OcrLine("middle", 10, 900 - offset, 60, 20),) if offset <= 900 < offset + tile.height else ()
        return OcrResult(tile, "fake", "\n".join(line.text for line in lines), 0, lines)

    async def recognize_async(tile):
        return recognize(tile)

    engine = engine_type()
    monkeypatch.setattr(engine, "_recognize_tile", recognize_async if engine_type is WindowsOcr else recognize)
    result = engine.recognize(original)
    assert len(calls) > 1
    assert result.frame is original
    assert result.text == "middle"
    assert result.lines == (OcrLine("middle", 10, 900, 60, 20),)
