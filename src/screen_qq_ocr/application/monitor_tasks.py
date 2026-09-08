from dataclasses import replace
from uuid import uuid4


def _source_identity(source):
    return (getattr(source, "stable_id", "") or getattr(source, "id", "")) if source else ""


def _source_ref(source):
    if not source:
        return None
    metadata = tuple(getattr(source, "metadata", ()))
    return {
        "id": getattr(source, "id", ""),
        "stable_id": _source_identity(source),
        "title": getattr(source, "title", ""),
        "kind": getattr(source, "kind", ""),
        "process_name": metadata[3] if len(metadata) > 3 else "",
    }


def _match_source(saved, sources):
    if not saved:
        return None
    stable_id = saved.get("stable_id") or saved.get("id") or ""
    title = saved.get("title") or ""
    for source in sources:
        if _source_identity(source) == stable_id:
            return source
    if title:
        for source in sources:
            metadata = tuple(getattr(source, "metadata", ()))
            if getattr(source, "kind", "") == "window" and len(metadata) > 1 and metadata[1] == title:
                return source
    return None


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

    def __init__(self, factory, emit, load_configs=None, save_configs=None):
        self.factory, self.emit = factory, emit
        self.load_configs = load_configs or (lambda: [])
        self.save_configs = save_configs or (lambda configs: None)
        self.tasks = {}
        self.selected = None
        self.serial = 0
        self.loading = True
        restored = list(self.load_configs() or [])
        if restored:
            for config in restored:
                self._add(config)
        else:
            self._add()
        self.loading = False
        self.persist()

    @property
    def current(self):
        return self.tasks[self.selected][1]

    def __getattr__(self, name):
        return getattr(self.current, name)

    def _add(self, config=None):
        config = config or {}
        task_id = config.get("id") or str(uuid4())
        self.serial += 1
        name = config.get("name") or f"任务 {self.serial}"

        def event(kind, value):
            if kind in ("error", "info"):
                self.emit(kind, f"{name}：{value}")
            elif kind == "sound_stop":
                if not any(app.active and app.flash_enabled for _, app in self.tasks.values()):
                    self.emit(kind, value)
            elif kind in ("rules", "policy", "sound") or self.selected == task_id:
                self.emit(kind, value)
            if kind in ("monitor_status", "capture_status", "roi", "image_roi"):
                self.publish_tasks()
                self.persist()

        app = self.factory(task_id, event)
        app.roi = tuple(config.get("roi") or (0, 0, 1, 1))
        app.image_roi = tuple(config.get("image_roi") or (0, 0, 1, 1))
        app.keywords = bool(config.get("keywords", True))
        app.flash_enabled = bool(config.get("flash", False))
        app.configured_keywords = app.keywords
        app.configured_flash = app.flash_enabled
        app.saved_source = config.get("source")
        self.tasks[task_id] = (name, app)
        self.selected = task_id

    def configs(self):
        return [
            {
                "id": task_id,
                "name": name,
                "source": _source_ref(app.source) or getattr(app, "saved_source", None),
                "roi": list(app.roi),
                "image_roi": list(app.image_roi),
                "keywords": app.configured_keywords,
                "flash": app.configured_flash,
            }
            for task_id, (name, app) in self.tasks.items()
        ]

    def persist(self):
        if not self.loading:
            self.save_configs(self.configs())

    async def set_options(self, task_id, keywords, flash):
        if task_id not in self.tasks:
            return
        app = self.tasks[task_id][1]
        app.configured_keywords, app.configured_flash = bool(keywords), bool(flash)
        self.persist()

    def publish_tasks(self):
        self.emit(
            "monitor_tasks",
            (
                self.selected,
                [
                    (
                        key,
                        f"{name} · {'运行' if app.active else '停止'} · "
                        f"{app.source.title if app.source else self.saved_source_title(app)}",
                    )
                    for key, (name, app) in self.tasks.items()
                ],
            ),
        )

    @staticmethod
    def saved_source_title(app):
        saved = getattr(app, "saved_source", None) or {}
        return saved.get("title") or "未选择来源"

    async def add(self):
        self._add()
        await self.select_task(self.selected)
        self.persist()

    async def remove(self, task_id):
        if task_id not in self.tasks:
            return
        if len(self.tasks) == 1:
            raise ValueError("请至少保留一个监控任务")
        await self.tasks[task_id][1].shutdown()
        del self.tasks[task_id]
        await self.select_task(next(iter(self.tasks)))
        self.persist()

    async def select_task(self, task_id):
        if task_id not in self.tasks:
            return
        self.selected = task_id
        app = self.current
        self.emit(
            "monitor_selected",
            (app.roi, app.image_roi, app.configured_keywords, app.configured_flash, app.source),
        )
        if app.last_preview:
            self.emit("frame", app.last_preview)
        if app.last_result:
            self.emit("ocr", app.last_result)
        self.emit("monitor_status", "运行" if app.active else "停止")
        self.emit("capture_status", "采集已就绪" if app.source else "请选择采集源")
        self.publish_tasks()

    async def restore_sources(self, sources):
        changed = False
        for _, app in self.tasks.values():
            if app.source or not getattr(app, "saved_source", None):
                continue
            source = _match_source(app.saved_source, sources)
            if source:
                keywords, flash = app.keywords, app.flash_enabled
                await app.select_source(source, app.roi)
                app.keywords, app.flash_enabled = keywords, flash
                app.saved_source = _source_ref(source)
                changed = True
        if changed:
            await self.select_task(self.selected)
            self.persist()
        else:
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
        self.persist()
        for _, app in list(self.tasks.values()):
            await app.shutdown()
