from pathlib import Path

from PySide6.QtCore import QByteArray, QLibraryInfo, Qt, QTranslator
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleFactory

LIGHT = dict(
    bg="#F4F4F3",
    surface="#FDFDFC",
    soft="#F0F0EE",
    text="#292A2C",
    muted="#747572",
    line="#E3E4E0",
    primary="#2B2D2F",
    on_primary="#FAFBF8",
    orange="#B66127",
    tint="#FBF0E5",
    green="#347C60",
    green_bg="#EDF4EE",
    danger="#B33B3B",
    glow="#F1D2B3",
)
DARK = dict(
    bg="#171819",
    surface="#242526",
    soft="#2E2F30",
    text="#EEEFED",
    muted="#A9AAA7",
    line="#393A3A",
    primary="#E8E9E5",
    on_primary="#222425",
    orange="#F0A264",
    tint="#3A2E24",
    green="#8CC7A7",
    green_bg="#28392F",
    danger="#EF9898",
    glow="#653C23",
)
PATHS = {
    "app": '<path d="M12 4c5 0 9 8 9 8s-4 8-9 8-9-8-9-8 4-8 9-8Z"/><circle cx="12" cy="12" r="3.2"/><path d="M16.5 6.5 19 4m-2.5 13.5L19 20M7.5 6.5 5 4m2.5 13.5L5 20"/>',
    "monitor": '<rect x="3" y="4" width="18" height="13" rx="2.4"/><path d="M7 9h4l2 4 2-7 2 3h2M8 21h8m-4-4v4"/>',
    "scan": '<path d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m8 0h3a2 2 0 0 0 2-2v-3"/><circle cx="12" cy="12" r="3"/><path d="M7 12h2m6 0h2"/>',
    "rules": '<path d="M6 5h15M6 12h15M6 19h15"/><circle cx="3.5" cy="5" r="1"/><path d="m2.5 12 .7.7 1.4-1.6m-2.1 7.9 2-2m0 2-2-2"/>',
    "chat": '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7A2.5 2.5 0 0 1 17.5 15H10l-5 4v-4.5A2.5 2.5 0 0 1 4 12.5Z"/><path d="M8 8h8M8 11h5"/>',
    "send": '<path d="M21 3 10.5 20l-2-7-6.5-2L21 3Z"/><path d="m8.5 13 5-3.5"/>',
    "history": '<path d="M4 12a8 8 0 1 0 2.2-5.5M4 4v8h8"/><path d="M12 8v5l3 2"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2"/><circle cx="15" cy="17" r="2"/>',
    "close": '<path d="m6 6 12 12M6 18 18 6"/>',
    "minimize": '<path d="M5 12h14"/>',
    "maximize": '<rect x="5" y="5" width="14" height="14" rx="1"/>',
    "restore": '<path d="M8 4h12v12M4 8h12v12H4Z"/>',
    "down": '<path d="m7 10 5 5 5-5"/>',
    "up": '<path d="m7 14 5-5 5 5"/>',
    "left": '<path d="m14 7-5 5 5 5"/>',
    "right": '<path d="m10 7 5 5-5 5"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M3 7.5V5h6l2 2.5h10v11A2.5 2.5 0 0 1 18.5 21h-13A2.5 2.5 0 0 1 3 18.5Z"/><path d="M3 10h18"/>',
    "file": '<path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v5h4M9 13h6M9 17h4"/>',
    "alert": '<path d="m12 3 10 18H2L12 3Zm0 6v5m0 3v.1"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    "refresh": '<path d="M20 8a8 8 0 1 0 0 8m0-13v5h-5"/>',
    "crop": '<path d="M6 2v16h16M2 6h16v16"/>',
    "theme": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
}


def colors():
    return DARK if QApplication.instance().property("dark_theme") else LIGHT


def svg(name, color):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
        f'stroke-linejoin="round">{PATHS.get(name, PATHS["file"])}</svg>'
    )


def icon(name, color=None):
    renderer = QSvgRenderer(QByteArray(svg(name, color or colors()["text"]).encode()))
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class StudioStyle(QProxyStyle):
    def __init__(self):
        super().__init__(QStyleFactory.create("Fusion"))

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint in (QStyle.StyleHint.SH_ComboBox_Popup, QStyle.StyleHint.SH_UnderlineShortcut):
            return 0
        if hint == QStyle.StyleHint.SH_Menu_SubMenuPopupDelay:
            return 120
        return super().styleHint(hint, option, widget, returnData)

    def standardIcon(self, standardIcon, option=None, widget=None):
        name = standardIcon.name
        file_controls = {
            "SP_FileDialogToParent": "up",
            "SP_FileDialogNewFolder": "folder",
            "SP_FileDialogListView": "rules",
            "SP_FileDialogDetailedView": "settings",
        }
        if name in file_controls:
            return icon(file_controls[name])
        key = next(
            (
                key
                for term, key in (
                    ("Close", "close"),
                    ("Cancel", "close"),
                    ("Ok", "check"),
                    ("Apply", "check"),
                    ("Min", "minimize"),
                    ("Max", "maximize"),
                    ("Normal", "restore"),
                    ("Dir", "folder"),
                    ("Open", "folder"),
                    ("Back", "left"),
                    ("Forward", "right"),
                    ("Up", "up"),
                    ("Down", "down"),
                    ("Reload", "refresh"),
                    ("Computer", "monitor"),
                    ("Critical", "alert"),
                    ("Warning", "alert"),
                    ("Information", "alert"),
                )
                if term in name
            ),
            "file",
        )
        return icon(key)


def install(app, theme="light"):
    if not hasattr(app, "_zh_translator"):
        app._zh_translator = QTranslator(app)
        app._zh_translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        app.installTranslator(app._zh_translator)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    if not getattr(app, "_studio_style", None):
        app._studio_style = StudioStyle()
        app.setStyle(app._studio_style)
    dark = theme == "dark" or (theme == "system" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark)
    app.setProperty("dark_theme", dark)
    palette = QPalette()
    tokens = DARK if dark else LIGHT
    for role, key in (
        (QPalette.ColorRole.Window, "bg"),
        (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "surface"),
        (QPalette.ColorRole.AlternateBase, "soft"),
        (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.Button, "surface"),
        (QPalette.ColorRole.ButtonText, "text"),
        (QPalette.ColorRole.Highlight, "tint"),
        (QPalette.ColorRole.HighlightedText, "text"),
        (QPalette.ColorRole.ToolTipBase, "primary"),
        (QPalette.ColorRole.ToolTipText, "on_primary"),
        (QPalette.ColorRole.PlaceholderText, "muted"),
    ):
        palette.setColor(role, QColor(tokens[key]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(tokens["muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(tokens["muted"]))
    app.setPalette(palette)
    folder = Path(__file__).parent / "theme"
    text = (folder / "light.qss").read_text(encoding="utf-8")
    for key, value in tokens.items():
        text = text.replace("@" + key + "@", value)
    text = text.replace("@icons@", (folder / "icons" / ("dark" if dark else "light")).as_posix())
    app.setStyleSheet(text)
    if not hasattr(app, "_dialog_styler"):
        from screen_qq_ocr.ui.widgets.controls import DialogStyler

        app._dialog_styler = DialogStyler(app)
        app.installEventFilter(app._dialog_styler)
