import asyncio
import hashlib
from urllib.parse import urlparse

import httpx


class Management:
    """Native login probe. Current upstream contract; not a release compatibility claim."""

    def __init__(self):
        self.client = None
        self._qr_lock = asyncio.Lock()
        self._stale_qr = None

    async def connect(self, url, token):
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("管理地址必须为本机 HTTP 地址")
        if not token:
            raise ValueError("管理凭据不能为空")
        await self.close()
        self.client = httpx.AsyncClient(base_url=url.rstrip("/") + "/", timeout=10, trust_env=False)
        try:
            data = await self.call(
                "api/auth/login", {"hash": hashlib.sha256((token + ".napcat").encode()).hexdigest()}
            )
            if data.get("require2FA"):
                raise ValueError("该实例启用了管理端二次验证，当前适配器尚未支持")
            credential = data.get("Credential")
            if not credential:
                raise ValueError("管理鉴权响应不兼容，未建立登录连接")
            self.client.headers["Authorization"] = f"Bearer {credential}"
        except Exception:
            await self.close()
            raise

    async def call(self, route, body=None):
        if not self.client:
            raise ValueError("请先连接管理接口")
        try:
            response = await self.client.post(route, json=body or {})
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                raise ValueError("管理接口拒绝请求，请检查凭据、登录状态及兼容版本")
            return data.get("data") or {}
        except httpx.HTTPError as error:
            raise ValueError("管理接口连接失败，请检查地址、端口和运行状态") from error

    async def login_state(self):
        async with self._qr_lock:
            state = await self.call("api/QQLogin/CheckLoginStatus")
            if self._stale_qr and state.get("qrcodeurl") == self._stale_qr:
                return {**state, "qrcodeurl": ""}
            return state

    async def refresh_qr(self, timeout=10, interval=0.25):
        # RefreshQRcode acknowledges a request, not the asynchronous QR generation.
        # Serialize with status polling so an in-flight refresh cannot redisplay the old QR.
        async with self._qr_lock:
            before = await self.call("api/QQLogin/CheckLoginStatus")
            if before.get("isLogin") or before.get("isOffline"):
                return before
            self._stale_qr = before.get("qrcodeurl")
            await self.call("api/QQLogin/RefreshQRcode")
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                state = await self.call("api/QQLogin/CheckLoginStatus")
                if state.get("isLogin") or state.get("isOffline"):
                    return state
                if state.get("loginError"):
                    return {**state, "qrcodeurl": ""}
                if state.get("qrcodeurl") and state["qrcodeurl"] != before.get("qrcodeurl"):
                    return state
                if asyncio.get_running_loop().time() >= deadline:
                    return {
                        "loginError": "NapCat 尚未生成新的二维码，请稍后重试；若重复出现，请检查 NapCat 运行状态。",
                        "qrcodeurl": "",
                    }
                await asyncio.sleep(interval)

    async def close(self):
        self._stale_qr = None
        if self.client:
            await self.client.aclose()
            self.client = None
