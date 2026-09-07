import asyncio


class QQService:
    """Reconnect transport only; never replay messages or accept an unexpected account."""

    def __init__(self, messaging, emit):
        self.messaging, self.emit = messaging, emit
        self.supervisor = None
        self.expected_account = ""

    async def connect(self, url, token):
        await self.disconnect()
        info, targets = await self.messaging.open(url, token)
        self.expected_account = str(info["user_id"])
        self.emit("account", info)
        self.emit("targets", targets)
        self.emit("qq_status", "QQ：可发送")
        self.supervisor = asyncio.create_task(self._supervise(url, token))
        return info, targets

    async def _supervise(self, url, token):
        attempt = 0
        while True:
            if self.messaging.online:
                attempt = 0
                await asyncio.sleep(1)
                continue
            delay = (1, 2, 4, 8, 15)[min(attempt, 4)]
            self.emit("qq_status", f"QQ：离线，{delay} 秒后重连")
            await asyncio.sleep(delay)
            try:
                info, targets = await self.messaging.open(url, token)
                if str(info["user_id"]) != self.expected_account:
                    await self.messaging.close()
                    self.emit("error", "重连后 QQ 账号发生变化，已断开；请手动连接并重新核验对象")
                    return
                self.emit("targets", targets)
                self.emit("qq_status", "QQ：已重连，仅处理新命中")
                attempt = 0
            except Exception:
                attempt += 1

    async def disconnect(self):
        if self.supervisor:
            self.supervisor.cancel()
            await asyncio.gather(self.supervisor, return_exceptions=True)
            self.supervisor = None
        await self.messaging.close()
