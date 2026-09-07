import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from screen_qq_ocr.application.monitor_tasks import MonitorTasks, TaskQueue
from screen_qq_ocr.application.monitoring import Monitoring
from screen_qq_ocr.application.sending import SendQueue
from screen_qq_ocr.domain.models import KeywordRule, OcrResult, SendPolicy, SendTask
from screen_qq_ocr.infrastructure.persistence.database import Database
from screen_qq_ocr.infrastructure.persistence.settings import Settings


async def test_independent_regions_workers_stop_and_shared_rules(tmp_path, frame, target):
    queue = SendQueue(SimpleNamespace(online=True, targets=[target]), lambda _: b"png")
    db = Database(tmp_path / "tasks.db")
    db.save_rule(KeywordRule("test", min_count=2))
    db.save_policy(SendPolicy(target=target))
    settings = Settings(tmp_path / "settings.json")
    events = []

    class Capture:
        def open(self, source):
            self.source = source

        def grab(self, session, roi):
            width = max(1, round(64 * roi[2]))
            height = max(1, round(64 * roi[3]))
            return replace(
                frame,
                session_id=session,
                width=width,
                height=height,
                rgb=bytes([255, 0, 0]) * width * height,
            )

        def close(self):
            pass

    class Ocr:
        async def availability(self, _):
            pass

        async def recognize(self, frame, _):
            return OcrResult(frame, "fake", "test test", 1)

    manager = MonitorTasks(
        lambda task_id, emit: Monitoring(
            Capture(), Ocr(), TaskQueue(queue, task_id), queue.messaging, db, settings, lambda _: "红", emit
        ),
        lambda *event: events.append(event),
    )
    try:
        first_id, first = manager.selected, manager.current
        source = SimpleNamespace(id="same-window", title="test")
        await first.select_source(source, (0, 0, 0.5, 1))
        await first.start(True, True)
        await manager.add()
        second = manager.current
        await second.select_source(source, (0.5, 0, 0.5, 1))
        await second.start(True, True)
        await asyncio.sleep(0.1)
        assert first.active and second.active
        assert first.capture is not second.capture and first.ocr_worker is not second.ocr_worker
        assert first.last_preview.width == 64 and first.last_frame.width == 32
        assert len(queue.pending) == 2
        assert len({task.monitor_id for task in queue.pending}) == 2
        preview = await first.preview(first.rules[0].id)
        with pytest.raises(ValueError, match="过期"):
            await second.test_send(preview)
        await manager.select_task(first_id)
        assert second.active
        await first.stop()
        assert second.active and len(queue.pending) == 1
        assert queue.pending[0].monitor_id != first_id
        await second.set_roi((0, 0, 1, 1))
        assert second.active and second.last_frame.width == 64
        await manager.save_rule(replace(first.rules[0], min_count=3, revision=2))
        assert all(app.rules[0].min_count == 3 and not app.keywords for _, app in manager.tasks.values())
    finally:
        await manager.shutdown()


def test_scoped_cancellation_does_not_cancel_other_task_current_send(frame, target):
    queue = SendQueue(None, lambda _: b"png")
    task = SendTask(1, "rule", 1, SendPolicy(target=target), frame, "text", 0)
    first, second = TaskQueue(queue, "a"), TaskQueue(queue, "b")
    assert first.accept(task) and second.accept(task)
    queue.current = queue.pending.pop()
    first.cancel()
    assert not queue.pending and queue.current.task_id not in queue.cancelled



async def test_monitor_tasks_persist_and_restore_window_by_process_name(tmp_path, frame, target):
    frame = replace(frame, width=100, height=80, rgb=bytes([255, 0, 0]) * 8000)
    saved = []
    queue = SendQueue(SimpleNamespace(online=True, targets=[target]), lambda _: b"png")
    db = Database(tmp_path / "restore.db")
    db.save_rule(KeywordRule("test"))
    db.save_policy(SendPolicy(target=target))
    settings = Settings(tmp_path / "settings.json")

    class Capture:
        def __init__(self):
            self.opened = []

        def open(self, source):
            self.opened.append(source)

        def grab(self, session, roi):
            return replace(frame, session_id=session)

        def close(self):
            pass

    class Ocr:
        async def availability(self, _):
            pass

        async def recognize(self, frame, _):
            return OcrResult(frame, "fake", "test", 1)

        async def shutdown(self):
            pass

    def factory(task_id, emit):
        return Monitoring(
            Capture(), Ocr(), TaskQueue(queue, task_id), queue.messaging, db, settings, lambda _: "红", emit
        )

    first_source = SimpleNamespace(
        id="window:111",
        stable_id="eve-character:regular decending semitone",
        title="EVE - Regular Decending Semitone",
        kind="window",
        metadata=(111, "EVE - Regular Decending Semitone", 1001, "exefile.exe"),
    )
    manager = MonitorTasks(factory, lambda *event: None, lambda: [], lambda configs: saved.append(configs))
    await manager.current.select_source(first_source, (0.1, 0.2, 0.3, 0.4))
    manager.current.image_roi = (0.2, 0.3, 0.4, 0.5)
    manager.current.keywords = True
    manager.current.flash_enabled = True
    manager.persist()

    restored = MonitorTasks(factory, lambda *event: None, lambda: saved[-1], lambda configs: saved.append(configs))
    new_source = SimpleNamespace(
        id="window:999",
        stable_id="eve-character:regular decending semitone",
        title="EVE - Regular Decending Semitone",
        kind="window",
        metadata=(999, "EVE - Regular Decending Semitone", 2002, "exefile.exe"),
    )

    await restored.restore_sources([new_source])

    app = restored.current
    assert app.source is new_source
    assert app.roi == (0.1, 0.2, 0.3, 0.4)
    assert app.image_roi == (0.2, 0.3, 0.4, 0.5)
    assert app.keywords is True and app.flash_enabled is True
    assert saved[-1][0]["source"]["stable_id"] == "eve-character:regular decending semitone"


async def test_monitor_tasks_keep_unresolved_saved_source_until_refresh(tmp_path, frame, target):
    saved_config = [
        {
            "id": "task-a",
            "name": "任务 1",
            "source": {
                "id": "window:111",
                "stable_id": "eve-character:7th life v",
                "title": "EVE - 7th life V",
                "kind": "window",
                "process_name": "exefile.exe",
            },
            "roi": [0, 0, 0.5, 1],
            "image_roi": [0.25, 0, 0.5, 1],
            "keywords": False,
            "flash": True,
        }
    ]
    queue = SendQueue(SimpleNamespace(online=True, targets=[target]), lambda _: b"png")
    db = Database(tmp_path / "unresolved.db")
    db.save_policy(SendPolicy(target=target))
    settings = Settings(tmp_path / "settings.json")

    class Capture:
        def open(self, source):
            pass

        def grab(self, session, roi):
            return frame

        def close(self):
            pass

    class Ocr:
        async def availability(self, _):
            pass

        async def recognize(self, frame, _):
            return OcrResult(frame, "fake", "", 1)

    manager = MonitorTasks(
        lambda task_id, emit: Monitoring(
            Capture(), Ocr(), TaskQueue(queue, task_id), queue.messaging, db, settings, lambda _: "红", emit
        ),
        lambda *event: None,
        lambda: saved_config,
        lambda configs: None,
    )

    await manager.restore_sources([])

    assert manager.current.source is None
    assert manager.current.saved_source["stable_id"] == "eve-character:7th life v"
    assert manager.current.roi == (0, 0, 0.5, 1)
    assert manager.current.image_roi == (0.25, 0, 0.5, 1)
    assert manager.current.keywords is False and manager.current.flash_enabled is True
