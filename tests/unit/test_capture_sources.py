

from screen_qq_ocr.infrastructure.capture.windows_capture import (
    CaptureSource,
    eve_character_name,
    eve_window_stable_id,
    source_identity,
    valid_window_process_name,
)


def test_eve_window_title_filter():
    assert valid_window_process_name("EVE - Regular Decending Semitone")
    assert valid_window_process_name("EVE - 7th life V")
    assert eve_character_name("EVE - 7th life V") == "7th life V"
    assert eve_window_stable_id("EVE - 7th life V") == "eve-character:7th life v"
    assert not valid_window_process_name("EVE启动器")
    assert not valid_window_process_name("exefile.exe")
    assert not valid_window_process_name("Everything.exe")


def test_capture_source_identity_defaults_to_id_and_accepts_stable_process_key():
    monitor = CaptureSource("monitor:1", "Monitor", "monitor", (0, 0, 100, 100))
    window = CaptureSource(
        "window:123",
        "EVE - Alpha",
        "window",
        (123, "EVE - Alpha", 456, "exefile.exe"),
        "eve-character:alpha",
    )

    assert source_identity(monitor) == "monitor:1"
    assert source_identity(window) == "eve-character:alpha"
