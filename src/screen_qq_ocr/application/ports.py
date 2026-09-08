from typing import Protocol

from screen_qq_ocr.domain.models import FrameSnapshot, OcrResult, QQTarget, SendReceipt


class CaptureNotReady(ValueError):
    """The capture stream is open but its requested frame has not arrived yet."""


class OcrPort(Protocol):
    def recognize(self, frame: FrameSnapshot) -> OcrResult: ...


class MessagingPort(Protocol):
    async def send_part(self, target: QQTarget, part: str, content: str | bytes) -> SendReceipt: ...


class RuleStore(Protocol):
    def list_rules(self) -> list: ...
    def save_rule(self, rule): ...
    def delete_rule(self, rule_id: str): ...
