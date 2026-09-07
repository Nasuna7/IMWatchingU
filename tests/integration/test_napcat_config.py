from dataclasses import replace

import pytest

from screen_qq_ocr.application.napcat_config_service import NapCatConfigService
from screen_qq_ocr.domain.napcat_config import NapCatConfig
from screen_qq_ocr.infrastructure.napcat.runtime import safe_member


class Journal:
    def __init__(self):
        self.events = []

    async def save(self, stage, data):
        self.events.append((stage, data))

    async def latest(self):
        return self.events[-1]


class Adapter:
    def __init__(self, fail=""):
        self.calls = []
        self.fail = fail

    async def revision(self):
        return "revision-1"

    async def snapshot(self):
        return "backup-ref"

    async def write(self, config):
        self.calls.append("write")
        if self.fail == "write":
            raise OSError()

    async def restart(self):
        self.calls.append("restart")
        if self.fail == "restart":
            raise OSError()

    async def verify(self, config):
        self.calls.append("verify")
        if self.fail in ("verify", "restore"):
            raise OSError()

    async def restore(self, backup):
        self.calls.append("restore")
        if self.fail == "restore":
            raise OSError()


async def no_op():
    pass


@pytest.mark.parametrize("failure", ["write", "restart", "verify", "restore"])
async def test_apply_failure_preserves_draft_and_journal(failure):
    journal, adapter = Journal(), Adapter(failure)
    service = NapCatConfigService(journal, adapter, no_op)
    with pytest.raises(ValueError):
        await service.apply(NapCatConfig(mode="managed"), "revision-1")
    assert "restore" in adapter.calls
    assert journal.events[-1][0] == ("recovery_failed" if failure == "restore" else "rolled_back")
    assert journal.events[-1][1]["draft"]


async def test_attached_does_not_write_or_restart():
    journal, adapter = Journal(), Adapter()
    service = NapCatConfigService(journal, adapter, no_op)
    await service.apply(NapCatConfig(), "revision-1")
    assert adapter.calls == ["verify"]


async def test_conflict_does_not_pause_or_write():
    journal, adapter = Journal(), Adapter()
    service = NapCatConfigService(journal, adapter, no_op)
    with pytest.raises(ValueError, match="外部配置"):
        await service.apply(NapCatConfig(), "stale")
    assert not journal.events and not adapter.calls


@pytest.mark.parametrize("name", ["../a", "..\\a", "/a", "C:/a", "file:stream", "a/CON.txt"])
def test_zip_traversal_rejected(name):
    with pytest.raises(ValueError):
        safe_member(name)


def test_config_validation():
    config = NapCatConfig()
    with pytest.raises(ValueError):
        replace(config, management_port=3001).validate()
    with pytest.raises(ValueError):
        replace(config, heartbeat=2).validate()
