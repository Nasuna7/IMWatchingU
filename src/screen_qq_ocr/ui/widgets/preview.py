from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget


class Preview(QWidget):
    roi_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 220)
        self.image = None
        self.roi = (0, 0, 1, 1)
        self.image_roi = (0, 0, 1, 1)
        self.drag = None
        self.editable = True
        self.setMouseTracking(True)
        self.rect = QRectF()
        self._frame_size = None
        self._frame_rgb = None
        self.revision = 0
        self.pending_revision = None
        self.accepted_roi = self.roi
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_frame(self, frame):
        self._frame_rgb = frame.rgb
        self.image = QImage(
            self._frame_rgb, frame.width, frame.height, frame.width * 3, QImage.Format.Format_RGB888
        )
        # Keep original pixels so small selections remain useful when magnified.
        if self.rect.isEmpty() or self._frame_size != self.image.size():
            self.cancel_drag()
            self.fit_roi()
        self._frame_size = self.image.size()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.contentsRect(), QColor("#27292B"))
        if self.image:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(self.rect, self.image)
        else:
            painter.setPen(QColor("#C7C7C2"))
            painter.drawText(
                self.contentsRect(),
                Qt.AlignmentFlag.AlignCenter,
                "选择显示器或窗口\n在全屏弹窗中圈定监控区和截图区",
            )
        if self.image:
            mask = QPainterPath()
            mask.addRect(QRectF(self.contentsRect()))
            mask.addRect(self.selection())
            painter.fillPath(mask, QColor(0, 0, 0, 85))
            self.draw_roi(painter, self.image_selection(), QColor("#F1E6D6"))
            self.draw_roi(painter, self.selection(), QColor("#D99C6C"))
            painter.setBrush(QColor("white"))
            for point in self.handles():
                painter.drawRect(QRectF(point.x() - 4, point.y() - 4, 8, 8))

    def draw_roi(self, painter, rect, color):
        painter.setPen(QPen(color, 2))
        painter.drawRect(rect)

    def set_roi(self, roi):
        self.revision += 1
        self.pending_revision = None
        self.accepted_roi = tuple(roi)
        self.drag = None
        self.roi = tuple(roi)
        self.fit_roi()
        self.update()

    def set_image_roi(self, roi):
        self.image_roi = tuple(roi)
        self.update()

    def submit_roi(self, roi):
        self.revision += 1
        self.pending_revision = self.revision
        self.roi = tuple(roi)
        self.fit_roi()
        self.update()
        x, y, w, h = self.roi
        self.roi_selected.emit((x, y, x + w, y + h))

    def finish_roi(self, revision, roi):
        if revision != self.pending_revision:
            return
        self.pending_revision = None
        self.accepted_roi = tuple(roi)
        # An acknowledgement must not interrupt a gesture already in progress.
        if not self.drag:
            self.roi = self.accepted_roi
            self.fit_roi()
            self.update()

    def fit_roi(self):
        """Center the accepted selection with editing room, capped at 8x overview."""
        if not self.image:
            self.rect = QRectF()
            return
        x, y, w, h = self.roi
        if w <= 0 or h <= 0:
            return
        iw, ih = self.image.width(), self.image.height()
        overview = min(self.width() / iw, self.height() / ih)
        scale = (
            overview
            if self.roi == (0, 0, 1, 1)
            else min(self.width() * 0.78 / (iw * w), self.height() * 0.78 / (ih * h), overview * 8)
        )
        width, height = iw * scale, ih * scale
        self.rect = QRectF(
            self.width() / 2 - (x + w / 2) * width, self.height() / 2 - (y + h / 2) * height, width, height
        )

    def cancel_drag(self):
        if self.drag:
            self.roi = self.drag[2] if self.pending_revision is not None else self.accepted_roi
            self.drag = None
            self.fit_roi()
            self.update()

    def resizeEvent(self, event):
        self.cancel_drag()
        self.fit_roi()
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.drag:
            self.cancel_drag()
            event.accept()
        else:
            super().keyPressEvent(event)

    def selection(self):
        return self.roi_rect(self.roi)

    def image_selection(self):
        return self.roi_rect(self.image_roi)

    def roi_rect(self, roi):
        x, y, w, h = roi
        return QRectF(
            self.rect.x() + x * self.rect.width(),
            self.rect.y() + y * self.rect.height(),
            w * self.rect.width(),
            h * self.rect.height(),
        )

    def handles(self):
        r = self.selection()
        return [
            r.topLeft(),
            QPointF(r.center().x(), r.top()),
            r.topRight(),
            QPointF(r.right(), r.center().y()),
            r.bottomRight(),
            QPointF(r.center().x(), r.bottom()),
            r.bottomLeft(),
            QPointF(r.left(), r.center().y()),
        ]

    def hit(self, point):
        for i, handle in enumerate(self.handles()):
            if (handle - point).manhattanLength() <= 12:
                return i
        if self.roi != (0, 0, 1, 1) and self.selection().contains(point):
            return "move"
        return "new"

    def normalized(self, point, rect=None):
        rect = self.rect if rect is None else rect
        return QPointF(
            min(1, max(0, (point.x() - rect.x()) / rect.width())),
            min(1, max(0, (point.y() - rect.y()) / rect.height())),
        )

    def mousePressEvent(self, event):
        if (
            self.editable
            and event.button() == Qt.MouseButton.LeftButton
            and self.image
            and self.rect.contains(event.position())
        ):
            self.setFocus()
            self.drag = (self.hit(event.position()), event.position(), self.roi, QRectF(self.rect))

    def mouseMoveEvent(self, event):
        if not self.image or self.rect.isEmpty():
            return
        if not self.drag:
            hit = self.hit(event.position())
            cursors = [
                Qt.CursorShape.SizeFDiagCursor,
                Qt.CursorShape.SizeVerCursor,
                Qt.CursorShape.SizeBDiagCursor,
                Qt.CursorShape.SizeHorCursor,
            ] * 2
            self.setCursor(
                cursors[hit]
                if isinstance(hit, int)
                else Qt.CursorShape.SizeAllCursor
                if hit == "move"
                else Qt.CursorShape.CrossCursor
            )
            return
        mode, press, original, image_rect = self.drag
        start = self.normalized(press, image_rect)
        p = self.normalized(event.position(), image_rect)
        x, y, w, h = original
        right, bottom = x + w, y + h
        if mode == "move":
            self.roi = (
                max(0, min(1 - w, x - (event.position().x() - press.x()) / image_rect.width())),
                max(0, min(1 - h, y - (event.position().y() - press.y()) / image_rect.height())),
                w,
                h,
            )
            # Move the image with the pointer; the aperture stays fixed in widget coordinates.
            self.rect = image_rect.translated(
                (x - self.roi[0]) * image_rect.width(), (y - self.roi[1]) * image_rect.height()
            )
        else:
            if mode == "new":
                x, right = sorted((start.x(), p.x()))
                y, bottom = sorted((start.y(), p.y()))
            else:
                if mode in (0, 6, 7):
                    x = min(p.x(), right)
                if mode in (2, 3, 4):
                    right = max(p.x(), x)
                if mode in (0, 1, 2):
                    y = min(p.y(), bottom)
                if mode in (4, 5, 6):
                    bottom = max(p.y(), y)
            self.roi = (x, y, right - x, bottom - y)
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag and event.button() == Qt.MouseButton.LeftButton:
            self.mouseMoveEvent(event)
            original = self.drag[2]
            self.drag = None
            proposed = self.roi
            if proposed != original:
                self.submit_roi(proposed)
            else:
                if self.pending_revision is None:
                    self.roi = self.accepted_roi
                self.fit_roi()
            self.update()


class RoiPickerDialog(QDialog):
    def __init__(self, parent, frame, roi, image_roi, title):
        super().__init__(parent)
        from screen_qq_ocr.ui.widgets.controls import button, label

        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.addWidget(label(title, "section"))
        self.preview = Preview()
        self.preview.set_roi(roi)
        self.preview.set_image_roi(image_roi)
        self.preview.set_frame(frame)
        layout.addWidget(self.preview, 1)
        actions = QHBoxLayout()
        reset = button("重置全屏", glyph="crop")
        cancel = button("取消")
        accept = button("应用区域", True)
        reset.clicked.connect(lambda: self.preview.set_roi((0, 0, 1, 1)))
        cancel.clicked.connect(self.reject)
        accept.clicked.connect(self.accept)
        actions.addStretch()
        for widget in (reset, cancel, accept):
            actions.addWidget(widget)
        layout.addLayout(actions)

    @staticmethod
    def pick(parent, frame, roi, image_roi, title):
        dialog = RoiPickerDialog(parent, frame, roi, image_roi, title)
        dialog.showFullScreen()
        return dialog.preview.roi if dialog.exec() == QDialog.DialogCode.Accepted else None
