from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt

from screen_qq_ocr.ui.widgets.preview import Preview


@pytest.fixture
def preview(qtbot, frame):
    widget = Preview()
    qtbot.addWidget(widget)
    widget.resize(400, 400)
    widget.set_frame(replace(frame, width=400, height=400, rgb=frame.rgb[:3] * 400 * 400))
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def commit_drag(qtbot, preview, start, end):
    with qtbot.waitSignal(preview.roi_selected) as signal:
        qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(preview, end)
        qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=end)
    x, y, right, bottom = signal.args[0]
    preview.set_roi((x, y, right - x, bottom - y))
    return preview.roi


def test_draw_centers_and_magnifies_selection(qtbot, preview):
    result = commit_drag(qtbot, preview, QPoint(100, 100), QPoint(200, 200))
    assert result == pytest.approx((0.25, 0.25, 0.25, 0.25))
    assert preview.selection().center() == QPointF(200, 200)
    assert preview.selection().width() == pytest.approx(312)
    assert preview.rect.width() > 400


def test_drag_moves_background_and_keeps_aperture_fixed(qtbot, preview):
    preview.set_roi((0.25, 0.25, 0.25, 0.25))
    aperture = preview.selection()
    background = preview.rect
    qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    qtbot.mouseMove(preview, QPoint(250, 230))
    assert preview.selection().x() == pytest.approx(aperture.x())
    assert preview.selection().y() == pytest.approx(aperture.y())
    assert preview.selection().size() == aperture.size()
    assert preview.rect.x() - background.x() == pytest.approx(50)
    assert preview.rect.y() - background.y() == pytest.approx(30)
    # A new live frame must not reset the camera while dragging.
    before = preview.rect
    preview.set_frame(type("Frame", (), dict(width=400, height=400, rgb=bytes(400 * 400 * 3)))())
    assert preview.rect == before
    with qtbot.waitSignal(preview.roi_selected) as signal:
        qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=QPoint(250, 230))
    x, y, right, bottom = signal.args[0]
    assert (x, y) == pytest.approx((0.25 - 50 / 1248, 0.25 - 30 / 1248))
    assert (right - x, bottom - y) == pytest.approx((0.25, 0.25))


def test_zoomed_handle_uses_source_coordinates(qtbot, preview):
    preview.set_roi((0.25, 0.25, 0.25, 0.25))
    result = commit_drag(qtbot, preview, QPoint(356, 356), QPoint(376, 376))
    assert result == pytest.approx((0.25, 0.25, 0.25 + 20 / 1248, 0.25 + 20 / 1248))
    assert preview.selection().center() == QPointF(200, 200)


def test_pan_clamps_at_source_edge_without_moving_aperture(qtbot, preview):
    preview.set_roi((0.01, 0.01, 0.25, 0.25))
    aperture = preview.selection()
    qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    qtbot.mouseMove(preview, QPoint(399, 399))
    assert preview.roi == pytest.approx((0, 0, 0.25, 0.25))
    assert preview.selection().x() == pytest.approx(aperture.x())
    assert preview.selection().y() == pytest.approx(aperture.y())
    qtbot.keyClick(preview, Qt.Key.Key_Escape)
    assert preview.roi == (0.01, 0.01, 0.25, 0.25)
    assert preview.drag is None


def test_reset_resize_and_task_switch_reframe(preview):
    preview.set_roi((0.1, 0.2, 0.02, 0.02))
    assert preview.rect.width() <= 400 * 8
    preview.resize(600, 300)
    assert preview.selection().center() == QPointF(300, 150)
    preview.set_roi((0.7, 0.6, 0.2, 0.3))
    assert preview.selection().center().x() == pytest.approx(300)
    assert preview.selection().center().y() == pytest.approx(150)
    preview.set_roi((0, 0, 1, 1))
    assert preview.rect.width() == pytest.approx(300)
    assert preview.rect.x() == pytest.approx(150)


def test_rejected_crop_keeps_accepted_roi_and_camera(qtbot, preview):
    preview.set_roi((0.25, 0.25, 0.25, 0.25))
    camera = preview.rect
    with qtbot.waitSignal(preview.roi_selected):
        qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(356, 356))
        qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    assert preview.pending_revision is not None
    preview.finish_roi(preview.pending_revision, preview.accepted_roi)
    assert preview.roi == (0.25, 0.25, 0.25, 0.25)
    assert preview.rect == camera


def test_same_size_source_switch_reframes_after_clearing_image(preview, frame):
    preview.set_roi((0.1, 0.1, 0.2, 0.2))
    preview.image = None
    preview.set_roi((0.6, 0.5, 0.3, 0.4))
    preview.set_frame(replace(frame, width=400, height=400, rgb=bytes(400 * 400 * 3)))
    assert preview.selection().center().x() == pytest.approx(200)
    assert preview.selection().center().y() == pytest.approx(200)


def test_landscape_letterboxing_and_original_detail(preview, frame):
    preview.set_frame(replace(frame, width=1920, height=1080, rgb=bytes(1920 * 1080 * 3)))
    assert preview.image.width() == 1920
    assert preview.rect.height() == pytest.approx(225)
    assert preview.normalized(QPointF(100, 87.5)) == QPointF(0.25, 0)
    preview.set_roi((0.4, 0.3, 0.1, 0.2))
    assert preview.selection().center() == QPointF(200, 200)
    assert preview.selection().width() / preview.selection().height() == pytest.approx(192 / 216)


def test_release_updates_before_backend_ack(qtbot, preview):
    with qtbot.waitSignal(preview.roi_selected):
        qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    assert preview.roi == (0.25, 0.25, 0.25, 0.25)
    assert preview.selection().center() == QPointF(200, 200)
    assert preview.selection().width() == pytest.approx(312)
    assert preview.pending_revision is not None


def test_stale_ack_and_task_switch_do_not_overwrite_latest_preview(preview):
    preview.submit_roi((0.1, 0.1, 0.2, 0.2))
    first = preview.pending_revision
    preview.submit_roi((0.3, 0.3, 0.2, 0.2))
    second = preview.pending_revision
    preview.finish_roi(first, (0.1, 0.1, 0.2, 0.2))
    assert preview.roi == (0.3, 0.3, 0.2, 0.2)
    preview.set_roi((0, 0, 1, 1))
    preview.finish_roi(second, (0.3, 0.3, 0.2, 0.2))
    assert preview.roi == (0, 0, 1, 1)


def test_ack_does_not_interrupt_next_drag(qtbot, preview):
    preview.submit_roi((0.25, 0.25, 0.25, 0.25))
    revision = preview.pending_revision
    qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    qtbot.mouseMove(preview, QPoint(240, 220))
    camera, roi = preview.rect, preview.roi
    preview.finish_roi(revision, (0.25, 0.25, 0.25, 0.25))
    assert preview.drag is not None
    assert preview.rect == camera and preview.roi == roi
    qtbot.keyClick(preview, Qt.Key.Key_Escape)
    assert preview.roi == (0.25, 0.25, 0.25, 0.25)


def test_failed_ack_during_unchanged_gesture_restores_backend_roi(qtbot, preview):
    preview.set_roi((0.25, 0.25, 0.25, 0.25))
    preview.submit_roi((0.3, 0.3, 0.25, 0.25))
    revision = preview.pending_revision
    qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    preview.finish_roi(revision, (0.25, 0.25, 0.25, 0.25))
    qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    assert preview.roi == preview.accepted_roi
