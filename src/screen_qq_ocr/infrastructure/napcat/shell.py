import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from screen_qq_ocr.infrastructure.persistence.settings import atomic_json


@dataclass(frozen=True)
class ShellConnection:
    management_url: str
    management_token: str = field(repr=False)
    onebot_url: str
    onebot_token: str = field(repr=False)


def read_config(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"NapCat 配置格式无效：{path.name}；原文件未修改") from error


def local_host(host):
    if host in ("", "0.0.0.0", "::", "127.0.0.1", "localhost"):
        return "127.0.0.1"
    if host == "::1":
        return "[::1]"
    raise ValueError("所选 NapCat 配置不是本机监听地址，请选择本机配置")


def port(value):
    if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= 65535:
        raise ValueError("NapCat 配置中的端口无效")
    return int(value)


class NapCatShell:
    def __init__(self):
        self.process = None
        self.job = None
        self._lock = threading.RLock()
        self._closed = False

    def stop(self, closing=False):
        """Stop only our owned process tree; closing also prevents late starts."""
        with self._lock:
            if closing:
                self._closed = True
            owned = self.process is not None or self.job is not None
            if self.job:
                self.job.stop()
                self.job = None
            elif self.process and self.process.poll() is None:
                self.process.terminate()
            if self.process:
                self.process.wait(timeout=5)
                self.process = None
            return owned

    def connection(self, config_dir, onebot_name="onebot11.json", prepare=False):
        folder = Path(config_dir).resolve()
        if prepare:
            folder.mkdir(parents=True, exist_ok=True)
        if (
            Path(onebot_name).name != onebot_name
            or not onebot_name.startswith("onebot11")
            or not onebot_name.endswith(".json")
        ):
            raise ValueError("请选择配置目录中的 OneBot JSON 文件")
        web_path, bot_path = folder / "webui.json", folder / onebot_name
        web, bot = read_config(web_path), read_config(bot_path)
        before = (json.dumps(web), json.dumps(bot))
        if prepare:
            web.setdefault("host", "127.0.0.1")
            web.setdefault("port", 6099)
            if not web.get("token"):
                web["token"] = secrets.token_urlsafe(32)
        if web.get("disableWebUI"):
            raise ValueError("NapCat 已禁用管理端，请先在配置中启用 WebUI")
        if not web.get("token"):
            raise ValueError("尚未找到管理端 token，请启动 NapCat 后重新读取")
        network = bot.setdefault("network", {})
        servers = network.setdefault("websocketServers", [])
        if not isinstance(servers, list):
            raise ValueError("OneBot websocketServers 配置格式无效")
        enabled = [server for server in servers if server.get("enable")]
        server = next((s for s in enabled if s.get("name") == "ScreenQQOCR"), None)
        if server is None:
            if len(enabled) > 1:
                raise ValueError("所选文件有多个正向 WS，请将要使用的通道命名为 ScreenQQOCR")
            server = enabled[0] if enabled else None
        if server is None:
            if not prepare:
                raise ValueError("所选配置未启用 OneBot 正向 WS；可点击启动并自动配置")
            server = dict(
                name="ScreenQQOCR",
                enable=True,
                host="127.0.0.1",
                port=3001,
                token=secrets.token_urlsafe(32),
                messagePostFormat="array",
                reportSelfMessage=False,
                enableForcePushEvent=True,
                heartInterval=30000,
            )
            servers.append(server)
        if not server.get("token"):
            if not prepare:
                raise ValueError("消息通道未配置 token；请通过启动并自动配置补全后重启 NapCat")
            server["token"] = secrets.token_urlsafe(32)
        connection = ShellConnection(
            f"http://{local_host(web.get('host', '127.0.0.1'))}:{port(web.get('port', 6099))}",
            web["token"],
            f"ws://{local_host(server.get('host', '127.0.0.1'))}:{port(server.get('port', 3001))}",
            server.get("token", ""),
        )
        if prepare:
            changed = [
                (path, data)
                for path, data, original in zip((web_path, bot_path), (web, bot), before)
                if json.dumps(data) != original
            ]
            backups = {}
            try:
                for path, data in changed:
                    backups[path] = path.read_bytes() if path.exists() else None
                    if path.exists():
                        backup = path.with_name(path.name + datetime.now().strftime(".%Y%m%d-%H%M%S-%f.bak"))
                        shutil.copy2(path, backup)
                    atomic_json(path, data)
            except Exception:
                for path, original in backups.items():
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(original)
                raise
        return connection

    def start(self, launcher, config_dir, onebot_name):
        with self._lock:
            if self._closed:
                raise ValueError("应用正在退出，无法启动 NapCat")
            return self._start(launcher, config_dir, onebot_name)

    def _start(self, launcher, config_dir, onebot_name):
        path = Path(launcher).resolve()
        if not path.is_file() or path.suffix.lower() not in (".bat", ".cmd", ".ps1", ".exe"):
            raise ValueError("请选择已安装 NapCat Shell 的启动文件（bat/cmd/ps1/exe）")
        if self.process and self.process.poll() is None:
            return self.connection(config_dir, onebot_name)
        web = read_config(Path(config_dir) / "webui.json")
        host = local_host(web.get("host", "127.0.0.1")).strip("[]")
        try:
            with socket.create_connection((host, port(web.get("port", 6099))), timeout=0.3):
                # An existing listener must be authenticated by the presenter; never rewrite its config.
                return self.connection(config_dir, onebot_name)
        except OSError:
            pass
        connection = self.connection(config_dir, onebot_name, prepare=True)
        # A previous launcher may have exited while its descendants survived.
        self.stop()
        environment = os.environ.copy()
        # Pass a batch path via an environment variable, never interpolate it into shell syntax.
        if path.suffix.lower() in (".bat", ".cmd"):
            environment["IMWATCHINGU_NAPCAT_LAUNCHER"] = str(path)
            interpreter = os.environ.get("COMSPEC", "cmd.exe")
            command = f'"{interpreter}" /d /v:off /s /c ""%IMWATCHINGU_NAPCAT_LAUNCHER%""'
        elif path.suffix.lower() == ".ps1":
            command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)]
        else:
            command = [str(path)]
        try:
            if os.name == "nt":
                from .process_job import ProcessJob

                self.job = ProcessJob()
            self.process = subprocess.Popen(
                command,
                cwd=path.parent,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(subprocess.CREATE_NO_WINDOW | 0x4) if os.name == "nt" else 0,
            )
            if self.job:
                self.job.attach_and_resume(self.process)
        except BaseException:
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            if self.job:
                self.job.close()
                self.job = None
            self.process = None
            raise
        return connection
