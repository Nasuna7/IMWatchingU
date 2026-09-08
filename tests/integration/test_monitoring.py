import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

from screen_qq_ocr.application.monitoring import Monitoring
from screen_qq_ocr.application.ports import CaptureNotReady
from screen_qq_ocr.application.sending import SendQueue
from screen_qq_ocr.domain.models import KeywordRule, OcrLine, OcrResult, SendPolicy
from screen_qq_ocr.infrastructure.persistence.database import Database
from screen_qq_ocr.infrastructure.persistence.settings import Settings


class Capture:
    def __init__(self, frame):
        self.frame = frame
        self.counter = 0
        self.source = None
        self.opens = 0
        self.closes = 0

    def open(self, source):
        self.opens += 1
        self.source = source

    def grab(self, session, roi):
        self.counter += 1
        return replace(self.frame, session_id=session, frame_id=str(self.counter))

    def close(self):
        self.closes += 1


class RoiAwareCapture(Capture):
    def __init__(self, frame):
        super().__init__(frame)
        self.rois = []

    def grab(self, session, roi):
        self.rois.append(roi)
        if roi == (0, 0, 1, 1):
            return super().grab(session, roi)
        self.counter += 1
        x, y, w, h = roi
        width = round(self.frame.width * w)
        height = round(self.frame.height * h)
        return replace(
            self.frame,
            session_id=session,
            frame_id=str(self.counter),
            width=width,
            height=height,
            rgb=self.frame.rgb[: width * height * 3],
        )


class Ocr:
    def __init__(self, gate=None, fail=False, lines=()):
        self.gate = gate
        self.fail = fail
        self.lines = lines
        self.calls = 0
        self.frames = []
        self.shutdowns = 0

    async def availability(self, options):
        pass

    async def shutdown(self):
        self.shutdowns += 1

    async def recognize(self, frame, options):
        self.calls += 1
        self.frames.append(frame)
        if self.gate:
            await self.gate.wait()
        if self.fail:
            raise ValueError("synthetic error")
        return OcrResult(frame, "fake", "\n".join(line.text for line in self.lines) or "Cerb", 0, self.lines)


def create(tmp_path, frame, target, ocr):
    db = Database(tmp_path / "app.db")
    db.save_rule(KeywordRule("Cerb"))
    db.save_policy(SendPolicy(target=target))
    messaging = SimpleNamespace(online=True, targets=[target])
    queue = SendQueue(messaging, lambda frame: b"png")
    events = []
    app = Monitoring(
        Capture(frame),
        ocr,
        queue,
        messaging,
        db,
        Settings(tmp_path / "settings.json"),
        lambda frame: "red",
        lambda kind, value: events.append((kind, value)),
    )
    app.source = "synthetic"
    app.roi = (0, 0, 1, 1)
    return app, events


async def test_manual_ocr_and_preview_never_enqueue(tmp_path, frame, target):
    app, events = create(tmp_path, frame, target, Ocr())
    await app.reload()
    await app.recognize_once()
    await app.ocr_task
    assert app.last_result.text == "Cerb" and not app.queue.pending
    before = dict(app.triggers.states)
    await app.preview(app.rules[0].id)
    assert app.triggers.states == before
    assert not app.queue.cooldowns.accepted_at


async def test_preview_waits_for_pending_default_policy_save(tmp_path, frame, target):
    app, events = create(tmp_path, frame, target, Ocr())
    await app.reload()
    app.last_frame = frame
    app.last_result = OcrResult(frame, "fake", "Cerb", 0)
    original_save = app.store.save_policy
    save_gate = threading.Event()

    def slow_save(policy):
        save_gate.wait(2)
        original_save(policy)

    app.store.save_policy = slow_save
    saving = asyncio.create_task(app.save_policy(SendPolicy(body_source="fixed", body="new", target=target)))
    await asyncio.sleep(0)
    preview = asyncio.create_task(app.preview(app.rules[0].id, "Cerb"))
    await asyncio.sleep(0)
    assert not preview.done()
    save_gate.set()
    task = await preview
    await saving
    assert task.text == "new"


async def test_preview_uses_separate_image_region(tmp_path, frame, target):
    source = replace(frame, width=32, height=32, rgb=frame.rgb * 4)
    app, events = create(tmp_path, source, target, Ocr())
    await app.reload()
    app.last_preview = source
    app.last_frame = source
    app.last_result = OcrResult(source, "fake", "Cerb", 0)
    await app.set_image_roi((0, 0, 0.5, 1))
    task = await app.preview(app.rules[0].id, "Cerb")
    assert task.frame.width == 16
    assert task.frame.height == 32


async def test_recognize_once_uses_monitor_roi_not_preview_or_image_roi(tmp_path, frame, target):
    source = replace(frame, width=100, height=80, rgb=bytes([255, 0, 0]) * 8000)
    ocr = Ocr()
    app, events = create(tmp_path, source, target, ocr)
    app.capture = RoiAwareCapture(source)
    app.image_roi = (0, 0, 1, 0.25)
    await app.grab_frame(force_preview=True)
    await app.set_roi((0.2, 0.25, 0.5, 0.5))

    await app.recognize_once()
    await app.ocr_task

    assert len(ocr.frames) == 1
    assert ocr.frames[0].width == 50
    assert ocr.frames[0].height == 40


async def test_select_source_captures_static_preview_without_touching_ocr(tmp_path, frame, target):
    ocr = Ocr()
    app, events = create(tmp_path, frame, target, ocr)

    await app.select_source(type("Source", (), {"title": "synthetic"})())

    assert app.source is not None
    assert app.last_preview is not None
    assert app.last_frame is not None
    assert app.capture.opens == 1
    assert app.capture.closes == 1  # Idle source selection releases WGC after the static preview.
    assert not app.capture_open
    assert ocr.calls == 0
    assert [kind for kind, _ in events].count("frame") == 1


async def test_inactive_roi_change_does_not_update_preview(tmp_path, frame, target):
    source = replace(frame, width=100, height=80, rgb=bytes([255, 0, 0]) * 8000)
    app, events = create(tmp_path, source, target, Ocr())
    app.last_preview = source

    await app.set_roi((0.1, 0.2, 0.3, 0.4))

    assert app.roi == (0.1, 0.2, 0.3, 0.4)
    assert app.last_frame is None
    assert not any(kind == "frame" for kind, _ in events)


async def test_inactive_recognize_once_does_not_update_preview(tmp_path, frame, target):
    ocr = Ocr()
    app, events = create(tmp_path, frame, target, ocr)
    app.capture = RoiAwareCapture(frame)
    app.roi = (0, 0, 0.5, 1)

    await app.recognize_once()
    await app.ocr_task

    assert ocr.frames[0].width == frame.width // 2
    assert not app.capture_open
    assert not any(kind == "frame" for kind, _ in events)


async def test_grab_frame_captures_roi_directly_when_preview_is_not_due(tmp_path, frame, target):
    source = replace(frame, width=100, height=80, rgb=bytes([255, 0, 0]) * 8000)
    app, events = create(tmp_path, source, target, Ocr())
    capture = RoiAwareCapture(source)
    app.capture = capture
    app.roi = (0.2, 0.25, 0.5, 0.5)
    app.next_preview = 999999999

    result = await app.grab_frame()

    assert capture.rois == [(0.2, 0.25, 0.5, 0.5)]
    assert result.width == 50
    assert result.height == 40
    assert not any(kind == "frame" for kind, _ in events)


async def test_grab_frame_throttles_live_preview_events(tmp_path, frame, target):
    app, events = create(tmp_path, frame, target, Ocr())

    await app.grab_frame(force_preview=True)
    await app.grab_frame()
    await app.grab_frame()

    assert [kind for kind, _ in events].count("frame") == 1


async def test_capture_loop_reads_monitor_roi_on_configured_interval(tmp_path, frame, target):
    source = replace(frame, width=100, height=80, rgb=bytes([255, 0, 0]) * 8000)
    ocr = Ocr()
    app, events = create(tmp_path, source, target, ocr)
    capture = RoiAwareCapture(source)
    app.capture = capture
    app.roi = (0.2, 0.25, 0.5, 0.5)
    app.settings.values["capture"]["read_interval"] = 0.2

    await app.start(False, True)
    await asyncio.sleep(0.46)
    await app.stop()

    assert 1 <= len(capture.rois) <= 4
    assert all(roi == (0.2, 0.25, 0.5, 0.5) for roi in capture.rois)
    assert not any(kind == "frame" for kind, _ in events)
    assert app.last_frame.width == 50
    assert app.last_frame.height == 40
    assert ocr.calls == 0


def test_automatic_ocr_requires_frame_change(tmp_path, frame, target):
    app, events = create(tmp_path, frame, target, Ocr())

    assert app.mark_changed_for_ocr(frame)
    assert not app.mark_changed_for_ocr(replace(frame, frame_id="same-pixels"))
    changed = replace(frame, rgb=bytes([0, 255, 0]) * (frame.width * frame.height))
    assert app.mark_changed_for_ocr(changed)


async def test_send_image_height_follows_matched_ocr_line(tmp_path, frame, target):
    source = replace(frame, width=100, height=100, rgb=bytes([255, 255, 255]) * 10000)
    ocr_frame = replace(source, width=100, height=50, rgb=bytes([255, 255, 255]) * 5000)
    line = OcrLine("Cerb", 10, 20, 30, 10)
    app, events = create(tmp_path, source, target, Ocr(lines=(line,)))
    await app.reload()
    app.session = ocr_frame.session_id
    app.active = app.keywords = True
    app.roi = (0, 0.2, 1, 0.5)
    app.image_roi = (0.25, 0, 0.5, 1)
    app.last_preview = source

    await app._recognize(ocr_frame, automatic=True)

    task = app.queue.pending[0]
    assert task.frame.width == 50
    assert task.frame.height == 18


async def test_non_silent_monitor_releases_ocr_worker_after_each_result(tmp_path, frame, target):
    ocr = Ocr()
    app, events = create(tmp_path, frame, target, ocr)
    await app.reload()
    app.settings.values["lifecycle"]["close_to_tray"] = False
    app.active = app.keywords = True

    await app._recognize(replace(frame, session_id=app.session), automatic=True)

    assert ocr.shutdowns == 1


async def test_silent_monitor_keeps_ocr_worker_warm_between_results(tmp_path, frame, target):
    ocr = Ocr()
    app, events = create(tmp_path, frame, target, ocr)
    await app.reload()
    app.settings.values["lifecycle"]["close_to_tray"] = True
    app.active = app.keywords = True

    await app._recognize(replace(frame, session_id=app.session), automatic=True)

    assert ocr.shutdowns == 0


async def test_late_ocr_after_stop_is_discarded(tmp_path, frame, target):
    gate = asyncio.Event()
    app, events = create(tmp_path, frame, target, Ocr(gate))
    await app.reload()
    app.active = app.keywords = True
    old = replace(frame, session_id=app.session)
    app.ocr_task = asyncio.create_task(app._recognize(old, True))
    operation = app.ocr_task
    await asyncio.sleep(0)
    await app.stop()
    gate.set()
    await operation
    assert not app.queue.pending and app.last_result is None


async def test_color_only_needs_no_qq_or_ocr(tmp_path, frame, target):
    ocr = Ocr(fail=True)
    app, events = create(tmp_path, frame, target, ocr)
    app.messaging.online = False
    await app.start(False, True)
    await asyncio.sleep(0.1)
    assert app.active and ocr.calls == 0
    await app.shutdown()


async def test_three_ocr_errors_keep_flash_running(tmp_path, frame, target):
    app, events = create(tmp_path, frame, target, Ocr(fail=True))
    await app.reload()
    app.active = app.keywords = app.flash_enabled = True
    for i in range(3):
        await app._recognize(replace(frame, session_id=app.session, frame_id=str(i)), True)
    assert not app.keywords and app.flash_enabled and app.active


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


class DelayedCapture(Capture):
    def __init__(self, frame):
        super().__init__(frame)
        self.waits = 2

    def grab(self, session, roi):
        if self.waits:
            self.waits -= 1
            raise CaptureNotReady("窗口尚无有效画面，请重试")
        return super().grab(session, roi)


async def test_automatic_ocr_waits_for_first_frame_and_publishes_changes(tmp_path, frame, target):
    ocr = Ocr(lines=(OcrLine("无关键词", 0, 0, 10, 10),))
    app, events = create(tmp_path, frame, target, ocr)
    app.capture = DelayedCapture(frame)
    app.settings.values["capture"]["read_interval"] = 0.2
    app.settings.values["ocr"]["interval"] = 0
    try:
        await app.start(True, False)
        await wait_until(lambda: len([e for e in events if e[0] == "ocr"]) == 1)
        assert app.active and not app.queue.pending
        await asyncio.sleep(0.45)
        assert ocr.calls == 1
        app.capture.frame = replace(frame, rgb=bytes([0, 255, 0]) * frame.width * frame.height)
        await wait_until(lambda: len([e for e in events if e[0] == "ocr"]) == 2)
        assert app.last_result.frame.rgb == app.capture.frame.rgb
        assert not any(kind == "error" for kind, _ in events)
    finally:
        await app.shutdown()


async def test_manual_ocr_waits_for_reopened_capture(tmp_path, frame, target):
    app, events = create(tmp_path, frame, target, Ocr())
    app.capture = DelayedCapture(frame)
    try:
        await app.recognize_once()
        await app.ocr_task
        assert app.last_result.text == "Cerb"
        assert not app.capture_open
    finally:
        await app.shutdown()


async def test_automatic_ocr_retries_failed_unchanged_frame(tmp_path, frame, target):
    ocr = Ocr(fail=True)
    app, events = create(tmp_path, frame, target, ocr)
    app.settings.values["capture"]["read_interval"] = 0.2
    app.settings.values["ocr"]["interval"] = 0
    try:
        await app.start(True, True)
        await wait_until(lambda: not app.keywords)
        assert ocr.calls == 3
        assert app.active and app.flash_enabled
        assert len([e for e in events if e[0] == "error"]) == 3
    finally:
        await app.shutdown()

