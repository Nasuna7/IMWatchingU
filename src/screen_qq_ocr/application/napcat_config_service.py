from dataclasses import asdict


class NapCatConfigService:
    """Compensating workflow. Runtime, credential and DB transactions are independent."""

    def __init__(self, journal, adapter, pause):
        self.journal, self.adapter, self.pause = journal, adapter, pause

    async def save_draft(self, config):
        config.validate()
        await self.journal.save("draft", asdict(config))

    async def apply(self, config, expected_revision):
        config.validate()
        actual_revision = await self.adapter.revision()
        if actual_revision != expected_revision:
            raise ValueError("发现外部配置变更，请查看差异后重新应用")
        await self.save_draft(config)
        await self.pause()
        snapshot = await self.adapter.snapshot()
        await self.journal.save("prepared", {"draft": asdict(config), "backup": snapshot})
        try:
            if config.mode == "managed":
                await self.adapter.write(config)
                await self.journal.save("written", {"draft": asdict(config), "backup": snapshot})
                await self.adapter.restart()
            await self.adapter.verify(config)
            await self.journal.save("verified", {"effective": asdict(config), "backup": snapshot})
        except Exception:
            try:
                await self.adapter.restore(snapshot)
                await self.journal.save("rolled_back", {"draft": asdict(config), "backup": snapshot})
            except Exception as rollback_error:
                await self.journal.save("recovery_failed", {"draft": asdict(config), "backup": snapshot})
                raise ValueError("配置应用失败且连接未恢复；保留草稿及备份") from rollback_error
            raise ValueError("配置未生效，已恢复旧配置并保留草稿") from None

    async def recover(self):
        stage, payload = await self.journal.latest()
        if stage in ("prepared", "written", "recovery_failed"):
            await self.pause()
            try:
                await self.adapter.restore(payload["backup"])
                await self.journal.save("rolled_back", payload)
            except Exception as error:
                await self.journal.save("recovery_failed", payload)
                raise ValueError("上次配置操作未完成，连接未恢复") from error
