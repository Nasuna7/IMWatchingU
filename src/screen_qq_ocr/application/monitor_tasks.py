from dataclasses import replace
from uuid import uuid4


class TaskQueue:
    """Keep one global send scheduler, with cancellation and cooldowns scoped to a monitor."""

    def __init__(self, queue, monitor_id):
        self.queue, self.monitor_id = queue, monitor_id

    def __getattr__(self, name):
        return getattr(self.queue, name)

    def accept(self, task):
        return self.queue.accept(replace(task, monitor_id=self.monitor_id))

    def cancel(self, rule_id=None):
        self.queue.cancel(rule_id, monitor_id=self.monitor_id)


class MonitorTasks:
    """Each task owns capture, OCR process, ROI and trigger state. Rules are shared."""

    def __init__(self, factory, emit):
        self.factory, self.emit = factory, emit
        self.tasks = {}
        self.selected = None
        self.serial = 0
        self._add()

    @property
    def current(self):
        return self.tasks[self.selected][1]

    def __getattr__(self, name):
        return getattr(self.current, name)

    def _add(self):
        task_id = str(uuid4())
        self.serial += 1
        name = f"任务 {self.serial}"

        def event(kind, value):
            if kind in ("error", "info"):
                self.emit(kind, f"{name}：{value}")
            elif kind == "sound_stop":
                if not any(app.active and app.flash_enabled for _, app in self.tasks.values()):
                    self.emit(kind, value)
            elif kind in ("rules", "policy", "sound") or self.selected == task_id:
                self.emit(kind, value)
            if kind in ("monitor_status", "capture_status"):
                self.publish_tasks()

        self.tasks[task_id] = (name, self.factory(task_id, event))
        self.selected = task_id

    def publish_tasks(self):
        self.emit(
            "monitor_tasks",
            (
                self.selected,
                [
                    (
                        key,
                        f"{name} · {'运行' if app.active else '停止'} · "
                        f"{app.source.title if app.source else '未选来源'}",
                    )
                    for key, (name, app) in self.tasks.items()
                ],
            ),
        )

    async def add(self):
        self._add()
        await self.select_task(self.selected)

    async def remove(self, task_id):
        if task_id not in self.tasks:
            return
        if len(self.tasks) == 1:
            raise ValueError("请至少保留一个监控任务")
        await self.tasks[task_id][1].shutdown()
        del self.tasks[task_id]
        await self.select_task(next(iter(self.tasks)))

    async def select_task(self, task_id):
        if task_id not in self.tasks:
            return
        self.selected = task_id
        app = self.current
        self.emit(
            "monitor_selected",
            (app.roi, app.image_roi, app.keywords if app.active else True, app.flash_enabled, app.source),
        )
        if app.last_preview:
            self.emit("frame", app.last_preview)
        if app.last_result:
            self.emit("ocr", app.last_result)
        self.emit("monitor_status", "运行" if app.active else "停止")
        self.emit("capture_status", "采集已就绪" if app.source else "请选择采集源")
        self.publish_tasks()

    async def reload(self):
        for _, app in self.tasks.values():
            await app.reload()
        self.publish_tasks()

    async def stop_all(self):
        for _, app in list(self.tasks.values()):
            await app.stop()

    async def pause_keywords(self):
        for _, app in list(self.tasks.values()):
            await app.pause_keywords()

    async def save_rule(self, rule):
        await self.pause_keywords()
        await self.current.save_rule(rule)
        await self.reload()

    async def delete_rule(self, rule_id):
        await self.pause_keywords()
        await self.current.delete_rule(rule_id)
        await self.reload()

    async def save_policy(self, policy):
        await self.pause_keywords()
        await self.current.save_policy(policy)
        await self.reload()

    def disconnected(self):
        for _, app in self.tasks.values():
            app.triggers.reset_continuity()
            app.policy_epoch += 1

    async def shutdown(self):
        for _, app in list(self.tasks.values()):
            await app.shutdown()
