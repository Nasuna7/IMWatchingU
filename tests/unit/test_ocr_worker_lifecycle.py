import pytest

from screen_qq_ocr.runtime.workers import OcrWorker


@pytest.mark.asyncio
async def test_availability_is_requested_from_worker_process(monkeypatch):
    worker = OcrWorker()
    captured = {}

    async def request(payload, timeout, timeout_message):
        captured["payload"] = payload
        captured["timeout"] = timeout
        captured["timeout_message"] = timeout_message

    monkeypatch.setattr(worker, "request", request)

    await worker.availability({"engine": "windows", "max_edge": 1920})

    assert captured["payload"] == ("availability", {"engine": "windows", "max_edge": 1920})
    assert captured["timeout"] == 8
    assert "可用性" in captured["timeout_message"]
