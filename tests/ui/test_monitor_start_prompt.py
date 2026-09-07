from types import SimpleNamespace

import pytest

from screen_qq_ocr.ui.presenters import Presenter
from screen_qq_ocr.ui.widgets import controls


class RaisingApp:
    def __init__(self, message):
        self.message = message

    async def start(self, *_):
        raise ValueError(self.message)


@pytest.mark.asyncio
async def test_start_monitor_prompts_when_qq_is_not_ready():
    events = []
    presenter = SimpleNamespace(
        app=RaisingApp("QQ 消息通道尚未就绪"),
        emit=lambda kind, value: events.append((kind, value)),
    )

    await Presenter.start_monitor(presenter, True, False)

    assert len(events) == 1
    assert events[0][0] == "start_blocked"
    assert "QQ 尚未登录" in events[0][1]
    assert "QQ 消息通道尚未就绪" in events[0][1]


@pytest.mark.asyncio
async def test_start_monitor_keeps_non_qq_start_errors_in_normal_error_flow():
    presenter = SimpleNamespace(
        app=RaisingApp("请先选择并验证采集源"),
        emit=lambda *_: None,
    )

    with pytest.raises(ValueError, match="采集源"):
        await Presenter.start_monitor(presenter, True, False)


def test_start_blocked_event_uses_custom_message_box(monkeypatch):
    records = []
    calls = []
    window = SimpleNamespace(
        status_labels={},
        records=SimpleNamespace(appendPlainText=records.append),
    )
    presenter = SimpleNamespace(window=window)
    monkeypatch.setattr(
        controls.MessageBox,
        "critical",
        lambda parent, title, text: calls.append((parent, title, text)),
    )

    Presenter.on_event(presenter, "start_blocked", "QQ 尚未登录或消息通道未连接")

    assert records == ["error · QQ 尚未登录或消息通道未连接"]
    assert calls == [(window, "无法开始监控", "QQ 尚未登录或消息通道未连接")]
