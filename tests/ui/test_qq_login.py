from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from screen_qq_ocr.infrastructure.napcat.management import Management
from screen_qq_ocr.ui.pages.qq_page import QQPage
from screen_qq_ocr.ui.presenters import Presenter


def test_duplicate_login_displays_real_cause_and_clears_qr(qtbot):
    page = QQPage()
    qtbot.addWidget(page)
    presenter = SimpleNamespace(window=SimpleNamespace(qq=page))
    Presenter.show_login(presenter, {"qrcodeurl": "https://example.com/qr"})
    assert not page.qr.pixmap().isNull()
    Presenter.show_login(presenter, {"loginError": "当前账号已登录,无法重复登录"})
    assert "其他 QQ / NapCat" in page.login_status.text()
    assert "过期" not in page.login_status.text()
    assert page.qr.pixmap().isNull()
    Presenter.show_login(presenter, {"refreshing": True})
    assert not page.refresh_qr.isEnabled()
    Presenter.show_login(presenter, {})
    assert page.refresh_qr.isEnabled()
    assert "等待 NapCat" in page.login_status.text()


@pytest.mark.asyncio
async def test_refresh_waits_for_changed_qr():
    management = Management()
    management.call = AsyncMock(
        side_effect=[{"qrcodeurl": "old"}, {}, {"qrcodeurl": "old"}, {"qrcodeurl": "new"}]
    )
    state = await management.refresh_qr(interval=0)
    assert state["qrcodeurl"] == "new"
    assert management.call.await_count == 4


@pytest.mark.asyncio
async def test_refresh_timeout_does_not_redisplay_old_qr_on_next_poll():
    management = Management()
    management.call = AsyncMock(
        side_effect=[{"qrcodeurl": "old"}, {}, {"qrcodeurl": "old"}, {"qrcodeurl": "old"}]
    )
    state = await management.refresh_qr(timeout=0)
    assert not state["qrcodeurl"] and state["loginError"]
    assert not (await management.login_state())["qrcodeurl"]


@pytest.mark.asyncio
async def test_refresh_does_not_request_qr_when_logged_in():
    management = Management()
    management.call = AsyncMock(return_value={"isLogin": True})
    assert (await management.refresh_qr())["isLogin"]
    management.call.assert_awaited_once_with("api/QQLogin/CheckLoginStatus")


@pytest.mark.asyncio
async def test_refresh_preserves_real_error():
    management = Management()
    management.call = AsyncMock(side_effect=[{}, {}, {"loginError": "无法重复登录", "qrcodeurl": "old"}])
    state = await management.refresh_qr()
    assert state == {"loginError": "无法重复登录", "qrcodeurl": ""}
