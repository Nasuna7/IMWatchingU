import asyncio
from types import SimpleNamespace

import pytest

from screen_qq_ocr.ui.presenters import Presenter


@pytest.mark.asyncio
async def test_fullscreen_monitor_picker_applies_normalized_roi_directly(monkeypatch):
    selected = (0.2, 0.25, 0.5, 0.5)
    calls = []
    scheduled = []

    class App:
        last_preview = SimpleNamespace(width=100, height=80)
        roi = (0, 0, 1, 1)
        image_roi = (0, 0, 1, 1)

        async def set_roi(self, roi):
            calls.append(roi)

    class Preview:
        def submit_roi(self, roi):
            raise AssertionError("fullscreen picker should not round-trip through preview.submit_roi")

    from screen_qq_ocr.ui.widgets import preview as preview_module

    monkeypatch.setattr(
        preview_module.RoiPickerDialog,
        "pick",
        lambda *args: selected,
    )
    presenter = SimpleNamespace(
        app=SimpleNamespace(current=App()),
        window=SimpleNamespace(monitor=SimpleNamespace(preview=Preview())),
        run=lambda coroutine: scheduled.append(coroutine),
        on_event=lambda *_: None,
    )

    Presenter.pick_roi(presenter, "monitor")
    await scheduled[0]

    assert calls == [selected]


@pytest.mark.asyncio
async def test_roi_submissions_are_serialized_per_task():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls, events = [], []

    class App:
        last_preview = SimpleNamespace(width=400, height=400)
        roi = (0, 0, 1, 1)

        async def set_roi(self, roi):
            calls.append(roi)
            if len(calls) == 1:
                entered.set()
                await release.wait()
            self.roi = roi

    app = App()
    presenter = SimpleNamespace(_roi_locks={}, emit=lambda *args: events.append(args))
    first = asyncio.create_task(Presenter.roi(presenter, (0.1, 0.1, 0.4, 0.4), app, 1))
    await entered.wait()
    second = asyncio.create_task(Presenter.roi(presenter, (0.2, 0.2, 0.5, 0.5), app, 2))
    await asyncio.sleep(0)
    assert len(calls) == 1
    release.set()
    await asyncio.gather(first, second)
    assert len(calls) == 2
    assert app.roi == pytest.approx((0.2, 0.2, 0.3, 0.3))
    assert [event[1][0] for event in events] == [1, 2]


@pytest.mark.asyncio
async def test_roi_validation_failure_acknowledges_actual_state():
    class App:
        last_preview = None
        roi = (0.1, 0.1, 0.3, 0.3)

    events = []
    presenter = SimpleNamespace(_roi_locks={}, emit=lambda *args: events.append(args))
    with pytest.raises(ValueError):
        await Presenter.roi(presenter, (0, 0, 1, 1), App(), 7)
    assert events == [("roi_result", (7, (0.1, 0.1, 0.3, 0.3)))]
