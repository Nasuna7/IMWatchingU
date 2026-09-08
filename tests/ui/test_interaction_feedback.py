from dataclasses import replace
from types import SimpleNamespace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QWidget

from screen_qq_ocr.domain.models import SendPolicy
from screen_qq_ocr.infrastructure.persistence.settings import Settings
from screen_qq_ocr.ui.main_window import MainWindow
from screen_qq_ocr.ui.pages.keywords_page import KeywordsPage
from screen_qq_ocr.ui.presenters import Presenter
from screen_qq_ocr.ui.widgets.policy_editor import PolicyEditor
from screen_qq_ocr.ui.widgets.preview import Preview
from screen_qq_ocr.ui.widgets.toasts import ToastStack


def test_apply_closes_only_after_success(qtbot):
    page = KeywordsPage()
    qtbot.addWidget(page)
    page.new()
    page.keyword.setText("已保存")
    with qtbot.waitSignal(page.save) as signal:
        page.submit()
    assert page.editor.isVisible()
    page.saved(signal.args[0])
    assert not page.editor.isVisible()


def test_loading_targets_replaces_previous_checks(qtbot, target):
    editor = PolicyEditor()
    qtbot.addWidget(editor)
    other = replace(target, account_id="654321")
    editor.set_account(target.account_id)
    editor.set_targets([target])
    editor.load(SendPolicy(target=target))
    assert editor.selected_targets() == (target,)
    editor.load(SendPolicy())
    assert not editor.selected_targets()
    editor.set_account(other.account_id)
    editor.set_targets([target, other])
    editor.load(SendPolicy(target=other))
    assert editor.target.count() == 1
    assert editor.selected_targets() == (other,)


def test_toasts_stack_bound_resize_and_expire(qtbot):
    window = QWidget()
    window.resize(600, 500)
    qtbot.addWidget(window)
    window.show()
    stack = ToastStack(window, duration=1000)
    for i in range(10):
        stack.show(f"任务 {i} 已启动")
    qtbot.waitUntil(lambda: not stack.retiring, timeout=800)
    assert len(stack.items) <= 3
    assert stack.items[-1].text().endswith("9 已启动")
    assert all(a.y() < b.y() for a, b in zip(stack.items, stack.items[1:]))
    window.resize(600, 350)
    qtbot.wait(250)
    assert sum(t.height() + 8 for t in stack.items) - 8 <= 140
    qtbot.waitUntil(lambda: not stack.items and not stack.retiring, timeout=2000)


def test_preview_hover_does_not_change_cursor_or_image(qtbot, frame):
    preview = Preview()
    preview.editable = False
    preview.set_frame(frame)
    qtbot.addWidget(preview)
    preview.show()
    before = preview.grab().toImage()
    qtbot.mouseMove(preview, QPoint(20, 20))
    assert preview.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert before == preview.grab().toImage()


def test_window_icon_is_identical_across_themes(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.json"))
    qtbot.addWidget(window)
    original = window.windowIcon().pixmap(48).toImage()
    window.toggle_theme()
    assert original == window.windowIcon().pixmap(48).toImage()
    settings = Settings(tmp_path / "dark.json")
    settings.values["appearance"]["theme"] = "dark"
    dark_window = MainWindow(settings)
    qtbot.addWidget(dark_window)
    assert original == dark_window.windowIcon().pixmap(48).toImage()
    for item in (window, dark_window):
        item.tray.hide()
        item.hide()


def test_success_and_error_events_show_toasts():
    calls = []
    window = SimpleNamespace(
        status_labels={},
        toasts=SimpleNamespace(show=lambda *a, **kw: calls.append((a, kw))),
        records=SimpleNamespace(appendPlainText=lambda _: None),
    )
    presenter = SimpleNamespace(window=window)
    Presenter.on_event(presenter, "toast", "监控已启动")
    Presenter.on_event(presenter, "error", "保存失败")
    assert calls == [(("监控已启动",), {"error": False}), (("保存失败",), {"error": True})]
