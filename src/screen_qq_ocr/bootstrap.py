import argparse
import asyncio
import hashlib
import multiprocessing
import os
import sys
from pathlib import Path

APP_NAME = "IMWatchingU❤"
APP_ID = "IMWatchingU"


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--self-check", type=Path, help="Write a synthetic OCR and dependency probe report")
    parser.add_argument(
        "--smoke-test", action="store_true", help="Open UI briefly, without capture or network"
    )
    args = parser.parse_args()
    if args.self_check:
        from screen_qq_ocr.runtime.self_check import run

        if not asyncio.run(run(args.self_check)):
            raise SystemExit(1)
        return
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    from PySide6.QtCore import QTimer
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from screen_qq_ocr.application.monitor_tasks import MonitorTasks, TaskQueue
    from screen_qq_ocr.application.monitoring import Monitoring
    from screen_qq_ocr.application.qq_service import QQService
    from screen_qq_ocr.application.sending import SendQueue
    from screen_qq_ocr.infrastructure.logging import configure_logging
    from screen_qq_ocr.infrastructure.napcat.management import Management
    from screen_qq_ocr.infrastructure.napcat.onebot import OneBot
    from screen_qq_ocr.infrastructure.persistence import keyword_files
    from screen_qq_ocr.infrastructure.persistence.database import Database
    from screen_qq_ocr.infrastructure.persistence.settings import Settings
    from screen_qq_ocr.infrastructure.platform.credentials import Credentials
    from screen_qq_ocr.infrastructure.platform.session import SessionFilter
    from screen_qq_ocr.runtime.async_loop import AsyncLoop
    from screen_qq_ocr.runtime.qt_bridge import EventBridge
    from screen_qq_ocr.runtime.workers import OcrWorker
    from screen_qq_ocr.ui.appearance import install
    from screen_qq_ocr.ui.audio import Audio
    from screen_qq_ocr.ui.main_window import MainWindow
    from screen_qq_ocr.ui.presenters import Presenter
    from screen_qq_ocr.ui.widgets.controls import MessageBox as QMessageBox

    data_dir = (args.data_dir or Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_ID).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    gui = QApplication(sys.argv[:1])
    install(gui)
    gui.setApplicationName(APP_NAME)
    gui.setApplicationDisplayName(APP_NAME)
    gui.setQuitOnLastWindowClosed(False)
    server_name = APP_ID + "-" + hashlib.sha256(str(data_dir).casefold().encode()).hexdigest()[:20]
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(400):
        socket.write(b"activate")
        socket.waitForBytesWritten(400)
        return
    server = QLocalServer()
    if not server.listen(server_name):
        QMessageBox.critical(None, "无法启动", "同一数据目录已有实例，或本地实例锁不可用。")
        return
    try:
        settings = Settings(data_dir / "settings.json")
        database = Database(data_dir / "app.db")
        database.select_account("")
    except Exception as error:
        QMessageBox.critical(None, "数据加载失败", str(error))
        return
    install(gui, settings.values["appearance"].get("theme", "light"))
    logger = configure_logging(data_dir / "logs")
    bridge = EventBridge()
    loop = AsyncLoop()
    window = MainWindow(settings)
    audio = Audio(data_dir / "cache")
    management = Management()

    def disconnected():
        queue.cancel()
        monitor.disconnected()
        bridge.publish("qq_status", "QQ：离线，通知暂停")

    messaging = OneBot(disconnected)

    def sending_event(task, state, receipts):
        bridge.publish("send", (task, state, receipts))
        logger.info("send task=%s rule=%s state=%s test=%s", task.task_id, task.rule_id, state, task.is_test)
        if state not in ("待发送", "倒计时", "发送中"):
            try:
                database.record(task, state, receipts)
            except Exception:
                bridge.publish("error", "发送回执保存失败，请检查数据目录；不会重发消息")

    def encode_png_lazy(frame):
        from screen_qq_ocr.infrastructure.ocr.preprocessing import encode_png

        return encode_png(frame)

    queue = SendQueue(messaging, encode_png_lazy, sending_event)

    def analyze_color(frame):
        from screen_qq_ocr.domain.flash import dominant
        from screen_qq_ocr.infrastructure.ocr.preprocessing import frame_image

        image = frame_image(frame).resize((max(4, frame.width // 4), max(4, frame.height // 4)))
        return dominant(list(image.getdata())[::2])

    class LazyCapture:
        def __init__(self):
            self.inner = None

        def capture(self):
            if self.inner is None:
                from screen_qq_ocr.infrastructure.capture.windows_capture import Capture

                self.inner = Capture()
            return self.inner

        def open(self, *args):
            return self.capture().open(*args)

        def grab(self, *args):
            return self.capture().grab(*args)

        def close(self):
            if self.inner is not None:
                return self.inner.close()

    def list_sources_lazy():
        from screen_qq_ocr.infrastructure.capture.windows_capture import list_sources

        return list_sources()

    def load_monitor_tasks():
        return settings.values.get("capture", {}).get("tasks", [])

    def save_monitor_tasks(configs):
        import copy

        values = copy.deepcopy(settings.values)
        values.setdefault("capture", {})["tasks"] = configs
        settings.save(values)

    monitor = MonitorTasks(
        lambda task_id, emit: Monitoring(
            LazyCapture(),
            OcrWorker(),
            TaskQueue(queue, task_id),
            messaging,
            database,
            settings,
            analyze_color,
            emit,
        ),
        bridge.publish,
        load_monitor_tasks,
        save_monitor_tasks,
    )
    credentials = Credentials(server_name)
    qq_service = QQService(messaging, bridge.publish)
    presenter = Presenter(
        window,
        monitor,
        loop,
        bridge,
        list_sources_lazy,
        keyword_files,
        audio,
        management,
        credentials,
        qq_service,
    )
    queue_future = loop.submit(queue.run())

    def activate():
        client = server.nextPendingConnection()
        if client:
            client.deleteLater()
        window.restore()

    server.newConnection.connect(activate)
    session_filter = SessionFilter(int(window.winId()), lambda: presenter.run(monitor.stop_all()))
    gui.installNativeEventFilter(session_filter)

    async def shutdown_connections():
        if presenter.stop_shell_task:
            await asyncio.gather(asyncio.wrap_future(presenter.stop_shell_task), return_exceptions=True)
        if presenter.shell_task:
            presenter.shell_task.cancel()
            await asyncio.gather(asyncio.wrap_future(presenter.shell_task), return_exceptions=True)
        await monitor.shutdown()
        if presenter.login_poll:
            presenter.login_poll.cancel()
            await asyncio.gather(presenter.login_poll, return_exceptions=True)
        deadline = asyncio.get_running_loop().time() + 10
        while queue.current and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        queue.running = False
        queue_future.cancel()
        await qq_service.disconnect()
        await management.close()

    async def shutdown():
        try:
            await shutdown_connections()
        finally:
            await asyncio.to_thread(presenter.shell.stop, closing=True)

    def quit_app():
        audio.stop()
        future = loop.submit(shutdown())
        timer = QTimer(window)

        def check():
            if future.done():
                timer.stop()
                try:
                    future.result()
                except Exception:
                    logger.exception("Application shutdown failed")
                session_filter.close()
                window.tray.hide()
                loop.stop()
                gui.exit(0)

        timer.timeout.connect(check)
        timer.start(50)

    window.quit_requested.connect(quit_app)
    window.show()
    if args.smoke_test:
        QTimer.singleShot(1500, window.request_quit)
    try:
        gui.exec()
    finally:
        presenter.shell.stop(closing=True)


if __name__ == "__main__":
    main()
