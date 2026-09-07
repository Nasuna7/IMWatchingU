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
