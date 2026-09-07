from PySide6.QtCore import Qt

from screen_qq_ocr.domain.models import KeywordRule, QQTarget, SendOverrides
from screen_qq_ocr.infrastructure.persistence.settings import Settings
from screen_qq_ocr.ui.main_window import MainWindow
from screen_qq_ocr.ui.widgets.policy_editor import PolicyEditor


def test_navigation_rule_editor_and_inheritance(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.json"))
    qtbot.addWidget(window)
    window.show()
    assert window.stack.count() == 6
    window.navigation.setCurrentRow(1)
    rule = KeywordRule("测试", min_count=5)
    window.keywords.set_rules([rule])
    window.keywords.edit(0, 0)
    assert window.keywords.keyword.text() == "测试"
    assert window.keywords.count.value() == 5
    assert window.keywords.policy.value() == SendOverrides()
    with qtbot.waitSignal(window.keywords.save) as signal:
        window.keywords.count.setValue(6)
        window.keywords.submit()
    saved = signal.args[0]
    assert saved.id == rule.id and saved.revision == 2 and saved.min_count == 6
    window.tray.hide()
    window.hide()


def test_keyword_target_count_can_be_changed_directly_in_table(qtbot):
    from screen_qq_ocr.ui.pages.keywords_page import KeywordsPage

    page = KeywordsPage()
    qtbot.addWidget(page)
    rule = KeywordRule("数量", min_count=2)
    page.set_rules([rule])
    with qtbot.waitSignal(page.save) as signal:
        page.table.cellWidget(0, 2).setValue(5)
    assert signal.args[0].min_count == 5 and signal.args[0].id == rule.id


def test_policy_editor_selects_multiple_targets(qtbot):
    first = QQTarget("123456", "private", "789012", "first")
    second = QQTarget("123456", "group", "345678", "second")
    editor = PolicyEditor()
    qtbot.addWidget(editor)
    editor.set_targets([first, second])
    for index in range(editor.target.count()):
        editor.target.item(index).setCheckState(Qt.CheckState.Checked)
    policy = editor.value()
    assert policy.target == first
    assert policy.targets == (first, second)
