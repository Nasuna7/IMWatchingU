from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from screen_qq_ocr.ui.presenters import Presenter


@pytest.mark.parametrize("disconnect_fails", [False, True])
async def test_stop_reaps_napcat_even_if_disconnect_fails(disconnect_fails):
    shell = SimpleNamespace(stop=Mock(return_value=True))
    presenter = SimpleNamespace(
        shell_task=None,
        login_poll=None,
        auto_onebot=object(),
        shell=shell,
        app=SimpleNamespace(stop_all=AsyncMock()),
        qq_service=SimpleNamespace(disconnect=AsyncMock()),
        management=SimpleNamespace(close=AsyncMock()),
        window=SimpleNamespace(exiting=False),
        emit=Mock(),
    )
    if disconnect_fails:
        presenter.qq_service.disconnect.side_effect = RuntimeError("disconnect failed")
        with pytest.raises(RuntimeError):
            await Presenter.stop_napcat(presenter)
    else:
        await Presenter.stop_napcat(presenter)
        assert presenter.shell is not shell
        presenter.emit.assert_any_call("shell_status", "NapCat 已停止，账号连接已释放")
    shell.stop.assert_called_once_with(closing=True)
    assert presenter.auto_onebot is None
