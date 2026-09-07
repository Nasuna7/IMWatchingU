import asyncio
import base64
import json
import time
from urllib.parse import urlparse
from uuid import uuid4

from websockets.asyncio.client import connect

from screen_qq_ocr.domain.models import QQTarget, SendReceipt


class ApiError(Exception):
    def __init__(self, code, submitted=False):
        self.code, self.submitted = str(code), submitted
        super().__init__(self.code)


class OneBot:
    def __init__(self, on_disconnect=lambda: None, timeout=10, heartbeat=30):
        self.ws = None
        self.pending = {}
        self.reader = None
        self.watchdog = None
        self.timeout, self.heartbeat = timeout, heartbeat
        self.on_disconnect = on_disconnect
        self.account = ""
        self.targets = []
        self.online = False

    async def open(self, url, token):
        parsed = urlparse(url)
        if parsed.scheme != "ws" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("首版只允许本机 OneBot 正向 WS")
        if not token:
            raise ValueError("OneBot Token 不能为空")
        await self.close()
        self.ws = await connect(
            url,
            additional_headers={"Authorization": f"Bearer {token}"},
            open_timeout=self.timeout,
            max_size=4 * 1024 * 1024,
            proxy=None,
        )
        self.last_seen = time.monotonic()
        self.reader = asyncio.create_task(self._read())
        self.watchdog = asyncio.create_task(self._watch())
        try:
            info = await self.request("get_login_info", {})
            status = await self.request("get_status", {})
            if status.get("online") is not True:
                raise ApiError("QQ_OFFLINE")
            self.account = str(info["user_id"])
            if not self.account.isdecimal():
                raise ApiError("INVALID_ACCOUNT")
            self.targets = await self.list_targets()
            self.online = True
            return info, self.targets
        except Exception:
            await self.close()
            raise

    async def _watch(self):
        while self.ws:
            await asyncio.sleep(self.heartbeat)
            if time.monotonic() - self.last_seen > 2 * self.heartbeat:
                await self.ws.close()
                return

    async def _read(self):
        try:
            async for raw in self.ws:
                data = json.loads(raw)
                self.last_seen = time.monotonic()
                if (
                    data.get("meta_event_type") == "heartbeat"
                    and data.get("status", {}).get("online") is False
                ):
                    raise ApiError("QQ_OFFLINE")
                echo = data.get("echo")
                future = self.pending.get(echo) if isinstance(echo, str) else None
                if future and not future.done():
                    future.set_result(data)
        except Exception:
            pass
        finally:
            self.online = False
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(ApiError("DISCONNECTED", submitted=True))
            self.on_disconnect()

    async def request(self, action, params):
        if self.ws is None:
            raise ApiError("NOT_CONNECTED")
        if len(self.pending) >= 100:
            raise ApiError("PENDING_LIMIT")
        echo = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        submitted = False
        try:
            submitted = True
            await self.ws.send(json.dumps(dict(action=action, params=params, echo=echo)))
            response = await asyncio.wait_for(future, self.timeout)
            if response.get("status") != "ok" or response.get("retcode") != 0:
                raise ApiError(response.get("retcode", "INVALID_RESPONSE"))
            return response.get("data") or {}
        except (TimeoutError, OSError) as error:
            raise ApiError("TIMEOUT_OR_CONNECTION", submitted) from error
        except ApiError:
            raise
        except Exception as error:
            raise ApiError("TRANSPORT_ERROR", submitted) from error
        finally:
            self.pending.pop(echo, None)
            if not future.done():
                future.cancel()

    async def list_targets(self):
        friends = await self.request("get_friend_list", {})
        groups = await self.request("get_group_list", {})
        return [
            QQTarget(self.account, "private", str(x["user_id"]), x.get("remark") or x.get("nickname", ""))
            for x in friends
        ] + [QQTarget(self.account, "group", str(x["group_id"]), x.get("group_name", "")) for x in groups]

    async def send_part(self, target, part, content):
        if not self.online or target.account_id != self.account:
            return SendReceipt(part, "failed", error_code="ACCOUNT_OFFLINE_OR_CHANGED")
        if not any(
            (t.account_id, t.type, t.id) == (target.account_id, target.type, target.id) for t in self.targets
        ):
            return SendReceipt(part, "failed", error_code="TARGET_NOT_VERIFIED")
        segment = (
            {"type": "text", "data": {"text": content}}
            if part == "text"
            else {"type": "image", "data": {"file": "base64://" + base64.b64encode(content).decode("ascii")}}
        )
        try:
            field = "user_id" if target.type == "private" else "group_id"
            data = await self.request(
                f"send_{target.type}_msg", {field: int(target.id), "message": [segment]}
            )
            if data.get("message_id") is None:
                return SendReceipt(part, "unknown", error_code="MISSING_MESSAGE_ID")
            return SendReceipt(part, "success", str(data["message_id"]))
        except ApiError as error:
            return SendReceipt(part, "unknown" if error.submitted else "failed", error_code=error.code)

    async def close(self):
        self.online = False
        if self.ws:
            await self.ws.close()
        for task in (self.reader, self.watchdog):
            if task and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.ws = None
        self.reader = self.watchdog = None
