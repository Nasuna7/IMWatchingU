from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import uuid4


@dataclass(frozen=True)
class QQTarget:
    account_id: str
    type: str
    id: str
    display_name: str = ""

    def __post_init__(self):
        if (
            self.type not in ("private", "group")
            or not isinstance(self.id, str)
            or not isinstance(self.account_id, str)
            or not self.id.isdecimal()
            or not self.account_id.isdecimal()
        ):
            raise ValueError("QQ 账号和对象必须为数字 ID，类型必须为好友或群")


@dataclass(frozen=True)
class SendPolicy:
    confirm_frames: int = 1
    repeat: str = "cooldown"
    cooldown: int = 60
    countdown: int = 3
    message_type: str = "text"
    body_source: str = "hit_line"
    body: str = ""
    target: QQTarget | None = None
    targets: tuple[QQTarget, ...] = ()

    def validate(self):
        from .templates import validate_template

        if type(self.confirm_frames) is not int or not 1 <= self.confirm_frames <= 10:
            raise ValueError("连续确认必须为 1–10 帧")
        if type(self.cooldown) is not int or not 0 <= self.cooldown <= 86400:
            raise ValueError("冷却必须为 0–86400 秒")
        if (
            type(self.countdown) is not int
            or self.countdown not in (0, 3, 5)
            or self.repeat not in ("cooldown", "once")
        ):
            raise ValueError("无效的倒计时或重复方式")
        if self.message_type not in ("text", "text_image", "image"):
            raise ValueError("无效的消息类型")
        if self.message_type == "image":
            return
        if self.body_source not in ("hit_line", "ocr_text", "fixed", "template"):
            raise ValueError("无效的正文来源")
        if self.body_source in ("fixed", "template"):
            if not isinstance(self.body, str) or not self.body.strip() or len(self.body) > 2000:
                raise ValueError("固定文本或模板须为 1–2000 字符")
            if self.body_source == "template":
                validate_template(self.body)

    @property
    def recipients(self) -> tuple[QQTarget, ...]:
        return tuple(self.targets or ()) or ((self.target,) if self.target else ())


@dataclass(frozen=True)
class SendOverrides:
    confirm_frames: int | None = None
    repeat: str | None = None
    cooldown: int | None = None
    countdown: int | None = None
    message_type: str | None = None
    body_source: str | None = None
    body: str | None = None
    target: QQTarget | None = None
    targets: tuple[QQTarget, ...] | None = None

    def resolve(self, default: SendPolicy) -> SendPolicy:
        values = {
            name: getattr(self, name) for name in self.__dataclass_fields__ if getattr(self, name) is not None
        }
        policy = replace(default, **values)
        policy.validate()
        return policy


@dataclass(frozen=True)
class KeywordRule:
    keyword: str
    min_count: int = 1
    alias: str = ""
    enabled: bool = True
    sort_order: int = 0
    send_overrides: SendOverrides = field(default_factory=SendOverrides)
    id: str = field(default_factory=lambda: str(uuid4()))
    revision: int = 1

    def __post_init__(self):
        from .matching import normalize

        if (
            not isinstance(self.keyword, str)
            or not 1 <= len(self.keyword.strip()) <= 100
            or not normalize(self.keyword)
        ):
            raise ValueError("关键词去除首尾空白后须为 1–100 字符")
        if type(self.min_count) is not int or not 1 <= self.min_count <= 999:
            raise ValueError("次数必须为 1–999 的整数")
        if not isinstance(self.alias, str) or len(self.alias.strip()) > 100:
            raise ValueError("关键词别名最多 100 字符")
        if type(self.enabled) is not bool:
            raise ValueError("enabled 必须为布尔值")
        object.__setattr__(self, "keyword", self.keyword.strip())
        object.__setattr__(self, "alias", self.alias.strip())


@dataclass(frozen=True)
class FrameSnapshot:
    frame_id: str
    session_id: int
    capture_time: datetime
    monotonic_time: float
    width: int
    height: int
    rgb: bytes


@dataclass(frozen=True)
class OcrLine:
    text: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class OcrResult:
    frame: FrameSnapshot
    engine: str
    text: str
    elapsed_ms: float
    lines: tuple[OcrLine, ...] = ()


@dataclass(frozen=True)
class SendTask:
    session_id: int
    rule_id: str
    revision: int
    policy: SendPolicy
    frame: FrameSnapshot
    text: str
    created_at: float
    is_test: bool = False
    task_id: str = field(default_factory=lambda: str(uuid4()))
    monitor_id: str = ""

    @property
    def key(self):
        key = tuple((t.account_id, t.type, t.id) for t in self.policy.recipients) + (self.rule_id,)
        return (*key, self.monitor_id) if self.monitor_id else key


@dataclass(frozen=True)
class SendReceipt:
    part: str
    status: str
    message_id: str = ""
    error_code: str = ""
