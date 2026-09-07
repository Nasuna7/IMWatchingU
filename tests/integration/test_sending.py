import asyncio
import json
import time
from dataclasses import replace

from websockets.asyncio.server import serve

from screen_qq_ocr.application.sending import SendQueue
from screen_qq_ocr.domain.models import SendPolicy, SendReceipt, SendTask
from screen_qq_ocr.infrastructure.napcat.onebot import OneBot


class FakeMessaging:
    def __init__(self, statuses=("success", "success")):
        self.calls = []
        self.statuses = statuses
        self.on_send = lambda: None

    async def send_part(self, target, part, content):
        self.calls.append((target, part, content))
        self.on_send()
        return SendReceipt(part, self.statuses[len(self.calls) - 1], "123")


def task(frame, target, **kwargs):
    return SendTask(
        1, "rule", 1, SendPolicy(target=target, countdown=0, **kwargs), frame, "message", time.monotonic()
    )


async def test_partial_and_no_retry(frame, target):
    messenger = FakeMessaging(("success", "failed"))
    events = []
    queue = SendQueue(messenger, lambda f: b"png", lambda t, s, r: events.append(s), request_interval=0)
    item = task(frame, target, message_type="text_image")
    assert queue.accept(item)
    await queue.execute(queue.pending.popleft())
    assert events[-1] == "部分成功"
    assert [x[1] for x in messenger.calls] == ["text", "image"]
    assert not queue.accept(replace(item, task_id="second"))


async def test_stop_between_parts(frame, target):
    messenger = FakeMessaging()
    events = []
    queue = SendQueue(messenger, lambda f: b"png", lambda t, s, r: events.append(s), request_interval=0)
    item = task(frame, target, message_type="text_image")
    queue.current = item
    messenger.on_send = queue.cancel
    await queue.execute(item)
    assert len(messenger.calls) == 1 and events[-1] == "部分成功"


async def test_cancel_countdown(frame, target):
    messenger = FakeMessaging()
    queue = SendQueue(messenger, lambda f: b"png")
    item = task(frame, target)
    item = replace(item, policy=replace(item.policy, countdown=3))
    queue.current = item
    operation = asyncio.create_task(queue.execute(item))
    await asyncio.sleep(0.01)
    queue.cancel()
    await operation
    assert not messenger.calls


async def test_image_only_expiry_and_test_isolation(frame, target):
    messenger = FakeMessaging()
    queue = SendQueue(messenger, lambda f: b"png", request_interval=0)
    item = replace(task(frame, target, message_type="image"), is_test=True)
    assert queue.accept(item)
    await queue.execute(queue.pending.popleft())
    assert messenger.calls[0][1] == "image"
    assert not queue.cooldowns.accepted_at
    await queue.execute(replace(item, created_at=time.monotonic() - 61))
    assert len(messenger.calls) == 1


async def test_multi_target_task_sends_each_recipient(frame, target):
    other = replace(target, id="345678", display_name="second")
    messenger = FakeMessaging(("success", "success"))
    events = []
    queue = SendQueue(messenger, lambda f: b"png", lambda t, s, r: events.append(s), request_interval=0)
    item = SendTask(
        1,
        "rule",
        1,
        SendPolicy(targets=(target, other), countdown=0),
        frame,
        "message",
        time.monotonic(),
    )
    assert queue.accept(item)
    await queue.execute(queue.pending.popleft())
    assert [call[0] for call in messenger.calls] == [target, other]
    assert [call[1] for call in messenger.calls] == ["text", "text"]
    assert events[-1] == "成功"


async def test_fake_onebot_echo_late_duplicate_and_timeout(target):
    sends = []

    async def handler(socket):
        async for raw in socket:
            request = json.loads(raw)
            action = request["action"]
            if action == "get_login_info":
                data = {"user_id": target.account_id}
            elif action == "get_status":
                data = {"online": True}
            elif action == "get_friend_list":
                data = [{"user_id": target.id, "nickname": "test"}]
            elif action == "get_group_list":
                data = []
            else:
                sends.append(request)
                await asyncio.sleep(0.1)
                data = {"message_id": 123}
            response = json.dumps(dict(status="ok", retcode=0, data=data, echo=request["echo"]))
            await socket.send(response)
            await socket.send(response)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = OneBot(timeout=0.04)
        await client.open(f"ws://127.0.0.1:{port}", "synthetic-token")
        receipt = await client.send_part(target, "text", "[CQ:image,file=untrusted] plain text")
        assert receipt.status == "unknown"
        await asyncio.sleep(0.15)
        assert not client.pending and len(sends) == 1
        assert sends[0]["params"]["message"][0]["type"] == "text"
        await client.close()
