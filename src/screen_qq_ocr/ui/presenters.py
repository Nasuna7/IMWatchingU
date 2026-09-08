import asyncio
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from screen_qq_ocr.ui.widgets.controls import ComboBox as QComboBox
from screen_qq_ocr.ui.widgets.controls import Dialog as QDialog
from screen_qq_ocr.ui.widgets.controls import FileDialog as QFileDialog
from screen_qq_ocr.ui.widgets.controls import MessageBox


class Presenter(QObject):
    def __init__(
        self, window, app, loop, bridge, list_sources, files, audio, management, credentials, qq_service
    ):
        super().__init__(window)
        self.window, self.app, self.loop = window, app, loop
        self.list_sources, self.files, self.audio, self.management = list_sources, files, audio, management
        self.preview_task = None
        self.credentials = credentials
        self.qq_service = qq_service
        self.login_poll = None
        self.qr_refreshing = False
        self.shell_task = None
        self.stop_shell_task = None
        self.auto_onebot = None
        self.auto_napcat_folder = None
        self._roi_locks = {}
        from screen_qq_ocr.infrastructure.napcat.shell import NapCatShell

        self.shell = NapCatShell()
        bridge.event.connect(self.on_event)
        self.emit = bridge.publish
        monitor = window.monitor
        self.selected_source = None
        monitor.sources.addItem("点击刷新获取来源", None)
        monitor.sources.currentIndexChanged.connect(
            lambda _: setattr(self, "selected_source", monitor.sources.currentData())
        )
        monitor.refresh.clicked.connect(lambda: self.run(self.refresh_sources()))
        monitor.refresh_preview.clicked.connect(lambda: self.run(app.current.refresh_preview(), "画面已刷新"))
        monitor.select.clicked.connect(
            lambda: self.run(app.current.select_source(monitor.sources.currentData()), "采集来源已更新")
        )
        monitor.pick_roi.clicked.connect(lambda: self.pick_roi("monitor"))
        monitor.pick_image_roi.clicked.connect(lambda: self.pick_roi("image"))
        monitor.clear_roi.clicked.connect(
            lambda: self.run(app.current.set_roi((0, 0, 1, 1)), "监控区域已重置")
        )
        monitor.clear_image_roi.clicked.connect(
            lambda: self.run(app.current.set_image_roi((0, 0, 1, 1)), "截图区域已重置")
        )
        monitor.preview.roi_selected.connect(
            lambda roi: self.run(self.roi(roi, app.current, monitor.preview.pending_revision))
        )
        monitor.add_task.clicked.connect(lambda: self.run(app.add(), "任务已新增"))
        monitor.remove_task.clicked.connect(
            lambda: self.run(app.remove(monitor.tasks.currentData()), "任务已删除")
        )
        monitor.tasks.currentIndexChanged.connect(
            lambda _: self.run(app.select_task(monitor.tasks.currentData()))
        )
        monitor.stop_all.clicked.connect(lambda: self.run(app.stop_all(), "全部任务已停止"))
        for option in (monitor.keywords, monitor.flash):
            option.toggled.connect(self.save_monitor_options)
        monitor.start.clicked.connect(
            lambda: self.run(self.start_monitor(monitor.keywords.isChecked(), monitor.flash.isChecked()))
        )
        monitor.stop.clicked.connect(lambda: self.run(app.stop(), "监控已停止"))
        window.stop_requested.connect(lambda: self.run(app.stop_all()))
        monitor.once.clicked.connect(lambda: self.run(app.recognize_once()))
        monitor.cancel.clicked.connect(lambda: self.run(self.cancel(), "待发送任务已取消"))
        window.keywords.save.connect(lambda rule: self.run(self.save_rule(rule)))
        window.keywords.delete.connect(lambda rule_id: self.run(app.delete_rule(rule_id), "关键词已删除"))
        window.keywords.error.connect(lambda message: self.on_event("error", message))
        window.keywords.import_clicked.connect(self.import_file)
        window.keywords.export_clicked.connect(self.export_file)
        window.send.apply.clicked.connect(self.save_policy)
        window.send.preview.clicked.connect(lambda: self.run(self.preview(window.send.rule.currentData())))
        window.send.sample_preview.clicked.connect(
            lambda: self.run(self.preview(window.send.rule.currentData(), window.send.sample.toPlainText()))
        )
        window.send.test.clicked.connect(self.test_send)
        window.send.rule.currentIndexChanged.connect(self.invalidate_preview)
        window.qq.connect.clicked.connect(
            lambda: self.run(self.connect_qq(window.qq.url.text(), window.qq.token.text()))
        )
        window.qq.disconnect.clicked.connect(lambda: self.run(self.disconnect()))
        window.qq.login.clicked.connect(lambda: self.shell_action(True))
        window.qq.refresh_qr.clicked.connect(lambda: self.run(self.refresh_qr()))
        window.qq.browse_launcher.clicked.connect(self.choose_launcher)
        window.qq.browse_config.clicked.connect(self.choose_config)
        window.qq.config_dir.editingFinished.connect(self.refresh_onebot_configs)
        window.qq.start_shell.clicked.connect(lambda: self.shell_action(True))
        window.qq.read_tokens.clicked.connect(lambda: self.shell_action(False))
        window.qq.stop_shell.clicked.connect(self.stop_shell_action)
        saved = app.settings.values.get("napcat", {})
        window.qq.launcher.setText(saved.get("launcher", ""))
        window.qq.config_dir.setText(saved.get("config_dir", ""))
        self.refresh_onebot_configs()
        window.qq.onebot_config.setCurrentText(saved.get("onebot_config", "onebot11.json"))
        window.settings_page.save.clicked.connect(
            lambda: self.run(self.save_settings(window.settings_page.value()))
        )
        window.settings_page.audition.clicked.connect(
            lambda: audio.play(window.settings_page.sound.currentText())
        )
        self.run(self.initialize())

    def run(self, coroutine, success=None):
        async def guarded():
            try:
                result = await coroutine
                if success:
                    self.emit("toast", success)
                return result
            except Exception as error:
                self.emit("error", str(error))

        return self.loop.submit(guarded())

    def save_monitor_options(self):
        monitor = self.window.monitor
        self.run(
            self.app.set_options(
                monitor.tasks.currentData(), monitor.keywords.isChecked(), monitor.flash.isChecked()
            ),
            "监控选项已保存，下次启动生效",
        )

    async def save_rule(self, rule):
        await self.app.save_rule(rule)
        self.emit("rule_saved", rule)
        self.emit("toast", "关键词已应用")

    async def start_monitor(self, keywords, flash):
        try:
            await self.app.start(keywords, flash)
            self.emit("toast", "监控已启动")
        except ValueError as error:
            message = str(error)
            if keywords and Presenter._is_qq_start_block(message):
                self.emit("start_blocked", Presenter._qq_start_block_message(message))
                return
            raise

    @staticmethod
    def _is_qq_start_block(message):
        return any(fragment in message for fragment in ("QQ 消息通道", "发送对象", "尚未核验"))

    @staticmethod
    def _qq_start_block_message(message):
        return (
            "QQ 尚未登录或消息通道未连接，无法开始关键词监控。\n"
            "请先在 QQ 连接页启动 NapCat、完成扫码登录，并确认发送对象后再开始监控。\n\n"
            f"详情：{message}"
        )

    async def initialize(self):
        await self.app.reload()
        await self.refresh_sources()
        self.emit(
            "credentials",
            (
                await asyncio.to_thread(self.credentials.read, "onebot"),
                await asyncio.to_thread(self.credentials.read, "management"),
            ),
        )
        records = await asyncio.to_thread(self.app.store.records)
        for row in reversed(records):
            self.emit("record", f"{row[0]} · {row[2]} · {row[1]} · {'测试' if row[5] else '自动'}")

    async def refresh_sources(self):
        sources = await asyncio.to_thread(self.list_sources)
        self.emit("sources", sources)
        await self.app.restore_sources(sources)

    async def select(self):
        # Snapshot UI selection before scheduling is preferable; this coroutine only consumes stored data.
        source = self.selected_source
        if source:
            await self.app.select_source(source)

    async def clear_roi(self):
        if self.app.source:
            await self.app.select_source(self.app.source)

    async def roi(self, coordinates, app, revision):
        from screen_qq_ocr.infrastructure.capture.coordinates import normalize_roi

        # Serialize changes per task: overlapping stop/start sequences lose running state.
        lock = self._roi_locks.setdefault(app, asyncio.Lock())
        async with lock:
            try:
                frame = app.last_preview
                if not frame:
                    raise ValueError("请先选择采集源")
                x1, y1, x2, y2 = coordinates
                relative = normalize_roi(
                    x1 * frame.width,
                    y1 * frame.height,
                    x2 * frame.width,
                    y2 * frame.height,
                    frame.width,
                    frame.height,
                )
                await app.set_roi(relative)
            finally:
                # Report actual backend state even when capture/restart fails after changing ROI.
                self.emit("roi_result", (revision, tuple(app.roi)))

    def pick_roi(self, kind):
        from screen_qq_ocr.ui.widgets.preview import RoiPickerDialog

        app = self.app.current
        frame = app.last_preview
        if not frame:
            self.on_event("error", "请先选择采集来源并获取一帧画面")
            return
        title = "选择监控识别区域" if kind == "monitor" else "选择发送截图区域"
        selected = RoiPickerDialog.pick(
            self.window,
            frame,
            app.roi if kind == "monitor" else app.image_roi,
            app.image_roi if kind == "monitor" else app.roi,
            title,
        )
        if selected is None:
            return
        if kind == "monitor":
            self.run(app.set_roi(selected), "监控区域已应用")
        else:
            self.window.monitor.preview.set_image_roi(selected)
            self.run(app.set_image_roi(selected), "截图区域已应用")

    async def cancel(self):
        self.app.queue.cancel()

    async def connect_qq(self, url, token):
        await self.app.stop_all()
        info, targets = await self.qq_service.connect(url, token)
        await asyncio.to_thread(self.app.store.select_account, str(info["user_id"]))
        await self.app.reload()
        await asyncio.to_thread(self.credentials.save, "onebot", token)
        self.emit("account", info)
        self.emit("targets", targets)
        self.emit("qq_status", "QQ：可发送")
        self.emit("toast", "QQ登录成功")
        return info, targets

    async def disconnect(self):
        await self.app.pause_keywords()
        await self.qq_service.disconnect()
        await asyncio.to_thread(self.app.store.select_account, "")
        self.emit("account_cleared", None)
        await self.app.reload()
        self.emit("qq_status", "QQ：离线")
        self.emit("toast", "QQ已断开")

    async def login(self, url, token):
        if self.login_poll:
            self.login_poll.cancel()
            await asyncio.gather(self.login_poll, return_exceptions=True)
        await self.management.connect(url, token)
        await asyncio.to_thread(self.credentials.save, "management", token)

        async def poll():
            while True:
                try:
                    state = await self.management.login_state()
                    if not self.qr_refreshing:
                        self.emit("login", state)
                    if state.get("isLogin") and self.auto_onebot:
                        connection = self.auto_onebot
                        self.auto_onebot = None
                        try:
                            info, _ = await self.connect_qq(connection.onebot_url, connection.onebot_token)
                            await self.save_logged_account_config(info.get("user_id"))
                            self.emit("shell_status", "NapCat 已登录，消息通道已核验")
                        except Exception:
                            self.emit(
                                "error", "NapCat 已登录，但消息通道未连接；请检查所选账号配置并重新连接"
                            )
                except Exception as error:
                    self.emit("error", str(error))
                    return
                await asyncio.sleep(3)

        self.login_poll = asyncio.create_task(poll())

    async def refresh_qr(self):
        if not self.management.client:
            self.shell_action(True)
            return
        if self.qr_refreshing:
            return
        self.qr_refreshing = True
        self.emit("login", {"refreshing": True})
        try:
            self.emit("login", await self.management.refresh_qr())
        except Exception:
            self.emit("login", {"loginError": "二维码刷新失败，请检查管理连接后重试。"})
            raise
        finally:
            self.qr_refreshing = False

    def save_policy(self):
        try:
            policy = self.window.send.editor.value()
            self.invalidate_preview()
            self.run(self.app.save_policy(policy), "发送配置已应用")
        except ValueError as error:
            self.on_event("error", str(error))

    async def preview(self, rule_id, sample=None):
        task = await self.app.preview(rule_id, sample)
        self.emit("preview_task", task)

    def invalidate_preview(self, *_):
        self.preview_task = None
        self.window.send.test.setEnabled(False)
        self.window.send.result.clear()

    def test_send(self):
        if self.preview_task:
            self.run(self.app.test_send(self.preview_task))
            self.invalidate_preview()

    async def save_settings(self, values):
        await self.app.stop_all()
        values["napcat"] = self.app.settings.values["napcat"]
        await asyncio.to_thread(self.app.settings.save, values)
        self.emit("info", "设置已保存；请重新开始监控")

    def choose_launcher(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window, "选择 NapCat Shell 启动文件", "", "启动文件 (*.bat *.cmd *.ps1 *.exe)"
        )
        if path:
            self.window.qq.launcher.setText(path)
            parent = Path(path).parent
            for folder in (parent / "config", parent / "napcat" / "config"):
                if folder.is_dir():
                    self.window.qq.config_dir.setText(str(folder))
                    break
            self.refresh_onebot_configs()

    def choose_config(self):
        folder = QFileDialog.getExistingDirectory(self.window, "选择包含 webui.json 的 NapCat 配置目录")
        if folder:
            self.window.qq.config_dir.setText(folder)
            self.refresh_onebot_configs()

    def refresh_onebot_configs(self):
        page = self.window.qq
        previous = page.onebot_config.currentText()
        folder = Path(page.config_dir.text())
        names = sorted(p.name for p in folder.glob("onebot11*.json")) if folder.is_dir() else []
        page.onebot_config.clear()
        page.onebot_config.addItems(names or ["onebot11.json"])
        if previous in names:
            page.onebot_config.setCurrentText(previous)

    def shell_action(self, start):
        page = self.window.qq
        if self.stop_shell_task and not self.stop_shell_task.done():
            return
        if self.shell_task and not self.shell_task.done():
            return
        if not page.config_dir.text().strip():
            self.on_event("error", "请选择 NapCat 配置目录")
            return
        page.start_shell.setEnabled(False)
        page.read_tokens.setEnabled(False)
        self.shell_task = self.run(
            self.configure_shell(
                page.launcher.text(), page.config_dir.text(), page.onebot_config.currentText(), start
            )
        )

    def stop_shell_action(self):
        if self.stop_shell_task and not self.stop_shell_task.done():
            return
        self.stop_shell_task = self.run(self.stop_napcat())

    async def stop_napcat(self):
        from screen_qq_ocr.infrastructure.napcat.shell import NapCatShell

        if self.shell_task:
            self.shell_task.cancel()
            await asyncio.gather(asyncio.wrap_future(self.shell_task), return_exceptions=True)
        if self.login_poll:
            self.login_poll.cancel()
            await asyncio.gather(self.login_poll, return_exceptions=True)
        self.auto_onebot = None
        try:
            await self.app.stop_all()
            await self.qq_service.disconnect()
            await self.management.close()
        finally:
            owned = await asyncio.to_thread(self.shell.stop, closing=True)
            if not self.window.exiting:
                self.shell = NapCatShell()
        self.emit("qq_status", "QQ：离线")
        self.emit("login", {"isOffline": True})
        self.emit(
            "shell_status",
            "NapCat 已停止，账号连接已释放"
            if owned
            else "未发现本应用启动的 NapCat；外部实例请从其启动入口退出",
        )

    async def configure_shell(self, launcher, folder, onebot_name, start):
        import copy

        try:
            if start:
                await self.app.stop_all()
                self.emit("shell_status", "正在启动 NapCat，等待管理端就绪…")
                connection = await asyncio.to_thread(self.shell.start, launcher, folder, onebot_name)
            else:
                connection = await asyncio.to_thread(self.shell.connection, folder, onebot_name)
            self.emit("shell_connection", connection)
            values = copy.deepcopy(self.app.settings.values)
            values["napcat"] = dict(launcher=launcher, config_dir=folder, onebot_config=onebot_name)
            await asyncio.to_thread(self.app.settings.save, values)
            if not start:
                self.emit("shell_status", "地址与 token 已读取，可连接管理端或消息通道")
                return
            self.auto_onebot = connection
            self.auto_napcat_folder = folder
            for attempt in range(30):
                try:
                    await self.login(connection.management_url, connection.management_token)
                    self.emit("shell_status", "管理端已连接，请扫码登录 QQ")
                    self.window.qq.refresh_qr.setEnabled(True)
                    return
                except ValueError:
                    if attempt == 29:
                        self.auto_onebot = None
                        raise ValueError(
                            "NapCat 管理端未就绪；请检查 Shell 启动文件、配置目录和端口，再连接管理端"
                        ) from None
                    await asyncio.sleep(1)
        finally:
            self.emit("shell_idle", None)

    async def save_logged_account_config(self, user_id):
        import copy

        folder = Path(self.auto_napcat_folder or self.window.qq.config_dir.text())
        if not folder.is_dir():
            return
        preferred = folder / f"onebot11_{user_id}.json" if user_id else None
        config = preferred if preferred and preferred.is_file() else None
        if config is None:
            configs = sorted(
                folder.glob("onebot11_*.json"), key=lambda item: item.stat().st_mtime, reverse=True
            )
            config = configs[0] if configs else None
        if config is None:
            return
        self.refresh_onebot_configs()
        self.window.qq.onebot_config.setCurrentText(config.name)
        values = copy.deepcopy(self.app.settings.values)
        values["napcat"] = dict(
            launcher=self.window.qq.launcher.text(), config_dir=str(folder), onebot_config=config.name
        )
        await asyncio.to_thread(self.app.settings.save, values)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self.window, "导入关键词", "", "关键词 (*.txt *.json)")
        if path:
            self.run(self.read_import(path))

    async def read_import(self, path):
        text = await asyncio.to_thread(Path(path).read_text, encoding="utf-8-sig")
        parser = self.files.parse_json if Path(path).suffix.lower() == ".json" else self.files.parse_txt
        preview = await asyncio.to_thread(parser, text)
        self.emit("import_preview", preview)

    def show_import(self, preview):
        dialog = QDialog(self.window)
        dialog.setWindowTitle("导入预览")
        dialog.resize(640, 500)
        layout = QVBoxLayout(dialog)
        summary = QPlainTextEdit()
        summary.setReadOnly(True)
        lines = [
            f"有效 {len(preview.rules)} 条；重复 {len(preview.duplicates)} 条；无效 {len(preview.errors)} 条"
        ]
        lines += [f"{r.keyword} | {r.min_count} | {r.send_overrides.body or ''}" for r in preview.rules]
        lines += preview.duplicates + preview.errors
        if preview.default_policy:
            lines += [
                "JSON 含默认策略快照；保留当前默认值可能改变最终行为，目标需重新核验。",
                str(preview.default_policy),
            ]
        summary.setPlainText("\n".join(lines))
        layout.addWidget(summary)
        mode = QComboBox()
        mode.addItems(["合并（保留已有规则）", "合并并覆盖同名规则", "替换（自动备份数据库）"])
        layout.addWidget(mode)
        valid_only = QCheckBox("存在无效条目时，仅导入上述有效条目")
        layout.addWidget(valid_only)
        use_default = QCheckBox("同时应用文件中的默认策略快照")
        use_default.setEnabled(preview.default_policy is not None)
        layout.addWidget(use_default)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.run(
                self.apply_import(
                    preview, mode.currentIndex(), valid_only.isChecked(), use_default.isChecked()
                )
            )

    async def apply_import(self, preview, mode, valid, use_default):
        await self.app.pause_keywords()
        await asyncio.to_thread(
            self.app.store.import_rules,
            preview,
            "replace" if mode == 2 else "merge",
            mode == 1,
            valid,
            use_default,
        )
        await self.app.reload()
        self.emit("info", "导入已保存；源文件未修改")

    def export_file(self):
        path, chosen = QFileDialog.getSaveFileName(
            self.window,
            "导出关键词（TXT 不含发送策略；完整保存请选择 JSON）",
            "keywords.json",
            "完整规则 (*.json);;关键词文本 (*.txt)",
        )
        if path:
            self.run(self.write_export(path))

    async def write_export(self, path):
        rules = await asyncio.to_thread(self.app.store.list_rules)
        default = await asyncio.to_thread(self.app.store.default_policy)
        text = (
            self.files.export_txt(rules)
            if Path(path).suffix.lower() == ".txt"
            else self.files.export_json(rules, default)
        )
        await asyncio.to_thread(Path(path).write_text, text, encoding="utf-8")
        self.emit("info", "规则已导出；TXT 仅保留关键词、次数与固定正文")

    def on_event(self, kind, value):
        w = self.window
        if kind in ("toast", "info", "error", "start_blocked") and hasattr(w, "toasts"):
            message = str(value).splitlines()[0]
            w.toasts.show(message[:80], error=kind in ("error", "start_blocked"))
        if kind in w.status_labels:
            w.status_labels[kind].setText(value)
        elif kind == "credentials":
            w.qq.token.setText(value[0])
            w.qq.management_token.setText(value[1])
        elif kind == "shell_connection":
            w.qq.management_url.setText(value.management_url)
            w.qq.management_token.setText(value.management_token)
            w.qq.url.setText(value.onebot_url)
            w.qq.token.setText(value.onebot_token)
        elif kind == "shell_status":
            w.qq.shell_status.setText(value)
        elif kind == "shell_idle":
            w.qq.start_shell.setEnabled(True)
            w.qq.read_tokens.setEnabled(True)
        elif kind == "start_blocked":
            w.records.appendPlainText(f"error · {value}")
            MessageBox.critical(w, "无法开始监控", value)
        elif kind in ("error", "info"):
            w.records.appendPlainText(f"{kind} · {value}")
        elif kind == "sources":
            w.monitor.sources.clear()
            if not value:
                w.monitor.sources.addItem("未找到可用来源，请稍后刷新", None)
            for source in value:
                w.monitor.sources.addItem(source.title, source)
            self.selected_source = w.monitor.sources.currentData()
        elif kind == "frame":
            if w.isVisible() and not w.isMinimized() and w.stack.currentIndex() == 0:
                w.monitor.preview.set_frame(value)
        elif kind == "roi_result":
            w.monitor.preview.finish_roi(*value)
        elif kind == "roi":
            if w.monitor.preview.pending_revision is None and not w.monitor.preview.drag:
                w.monitor.preview.set_roi(value)
        elif kind == "image_roi":
            w.monitor.preview.set_image_roi(value)
        elif kind == "monitor_tasks":
            selected, tasks = value
            w.monitor.tasks.blockSignals(True)
            w.monitor.tasks.clear()
            for task_id, title in tasks:
                w.monitor.tasks.addItem(title, task_id)
            w.monitor.tasks.setCurrentIndex(w.monitor.tasks.findData(selected))
            w.monitor.tasks.blockSignals(False)
        elif kind == "monitor_selected":
            self.invalidate_preview()
            roi, image_roi, keywords, flash, source = value
            w.monitor.preview.image = None
            w.monitor.preview.drag = None
            w.monitor.preview.set_roi(roi)
            w.monitor.preview.set_image_roi(image_roi)
            w.monitor.ocr.clear()
            w.monitor.meta.setText("尚无识别结果")
            w.monitor.flash_state.setText("色块：等待采样")
            for option, checked in ((w.monitor.keywords, keywords), (w.monitor.flash, flash)):
                option.blockSignals(True)
                option.setChecked(checked)
                option.blockSignals(False)
            if source:
                w.monitor.sources.setCurrentIndex(w.monitor.sources.findData(source))
        elif kind == "rules":
            w.keywords.set_rules(value)
            selected = w.send.rule.currentData()
            w.send.rule.clear()
            for rule in value:
                w.send.rule.addItem(rule.keyword, rule.id)
            w.send.rule.setCurrentIndex(max(0, w.send.rule.findData(selected)))
        elif kind == "rule_saved":
            w.keywords.saved(value)
        elif kind == "policy":
            w.send.editor.load(value)
            self.invalidate_preview()
        elif kind == "ocr":
            w.monitor.ocr.setPlainText(value.text)
            w.monitor.meta.setText(
                f"{value.engine} · {value.elapsed_ms:.0f} ms · {len([x for x in value.text.splitlines() if x.strip()])} 行 · {len(''.join(value.text.split()))} 字符\n采集：{value.frame.capture_time:%H:%M:%S}"
            )
        elif kind == "flash":
            w.monitor.flash_state.setText(
                f"主色：{value[0]} · 连续变化 {value[1]}/4" + (" · 报警" if value[2] else "")
            )
        elif kind == "sound":
            self.audio.play(value)
        elif kind == "sound_stop":
            self.audio.stop()
        elif kind == "send":
            task, state, receipts = value
            targets = task.policy.recipients
            target = targets[0] if targets else None
            suffix = f"{target.display_name} ({target.id})" if target else "尚未选择对象"
            if len(targets) > 1:
                suffix += f" 等 {len(targets)} 个对象"
            w.monitor.pending.setText(f"{state} · {suffix} · {task.task_id[:8]}")
            w.records.appendPlainText(
                f"发送 · {state} · {task.task_id} · {'测试' if task.is_test else '自动'}"
            )
        elif kind == "record":
            w.records.appendPlainText(value)
        elif kind == "account":
            w.qq.account.setText(f"{value.get('nickname', '')} · QQ {value['user_id']}")
            if w.keywords.policy.account_id != str(value["user_id"]):
                w.keywords.editor.reject()
                w.keywords.editing = None
            for editor in (w.send.editor, w.keywords.policy):
                editor.set_account(str(value["user_id"]))
        elif kind == "account_cleared":
            w.keywords.editor.reject()
            w.keywords.editing = None
            for editor in (w.send.editor, w.keywords.policy):
                editor.set_account("")
        elif kind == "targets":
            w.send.editor.set_targets(value)
            w.keywords.policy.set_targets(value)
        elif kind == "preview":
            w.send.result.setPlainText("\n".join(f"{key}：{item}" for key, item in value.items()))
        elif kind == "preview_task":
            self.preview_task = value
            targets = value.policy.recipients
            target = targets[0] if targets else None
            w.send.test.setText("向下列对象测试发送")
            w.send.test_target.setText(
                f"测试发送到 {target.display_name}（{target.type} {target.id}）等 {len(targets)} 个对象"
                if target
                else "尚未选择对象"
            )
            w.send.test.setEnabled(bool(targets))
        elif kind == "import_preview":
            self.show_import(value)
        elif kind == "login":
            self.show_login(value)

    def show_login(self, data):
        w = self.window.qq
        w.refresh_qr.setEnabled(not data.get("refreshing", False))
        if data.get("refreshing"):
            w.qr.clear()
            w.login_status.setText("正在请求新的二维码，请稍候…")
        elif data.get("isLogin"):
            w.qr.clear()
            w.login_status.setText("已登录；请连接消息通道核验账号")
        elif data.get("isOffline"):
            w.qr.clear()
            w.login_status.setText("QQ 已离线；若无法重新扫码，请停止并重新启动本应用的 NapCat。")
        elif data.get("loginError"):
            w.qr.clear()
            error = str(data["loginError"])
            if "已登录" in error and "重复登录" in error:
                advice = "请先退出使用同一账号的其他 QQ / NapCat 登录会话，再刷新二维码。"
            elif "过期" in error:
                advice = "请刷新二维码后重新扫码。"
            else:
                advice = "请查看手机 QQ 的验证提示及 NapCat 运行状态。"
            w.login_status.setText(f"NapCat 登录提示：{error}\n{advice}")
        else:
            w.login_status.setText("等待登录，请使用手机 QQ 扫码")
            url = data.get("qrcodeurl", "")
            if not url:
                w.qr.clear()
                w.login_status.setText("正在等待 NapCat 生成二维码，可点击刷新重试。")
            if url:
                try:
                    import qrcode
                    from PIL.ImageQt import ImageQt
                    from PySide6.QtGui import QPixmap

                    qr = qrcode.QRCode(box_size=5, border=4)
                    qr.add_data(url)
                    qr.make(fit=True)
                    image = qr.make_image().convert("RGB")
                    w.qr.setPixmap(QPixmap.fromImage(ImageQt(image)))
                except ImportError:
                    w.qr.setText("缺少二维码绘制组件，请安装项目依赖")
