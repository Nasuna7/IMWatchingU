from datetime import datetime, timezone

import pytest

from screen_qq_ocr.domain.models import FrameSnapshot, QQTarget


@pytest.fixture
def frame():
    return FrameSnapshot(
        "frame-1", 1, datetime(2026, 9, 5, tzinfo=timezone.utc), 0, 16, 16, bytes([255, 0, 0]) * 256
    )


@pytest.fixture
def target():
    return QQTarget("123456", "private", "789012", "合成测试对象")
