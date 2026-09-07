from dataclasses import dataclass


@dataclass(frozen=True)
class NapCatConfig:
    mode: str = "attached"
    management_port: int = 6099
    websocket_port: int = 3001
    heartbeat: int = 30
    timeout: int = 10
    reconnect: bool = True
    reconnect_max: int = 15
    management_credential: str = "ScreenQQOCR/management"
    websocket_credential: str = "ScreenQQOCR/onebot"

    def validate(self):
        if self.mode not in ("managed", "attached"):
            raise ValueError("运行模式无效")
        for value in (self.management_port, self.websocket_port):
            if type(value) is not int or not 1024 <= value <= 65535:
                raise ValueError("端口必须为 1024–65535 的整数")
        if self.management_port == self.websocket_port:
            raise ValueError("管理端口与 WS 端口不能相同")
        for key, lower in (("heartbeat", 5), ("timeout", 3), ("reconnect_max", 5)):
            if type(getattr(self, key)) is not int or not lower <= getattr(self, key) <= 60:
                raise ValueError(f"{key} 必须为 {lower}–60 秒")
