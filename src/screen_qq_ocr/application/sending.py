import asyncio
import time
from collections import deque

from screen_qq_ocr.domain.cooldown import Cooldowns
from screen_qq_ocr.domain.models import SendReceipt


class SendQueue:
    """All methods run on the network loop. Cancellation never retries a submitted request."""

    def __init__(
        self,
        messaging,
        encode_png,
        on_event=lambda *args: None,
        clock=time.monotonic,
        request_interval=2,
        capacity=100,
        image_budget=64 * 1024 * 1024,
    ):
        self.messaging = messaging
        self.encode_png = encode_png
        self.on_event = on_event
        self.clock = clock
        self.request_interval = request_interval
        self.capacity = capacity
        self.image_budget = image_budget
        self.pending = deque()
        self.current = None
        self.cancelled = set()
        self.cooldowns = Cooldowns()
        self.last_request = float("-inf")
        self.running = True

    def accept(self, task):
        active = [*self.pending] + ([self.current] if self.current else [])
        if len(active) >= self.capacity:
            return False
        frames = {t.frame.frame_id: len(t.frame.rgb) for t in [*active, task]}
        if sum(frames.values()) > self.image_budget:
            return False
        if not task.policy.recipients:
            return False
        if not task.is_test and not self.cooldowns.acquire(task.key, self.clock(), task.policy.cooldown):
            return False
        self.pending.append(task)
        self.on_event(task, "待发送", ())
        return True

    def cancel(self, rule_id=None, monitor_id=None):
        def matches(task):
            return (rule_id is None or task.rule_id == rule_id) and (
                monitor_id is None or task.monitor_id == monitor_id
            )

        retained = deque()
        for task in self.pending:
            if matches(task):
                self._finish(task, "取消", [])
            else:
                retained.append(task)
        self.pending = retained
        if self.current and matches(self.current):
            self.cancelled.add(self.current.task_id)

    def _invalid(self, task):
        if task.task_id in self.cancelled or not self.running:
            return "取消"
        if self.clock() - task.created_at >= 60:
            return "过期"
        return ""

    async def _wait_until(self, task, deadline):
        while self.clock() < deadline:
            if self._invalid(task):
                return False
            await asyncio.sleep(min(0.05, max(0, deadline - self.clock())))
        return not self._invalid(task)

    def _finish(self, task, status, receipts):
        if not task.is_test:
            self.cooldowns.release(task.key)
        self.cancelled.discard(task.task_id)
        self.on_event(task, status, tuple(receipts))

    async def execute(self, task):
        receipts = []
        invalid = self._invalid(task)
        if not invalid:
            self.on_event(task, "倒计时", ())
            await self._wait_until(task, self.clock() + task.policy.countdown)
            invalid = self._invalid(task)
        if invalid:
            self._finish(task, invalid, receipts)
            return
        parts = ["text", "image"] if task.policy.message_type == "text_image" else [task.policy.message_type]
        for part in parts:
            if not await self._wait_until(task, self.last_request + self.request_interval):
                break
            try:
                content = task.text if part == "text" else self.encode_png(task.frame)
                if part == "image" and len(content) > 8 * 1024 * 1024:
                    receipts.append(SendReceipt(part, "failed", error_code="IMAGE_TOO_LARGE"))
                    break
                if self._invalid(task):
                    break
                self.last_request = self.clock()
                self.on_event(task, "发送中", tuple(receipts))
                for target in task.policy.recipients:
                    receipt = await self.messaging.send_part(target, part, content)
                    receipts.append(receipt)
                    if receipt.status != "success":
                        break
                if not receipts or receipts[-1].status != "success":
                    break
            except asyncio.CancelledError:
                receipts.append(SendReceipt(part, "unknown", error_code="SHUTDOWN"))
                self._finish(task, "结果未知", receipts)
                raise
            except Exception:
                receipts.append(SendReceipt(part, "failed", error_code="ENCODING_OR_ADAPTER_ERROR"))
                break
        expected = len(parts) * len(task.policy.recipients)
        if any(r.status == "unknown" for r in receipts):
            status = "结果未知"
        elif len(receipts) == expected and all(r.status == "success" for r in receipts):
            status = "成功"
        elif any(r.status == "success" for r in receipts):
            status = "部分成功"
        else:
            status = self._invalid(task) or "失败"
        self._finish(task, status, receipts)

    async def run(self):
        while self.running:
            if not self.pending:
                await asyncio.sleep(0.05)
                continue
            self.current = self.pending.popleft()
            try:
                await self.execute(self.current)
            finally:
                self.current = None
