import json
import os
import time
from types import SimpleNamespace

import pytest

from screen_qq_ocr.infrastructure.napcat import shell as module


def test_prepare_generates_tokens_then_reads_without_replacing_them(tmp_path):
    shell = module.NapCatShell()
    first = shell.connection(tmp_path, prepare=True)
    assert first.management_token and first.onebot_token
    assert first.management_token != first.onebot_token
    assert first == shell.connection(tmp_path, prepare=True)
    assert not list(tmp_path.glob("*.bak"))
    assert first.management_token not in repr(first)


def test_prepare_without_account_config_creates_qr_login_config(tmp_path):
    folder = tmp_path / "NapCat.Shell" / "config"
    connection = module.NapCatShell().connection(folder, "onebot11.json", prepare=True)
    assert (folder / "webui.json").is_file()
    assert (folder / "onebot11.json").is_file()
    assert connection.management_url == "http://127.0.0.1:6099"
    assert connection.onebot_url == "ws://127.0.0.1:3001"


def test_existing_config_preserved_and_backup_written(tmp_path):
    web = {"token": "management-secret", "port": 6099, "theme": {"custom": True}}
    bot = {"custom": 7, "network": {"httpServers": [{"enable": True}], "websocketServers": []}}
    (tmp_path / "webui.json").write_text(json.dumps(web))
    (tmp_path / "onebot11_123.json").write_text(json.dumps(bot))
    result = module.NapCatShell().connection(tmp_path, "onebot11_123.json", prepare=True)
    updated = json.loads((tmp_path / "onebot11_123.json").read_text())
    assert updated["custom"] == 7 and updated["network"]["httpServers"] == bot["network"]["httpServers"]
    assert result.management_token == web["token"]
    backup = next(tmp_path.glob("onebot11_123.json*.bak"))
    assert json.loads(backup.read_text()) == bot


def test_invalid_bot_does_not_write_web_config(tmp_path):
    (tmp_path / "onebot11.json").write_text("invalid")
    with pytest.raises(ValueError, match="格式无效"):
        module.NapCatShell().connection(tmp_path, prepare=True)
    assert not (tmp_path / "webui.json").exists()


def test_hidden_launch_with_spaces_and_no_token_arguments(tmp_path, monkeypatch):
    launcher = tmp_path / "launch & test.cmd"
    launcher.write_text("@echo off")
    calls = []

    def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(poll=lambda: None)

    def unavailable(*args, **kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    if os.name == "nt":
        from screen_qq_ocr.infrastructure.napcat.process_job import ProcessJob

        monkeypatch.setattr(ProcessJob, "attach_and_resume", lambda self, process: None)
    monkeypatch.setattr(module.socket, "create_connection", unavailable)
    shell = module.NapCatShell()
    connection = shell.start(launcher, tmp_path / "config", "onebot11.json")
    assert len(calls) == 1
    if shell.job:
        shell.job.close()
    args, kwargs = calls[0]
    assert kwargs["env"]["IMWATCHINGU_NAPCAT_LAUNCHER"] == str(launcher)
    assert kwargs["cwd"] == tmp_path
    assert connection.onebot_token not in str(args)
    assert shell.start(launcher, tmp_path / "config", "onebot11.json") == connection
    assert len(calls) == 1


def test_existing_listener_is_attached_without_rewrite_or_spawn(tmp_path, monkeypatch):
    launcher = tmp_path / "launch.cmd"
    launcher.write_text("@echo off")
    shell = module.NapCatShell()
    connection = shell.connection(tmp_path, prepare=True)

    class Listener:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(module.socket, "create_connection", lambda *a, **kw: Listener())
    assert shell.start(launcher, tmp_path, "onebot11.json") == connection
    assert shell.process is None


@pytest.mark.skipif(os.name != "nt", reason="Windows shell quoting")
def test_actual_batch_launch_with_spaces_and_metacharacters(tmp_path, monkeypatch):
    launcher = tmp_path / "launch & fixture.cmd"
    launcher.write_text('@echo off\n> "%~dp0started.txt" echo started\n')

    def unavailable(*args, **kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(module.socket, "create_connection", unavailable)
    shell = module.NapCatShell()
    shell.start(launcher, tmp_path / "config", "onebot11.json")
    deadline = time.monotonic() + 5
    while shell.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        assert shell.process.poll() == 0
        assert (tmp_path / "started.txt").read_text().strip() == "started"
    finally:
        if shell.process.poll() is None:
            shell.process.terminate()
        shell.process.wait(timeout=2)
        shell.stop()


def test_closed_shell_rejects_late_start(tmp_path):
    shell = module.NapCatShell()
    assert shell.stop(closing=True) is False
    with pytest.raises(ValueError, match="退出"):
        shell.start(tmp_path / "unused.cmd", tmp_path, "onebot11.json")


def test_shutdown_waits_for_inflight_launch_and_prevents_restart(tmp_path, monkeypatch):
    import concurrent.futures
    import threading

    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    shell = module.NapCatShell()

    def launch(*args):
        entered.set()
        assert release.wait(5)
        shell.process = SimpleNamespace(poll=lambda: None, terminate=stopped.set, wait=lambda timeout: 0)

    monkeypatch.setattr(shell, "_start", launch)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        launching = pool.submit(shell.start, "unused.cmd", tmp_path, "onebot11.json")
        assert entered.wait(5)
        closing = pool.submit(shell.stop, closing=True)
        release.set()
        launching.result(timeout=5)
        assert closing.result(timeout=5)
    assert stopped.is_set()
    assert shell.process is None
    with pytest.raises(ValueError, match="退出"):
        shell.start("unused.cmd", tmp_path, "onebot11.json")


@pytest.mark.skipif(os.name != "nt", reason="Windows process job")
def test_job_assignment_failure_kills_suspended_launcher(tmp_path, monkeypatch):
    from screen_qq_ocr.infrastructure.napcat.process_job import ProcessJob

    launcher = tmp_path / "launch.cmd"
    launcher.write_text('@echo off\necho unexpected > "%~dp0unexpected.txt"\n')
    processes = []

    def fail_attach(self, process):
        processes.append(process)
        raise OSError("assignment failed")

    def unavailable(*args, **kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(module.socket, "create_connection", unavailable)
    monkeypatch.setattr(ProcessJob, "attach_and_resume", fail_attach)
    shell = module.NapCatShell()
    with pytest.raises(OSError, match="assignment failed"):
        shell.start(launcher, tmp_path / "config", "onebot11.json")
    assert processes[0].poll() is not None
    assert shell.process is None and shell.job is None
    assert not (tmp_path / "unexpected.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows process job")
@pytest.mark.parametrize("close_handle", [False, True])
def test_stop_reaps_child_after_launcher_exits(tmp_path, monkeypatch, close_handle):
    import ctypes
    import sys
    from ctypes import wintypes

    child = tmp_path / "child.py"
    child.write_text(
        "import os, time\nfrom pathlib import Path\n"
        "Path(__file__).with_suffix('.pid').write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    launcher = tmp_path / "launch.cmd"
    launcher.write_text(f'@echo off\nstart "" /b "{sys.executable}" "{child}"\n')

    def unavailable(*args, **kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(module.socket, "create_connection", unavailable)
    shell = module.NapCatShell()
    handle = None
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        shell.start(launcher, tmp_path / "config", "onebot11.json")
        shell.process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while not child.with_suffix(".pid").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        pid = int(child.with_suffix(".pid").read_text())
        handle = api.OpenProcess(0x100000, False, pid)
        assert handle
        assert api.WaitForSingleObject(handle, 0) == 258
        if close_handle:
            shell.job.close()
        else:
            assert shell.stop() is True
        assert api.WaitForSingleObject(handle, 5000) == 0
        shell.stop()
        assert shell.stop() is False
    finally:
        shell.stop()
        if handle:
            api.CloseHandle(handle)
