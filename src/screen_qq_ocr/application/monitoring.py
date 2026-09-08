import asyncio
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial

from screen_qq_ocr.application.ports import CaptureNotReady
from screen_qq_ocr.domain.flash import FlashDetector
from screen_qq_ocr.domain.matching import match
from screen_qq_ocr.domain.models import SendTask
from screen_qq_ocr.domain.send_policy import TriggerTracker
from screen_qq_ocr.domain.templates import render


class Monitoring:
    def __init__(self, capture, ocr_worker, queue, messaging, store, settings, analyze_color, emit):
        self.capture, self.ocr_worker, self.queue = capture, ocr_worker, queue
        self.messaging, self.store, self.settings = messaging, store, settings
        self.analyze_color, self.emit = analyze_color, emit
        self.session = 0
        self.active = False
        self.keywords = False
        self.flash_enabled = False
        self.configured_keywords = True
        self.configured_flash = False
        self.last_result = None
        self.last_frame = None
        self.last_preview = None
        self.roi = (0, 0, 1, 1)
        self.image_roi = (0, 0, 1, 1)
        self.capture_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture")
        self.source = None
        self.ocr_task = None
        self.capture_task = None
        self.capture_open = False
        self.next_ocr = 0
        self.next_preview = 0
        self.last_ocr_signature = None
        self.failures = 0
        self.policy_epoch = 0
        self.policy_lock = asyncio.Lock()
        self.rules = []
        self.default = None
        self.triggers = TriggerTracker()
        self.flash = FlashDetector()

    async def reload(self):
        self.rules = await asyncio.to_thread(self.store.list_rules)
        self.default = await asyncio.to_thread(self.store.default_policy)
        self.emit("rules", tuple(self.rules))
        self.emit("policy", self.default)

    async def select_source(self, source, roi=(0, 0, 1, 1)):
        if source is None:
            raise ValueError("请先选择采集源")
        await self.stop()
        self.last_result = self.last_frame = self.last_preview = None
        self.source = source
        await self.open_capture()
        self.roi = roi
        # read_capture waits for WGC's first frame before publishing the static preview.
        try:
            frame = await self.grab_frame(force_preview=True)
            self.last_frame = frame
            self.emit("roi", roi)
            self.emit("capture_status", "采集已就绪")
        except ValueError:
            self.source = None
            raise
        finally:
            if not self.active:
                await self.close_capture()

    async def capture_call(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self.capture_executor, partial(function, *args)
        )

    async def open_capture(self):
        if not self.source:
            raise ValueError("请先选择采集源")
        if not self.capture_open:
            await self.capture_call(self.capture.open, self.source)
            self.capture_open = True

    async def close_capture(self):
        if self.capture_open:
            await self.capture_call(self.capture.close)
            self.capture_open = False

    async def configure_capture_roi(self, roi):
        setter = getattr(self.capture, "set_roi", None)
        if setter:
            await self.capture_call(setter, tuple(roi))

    async def read_capture(self, roi):
        # Opening WGC and switching its ROI are asynchronous. Only retry missing
        # frames; closed/minimized sources and other capture errors remain fatal.
        for attempt in range(40):
            try:
                return await self.capture_call(self.capture.grab, self.session, roi)
            except CaptureNotReady:
                if attempt == 39:
                    raise
                await asyncio.sleep(0.15)

    async def grab_frame(self, force_preview=False):
        await self.open_capture()
        now = time.monotonic()
        interval = 0.5 if self.settings.values["appearance"]["low_resource"] else 0.2
        preview_due = force_preview or now >= self.next_preview
        if preview_due:
            full = await self.read_capture((0, 0, 1, 1))
            self.last_preview = full
            self.emit("frame", full)
            self.next_preview = now + interval
            if self.roi == (0, 0, 1, 1):
                return full
            return self.crop_snapshot(full, self.roi)
        return await self.grab_monitor_frame()

    async def grab_monitor_frame(self):
        await self.open_capture()
        return await self.read_capture(self.roi)

    def crop_snapshot(self, frame, roi):
        from PIL import Image

        from screen_qq_ocr.infrastructure.capture.coordinates import pixel_box

        image = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb)
        image = image.crop(pixel_box(roi, frame.width, frame.height))
        return replace(frame, width=image.width, height=image.height, rgb=image.tobytes())

    async def set_roi(self, roi):
        from screen_qq_ocr.infrastructure.capture.coordinates import pixel_box

        if not self.source:
            raise ValueError("请先选择采集源")
        if self.last_preview:
            pixel_box(roi, self.last_preview.width, self.last_preview.height)
        running, keywords, flash = self.active, self.keywords, self.flash_enabled
        await self.stop()
        self.roi = tuple(roi)
        self.last_result = None
        if running:
            await self.start(keywords, flash)
            self.last_frame = await self.grab_frame(force_preview=True)
        else:
            self.last_frame = None
            self.emit("roi", self.roi)

    async def set_image_roi(self, roi):
        from screen_qq_ocr.infrastructure.capture.coordinates import pixel_box

        if not self.source or not self.last_preview:
            raise ValueError("请先选择采集源")
        pixel_box(roi, self.last_preview.width, self.last_preview.height)
        self.image_roi = tuple(roi)
        self.emit("image_roi", self.image_roi)

    def validate_targets(self):
        reasons = []
        enabled = [r for r in self.rules if r.enabled]
        if not enabled:
            reasons.append("至少启用一条关键词规则")
        if not self.messaging.online:
            reasons.append("QQ 消息通道尚未就绪")
        for rule in enabled:
            policy = rule.send_overrides.resolve(self.default)
            if not policy.recipients or any(
                not any(
                    (t.account_id, t.type, t.id) == (x.account_id, x.type, x.id)
                    for x in self.messaging.targets
                )
                for t in policy.recipients
            ):
                reasons.append(f"{rule.keyword}：发送对象尚未核验")
        return reasons

    async def start(self, keywords, flash):
        self.configured_keywords, self.configured_flash = bool(keywords), bool(flash)
        if not self.source:
            raise ValueError("请先选择并验证采集源")
        if not keywords and not flash:
            raise ValueError("至少启用关键词或色块模块")
        await self.reload()
        if keywords:
            reasons = self.validate_targets()
            if reasons:
                raise ValueError("；".join(reasons))
        await self.stop()
        await self.open_capture()
        await self.configure_capture_roi(self.roi)
        if keywords:
            await self.ocr_worker.availability(self.settings.values["ocr"])
            await self.release_ocr_if_idle()
        self.active, self.keywords, self.flash_enabled = True, keywords, flash
        self.flash.cooldown = self.settings.values["flash"]["cooldown"]
        self.failures = 0
        self.next_ocr = 0
        self.next_preview = 0
        self.last_ocr_signature = None
        self.capture_task = asyncio.create_task(self._capture_loop())
        self.emit("monitor_status", "运行")

    async def stop(self):
        self.active = False
        self.keywords = False
        self.session += 1
        self.queue.cancel()
        self.triggers.reset_continuity()
        self.flash.reset()
        if self.capture_task and self.capture_task is not asyncio.current_task():
            self.capture_task.cancel()
            await asyncio.gather(self.capture_task, return_exceptions=True)
        self.capture_task = None
        self.emit("sound_stop", None)
        self.emit("monitor_status", "停止")
        await self.close_capture()
        if not self.ocr_task and hasattr(self.ocr_worker, "shutdown"):
            await self.ocr_worker.shutdown()

    async def pause_keywords(self):
        self.keywords = False
        self.policy_epoch += 1
        self.queue.cancel()
        self.triggers.reset_continuity()
        await self.release_ocr_if_idle()
        self.emit("ocr_status", "关键词已暂停，应用后需重新开始")

    async def _capture_loop(self):
        next_flash = 0
        try:
            while self.active:
                started_at = time.monotonic()
                frame = await self.grab_monitor_frame()
                self.last_frame = frame
                now = time.monotonic()
                if self.flash_enabled and now >= next_flash:
                    color = await asyncio.to_thread(self.analyze_color, frame)
                    alarm = self.flash.sample(color, frame.monotonic_time)
                    self.emit("flash", (color, self.flash.changes, alarm))
                    if alarm:
                        self.emit("sound", self.settings.values["flash"]["sound"])
                    next_flash = now + self.read_interval()
                if self.keywords and now >= self.next_ocr and not self.ocr_task:
                    if self.mark_changed_for_ocr(frame):
                        self.ocr_task = asyncio.create_task(self._recognize(frame, automatic=True))
                    else:
                        self.next_ocr = now + self.ocr_interval()
                elapsed = time.monotonic() - started_at
                await asyncio.sleep(max(0, self.read_interval() - elapsed))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.emit("error", str(error))
            await self.stop()
            self.emit("capture_status", "采集暂停，请重新选择")

    async def recognize_once(self):
        if self.ocr_task:
            if self.last_result:
                self.emit("ocr", self.last_result)
            self.emit("info", "当前识别正在执行，完成后显示结果；没有新增发送任务")
            return
        if not self.source:
            raise ValueError("请先选择采集源")
        if self.active:
            frame = await self.grab_frame(force_preview=True)
        else:
            await self.open_capture()
            try:
                frame = await self.read_capture(self.roi)
            finally:
                await self.close_capture()
        self.last_frame = frame
        self.ocr_task = asyncio.create_task(self._recognize(frame, automatic=False))

    async def refresh_preview(self):
        try:
            self.last_frame = await self.grab_frame(force_preview=True)
        finally:
            if self.active:
                await self.configure_capture_roi(self.roi)
            else:
                await self.close_capture()

    async def _recognize(self, frame, automatic):
        epoch = self.policy_epoch
        try:
            result = await self.ocr_worker.recognize(frame, dict(self.settings.values["ocr"]))
            if frame.session_id != self.session:
                return
            self.failures = 0
            self.last_result = result
            self.emit("ocr", result)
            self.emit("ocr_status", "OCR 已就绪")
            if not automatic:
                self.emit("toast", "识别完成" if result.text.strip() else "识别完成，未发现文字")
            if automatic and self.active and self.keywords and epoch == self.policy_epoch:
                for rule in self.rules:
                    if not rule.enabled:
                        continue
                    policy = rule.send_overrides.resolve(self.default)
                    if not policy.recipients:
                        continue
                    key = tuple((t.account_id, t.type, t.id) for t in policy.recipients) + (rule.id,)
                    matched = match(result.text, rule.keyword, rule.min_count, result.lines)
                    eligible = self.triggers.observe(key, frame.frame_id, self.session, matched.hit, policy)
                    if eligible and self.messaging.online:
                        text, _ = render(policy, rule, result, matched)
                        if policy.message_type != "image" and not text.strip():
                            continue
                        image_frame = self.matched_image_snapshot(result, matched)
                        task = SendTask(
                            self.session,
                            rule.id,
                            rule.revision,
                            policy,
                            image_frame,
                            text,
                            time.monotonic(),
                        )
                        if self.queue.accept(task):
                            self.triggers.accepted(key)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if frame.session_id != self.session:
                return
            self.emit("error", str(error))
            if automatic:
                self.last_ocr_signature = None
                self.triggers.reset_continuity()
                self.failures += 1
                if self.failures >= 3:
                    self.keywords = False
                    self.queue.cancel()
                    self.emit("ocr_status", "连续失败 3 次，请重试 OCR")
        finally:
            self.next_ocr = time.monotonic() + self.ocr_interval()
            self.ocr_task = None
            await self.release_ocr_if_idle()

    def ocr_interval(self):
        return self.settings.values["ocr"]["interval"]

    def read_interval(self):
        return max(0.2, float(self.settings.values.get("capture", {}).get("read_interval", 5)))

    def keep_ocr_worker_alive(self):
        return self.active and self.keywords and self.settings.values["lifecycle"].get("close_to_tray", True)

    async def release_ocr_if_idle(self):
        if not self.ocr_task and not self.keep_ocr_worker_alive() and hasattr(self.ocr_worker, "shutdown"):
            await self.ocr_worker.shutdown()

    def mark_changed_for_ocr(self, frame):
        signature = self.frame_signature(frame)
        if signature == self.last_ocr_signature:
            return False
        self.last_ocr_signature = signature
        return True

    @staticmethod
    def frame_signature(frame):
        return frame.width, frame.height, zlib.crc32(frame.rgb)

    async def save_rule(self, rule):
        old = next((r for r in self.rules if r.id == rule.id), None)
        if old and old.send_overrides != rule.send_overrides:
            await self.pause_keywords()
        self.queue.cancel(rule.id)
        await asyncio.to_thread(self.store.save_rule, rule)
        await self.reload()

    async def delete_rule(self, rule_id):
        self.queue.cancel(rule_id)
        await asyncio.to_thread(self.store.delete_rule, rule_id)
        await self.reload()

    async def save_policy(self, policy):
        async with self.policy_lock:
            await self.pause_keywords()
            await asyncio.to_thread(self.store.save_policy, policy)
            await self.reload()

    async def preview(self, rule_id, sample_text=None):
        from screen_qq_ocr.domain.models import OcrResult

        async with self.policy_lock:
            return self._preview_locked(rule_id, sample_text, OcrResult)

    def _preview_locked(self, rule_id, sample_text, ocr_result_type):
        rule = next((r for r in self.rules if r.id == rule_id), None)
        if not rule:
            raise ValueError("请先选择规则")
        result = self.last_result
        if sample_text is not None:
            if not self.last_frame:
                raise ValueError("请先采集画面，试算不会发送")
            result = ocr_result_type(self.last_frame, "示例", sample_text, 0)
        if not result:
            raise ValueError("尚无识别结果，请识别一次或输入示例")
        policy = rule.send_overrides.resolve(self.default)
        matched = match(result.text, rule.keyword, rule.min_count, result.lines)
        text, truncated = render(policy, rule, result, matched)
        target = policy.recipients[0] if policy.recipients else None
        key = tuple((t.account_id, t.type, t.id) for t in policy.recipients) + (rule.id,) if target else None
        state = self.triggers.states.get(key)
        cooldown_key = (*key, self.queue.monitor_id) if key and hasattr(self.queue, "monitor_id") else key
        details = {
            "次数": f"{matched.count}/{rule.min_count}",
            "连续帧": f"{state.consecutive if state else 0}/{policy.confirm_frames}",
            "冷却可用": bool(
                key and self.queue.cooldowns.available(cooldown_key, time.monotonic(), policy.cooldown)
            ),
            "本轮已占用": bool(state and state.round_used),
            "在线": self.messaging.online,
            "对象": target,
            "截断": truncated,
            "消息": text,
            "类型": policy.message_type,
        }
        self.emit("preview", details)
        return SendTask(
            self.session,
            rule.id,
            rule.revision,
            policy,
            self.matched_image_snapshot(result, matched),
            text,
            time.monotonic(),
            is_test=True,
            monitor_id=getattr(self.queue, "monitor_id", ""),
        )

    def matched_image_snapshot(self, result, matched):
        if not self.last_preview:
            return result.frame
        return self.crop_snapshot(
            self.last_preview,
            self.matched_image_roi(
                result.frame,
                self.roi,
                self.image_roi,
                result.lines,
                matched,
                self.last_preview.height,
            ),
        )

    @staticmethod
    def matched_image_roi(ocr_frame, monitor_roi, image_roi, lines, matched, preview_height=None):
        if not lines or not matched.line_indices or ocr_frame.height <= 0:
            return image_roi
        selected = [
            lines[index]
            for index in matched.line_indices
            if 0 <= index < len(lines) and lines[index].height > 0
        ]
        if not selected:
            return image_roi
        top = max(0, min(line.y for line in selected))
        bottom = min(ocr_frame.height, max(line.y + line.height for line in selected))
        if bottom <= top:
            return image_roi
        height = bottom - top
        padding = max(4, height * 0.35)
        top = max(0, top - padding)
        bottom = min(ocr_frame.height, bottom + padding)
        y = monitor_roi[1] + (top / ocr_frame.height) * monitor_roi[3]
        h = ((bottom - top) / ocr_frame.height) * monitor_roi[3]
        if preview_height:
            minimum = min(1, 16 / preview_height)
            if h < minimum:
                center = y + h / 2
                h = minimum
                y = center - h / 2
        h = min(1, h)
        y = max(0, min(1 - h, y))
        if h <= 0:
            return image_roi
        return image_roi[0], y, image_roi[2], h

    async def test_send(self, task):
        if not self.messaging.online or not task.policy.recipients:
            raise ValueError("QQ 通道或对象尚未就绪")
        if task.session_id != self.session or task.monitor_id != getattr(self.queue, "monitor_id", ""):
            raise ValueError("预览已过期，请重新试算")
        task = replace(task, text="【测试】" + task.text if task.text else "", created_at=time.monotonic())
        if not self.queue.accept(task):
            raise ValueError("发送队列已满")

    async def shutdown(self):
        await self.stop()
        if self.ocr_task:
            self.ocr_task.cancel()
            await asyncio.gather(self.ocr_task, return_exceptions=True)
        if hasattr(self.ocr_worker, "shutdown"):
            await self.ocr_worker.shutdown()
        await self.close_capture()
        self.capture_executor.shutdown(wait=False)
