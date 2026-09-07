import asyncio
import multiprocessing
import time


def _engine_key(options):
    return (
        options.get("engine"),
        options.get("max_edge"),
        options.get("tesseract", ""),
        options.get("preprocess", True),
    )


def _make_engine(options):
    if options["engine"] == "windows":
        from screen_qq_ocr.infrastructure.ocr.windows_ocr import WindowsOcr

        return WindowsOcr(options["max_edge"])
    from screen_qq_ocr.infrastructure.ocr.tesseract import Tesseract

    return Tesseract(options["tesseract"], options["max_edge"], options["preprocess"])


def _check_availability(options):
    if options["engine"] == "windows":
        from winrt.windows.media.ocr import OcrEngine

        if not any(
            language.language_tag == "zh-Hans-CN"
            for language in OcrEngine.available_recognizer_languages
        ):
            raise ValueError("Windows 缺少简体中文 OCR 组件，请安装语言组件或切换 Tesseract")
    else:
        import os
        import shutil
        import subprocess

        executable = options.get("tesseract") or shutil.which("tesseract")
        if not executable:
            raise ValueError("未找到 Tesseract，请在设置中选择引擎")
        response = subprocess.run(
            [executable, "--list-langs"],
            capture_output=True,
            timeout=5,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        languages = response.stdout.decode("utf-8", errors="replace")
        if response.returncode or not all(x in languages.split() for x in ("chi_sim", "eng")):
            raise ValueError("Tesseract 缺少 chi_sim 或 eng 语言模型")


def _ocr_child(connection):
    engine = None
    engine_key = None
    try:
        while True:
            try:
                payload = connection.recv()
            except EOFError:
                break
            if payload is None:
                break
            command = payload[0]
            try:
                if command == "availability":
                    _check_availability(payload[1])
                    connection.send((True, None))
                elif command == "recognize":
                    _, frame, options = payload
                    key = _engine_key(options)
                    if engine is None or key != engine_key:
                        engine = _make_engine(options)
                        engine_key = key
                    connection.send((True, engine.recognize(frame)))
                else:
                    raise ValueError(f"Unknown OCR worker command: {command}")
            except Exception as error:
                connection.send((False, str(error)))
    finally:
        connection.close()


class OcrWorker:
    """Isolate native OCR in a disposable child process."""

    def __init__(self):
        self.process = None
        self.connection = None
        self.busy = False

    async def availability(self, options):
        await self.request(("availability", options), timeout=8, timeout_message="OCR 可用性检查超时，请重试")

    async def recognize(self, frame, options):
        if self.busy:
            raise RuntimeError("OCR 已在运行")
        self.busy = True
        try:
            return await self.request(
                ("recognize", frame, options),
                timeout=25,
                timeout_message="OCR 工作进程超时或退出，请重试 OCR",
            )
        finally:
            self.busy = False

    async def request(self, payload, timeout, timeout_message):
        self.ensure_process()
        self.connection.send(payload)
        deadline = time.monotonic() + timeout
        while not self.connection.poll():
            if time.monotonic() > deadline or not self.process.is_alive():
                self.shutdown_now()
                raise ValueError(timeout_message)
            await asyncio.sleep(0.03)
        ok, value = self.connection.recv()
        if not ok:
            raise ValueError(value)
        return value

    def ensure_process(self):
        if self.process and self.process.is_alive() and self.connection:
            return
        self.shutdown_now()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(target=_ocr_child, args=(child,), daemon=True)
        process.start()
        child.close()
        self.process = process
        self.connection = parent

    def shutdown_now(self):
        connection, process = self.connection, self.process
        self.connection = None
        self.process = None
        if connection:
            try:
                if process and process.is_alive():
                    connection.send(None)
            except (BrokenPipeError, EOFError, OSError):
                pass
            connection.close()
        if process:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)

    async def shutdown(self):
        await asyncio.to_thread(self.shutdown_now)
