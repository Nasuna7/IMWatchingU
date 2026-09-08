from types import SimpleNamespace

from screen_qq_ocr.domain.models import OcrResult
from screen_qq_ocr.ui.pages.monitor_page import MonitorPage
from screen_qq_ocr.ui.presenters import Presenter


def test_ocr_event_refreshes_recent_text_and_clears_empty_result(qtbot, frame):
    page = MonitorPage()
    qtbot.addWidget(page)
    presenter = SimpleNamespace(window=SimpleNamespace(status_labels={}, monitor=page))

    Presenter.on_event(presenter, "ocr", OcrResult(frame, "fake", "画面变化后的文字", 12))
    assert page.ocr.toPlainText() == "画面变化后的文字"
    assert "12 ms" in page.meta.text()

    Presenter.on_event(presenter, "ocr", OcrResult(frame, "fake", "", 8))
    assert page.ocr.toPlainText() == ""
    assert "0 字符" in page.meta.text()
