from types import SimpleNamespace

from screen_qq_ocr.infrastructure.ocr.windows_ocr import WindowsOcr


def test_windows_ocr_line_box_is_aggregated_from_words():
    line = SimpleNamespace(
        text="Cerb here",
        words=(
            SimpleNamespace(bounding_rect=SimpleNamespace(x=10, y=20, width=30, height=8)),
            SimpleNamespace(bounding_rect=SimpleNamespace(x=45, y=18, width=20, height=12)),
        ),
    )

    result = WindowsOcr.ocr_line(line, 2, 3)

    assert result.text == "Cerb here"
    assert (result.x, result.y, result.width, result.height) == (20, 54, 110, 36)
