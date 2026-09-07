from dataclasses import replace

import pytest

from screen_qq_ocr.domain.cooldown import Cooldowns
from screen_qq_ocr.domain.flash import FlashDetector, classify, dominant
from screen_qq_ocr.domain.matching import match
from screen_qq_ocr.domain.models import KeywordRule, OcrLine, OcrResult, SendOverrides, SendPolicy
from screen_qq_ocr.domain.send_policy import TriggerTracker
from screen_qq_ocr.domain.templates import render, validate_template
from screen_qq_ocr.infrastructure.capture.coordinates import normalize_roi, pixel_box


@pytest.mark.parametrize(
    "text,keyword,threshold,count,hit",
    [
        ("Cerb " * 4, "Cerb", 5, 4, False),
        ("Cerb " * 5, "Cerb", 5, 5, True),
        ("aaaa", "aa", 2, 2, True),
        ("cerb", "Cerb", 1, 0, False),
        ("C\u3000e\nr\tb", " C erb ", 1, 1, True),
    ],
)
def test_literal_matching(text, keyword, threshold, count, hit):
    result = match(text, keyword, threshold)
    assert (result.count, result.hit) == (count, hit)


def test_cross_line_fallback(frame):
    text = "before\nCe\nrb\nafter"
    rule = KeywordRule("Cerb")
    result = OcrResult(frame, "fake", text, 0)
    assert render(SendPolicy(), rule, result, match(text, rule.keyword))[0] == text


def test_matching_reports_hit_line_indices():
    lines = (
        OcrLine("before", 0, 0, 10, 10),
        OcrLine("Cerb here", 0, 10, 10, 10),
        OcrLine("and Cerb again", 0, 20, 10, 10),
    )
    result = match("before\nCerb here\nand Cerb again", "Cerb", 2, lines)
    assert result.hit
    assert result.hit_line == "Cerb here"
    assert result.line_indices == (1, 2)


@pytest.mark.parametrize(
    "template", ["{unknown}", "{keyword.upper}", "{count:04}", "{count!r}", "{", "{}", "{ocr_text[0]}"]
)
def test_template_rejects_code(template):
    with pytest.raises(ValueError):
        validate_template(template)


def test_template_fixed_and_image(frame):
    rule = KeywordRule("Cerb")
    result = OcrResult(frame, "fake", "Cerb", 0)
    hit = match(result.text, rule.keyword)
    assert (
        render(SendPolicy(body_source="fixed", body="{not_a_variable}"), rule, result, hit)[0]
        == "{not_a_variable}"
    )
    assert (
        render(SendPolicy(body_source="template", body="{{提醒}} {keyword} {count}"), rule, result, hit)[0]
        == "{提醒} Cerb 1"
    )
    assert render(SendPolicy(message_type="image", body_source="template", body="{"), rule, result, hit) == (
        "",
        False,
    )
    assert (
        len(render(SendPolicy(body_source="ocr_text"), rule, replace(result, text="a" * 3000), hit)[0])
        == 2000
    )


def test_template_uses_keyword_alias(frame):
    rule = KeywordRule("Cerb", alias="提醒对象")
    result = OcrResult(frame, "fake", "Cerb", 0)
    hit = match(result.text, rule.keyword)
    assert (
        render(SendPolicy(body_source="template", body="{keyword} {count}"), rule, result, hit)[0]
        == "提醒对象 1"
    )


def test_field_inheritance(target):
    override = SendOverrides(cooldown=0)
    result = override.resolve(SendPolicy(cooldown=60, target=target, countdown=5))
    assert result.cooldown == 0 and result.target == target and result.countdown == 5
    assert override.resolve(replace(result, cooldown=30, countdown=0)).countdown == 0


def test_multi_target_policy_resolution(target):
    other = replace(target, id="345678", display_name="second")
    policy = SendPolicy(target=target)
    assert policy.recipients == (target,)
    result = SendOverrides(targets=(target, other)).resolve(policy)
    assert result.recipients == (target, other)


def test_cooldown_survives_release_and_zero_occupancy():
    tracker = Cooldowns()
    key = ("a", "private", "b", "r")
    assert tracker.acquire(key, 0, 60)
    assert not tracker.acquire(key, 61, 0)
    tracker.release(key)
    assert not tracker.acquire(key, 30, 60)
    assert tracker.acquire(key, 60, 60)
    assert tracker.acquire(("a", "group", "b", "other"), 60, 60)


def test_confirmation_and_round_occupancy():
    tracker = TriggerTracker()
    policy = SendPolicy(confirm_frames=2, repeat="once")
    key = ("a", "private", "b", "r")
    assert [tracker.observe(key, str(i), 1, value >= 5, policy) for i, value in enumerate([5, 4, 5, 5])] == [
        False,
        False,
        False,
        True,
    ]
    tracker.accepted(key)
    tracker.reset_continuity()
    assert not tracker.observe(key, "4", 2, True, policy)
    assert not tracker.observe(key, "5", 2, True, policy)
    assert not tracker.observe(key, "6", 2, False, policy)
    assert not tracker.observe(key, "7", 2, True, policy)
    assert tracker.observe(key, "8", 2, True, policy)
    assert not tracker.observe(key, "8", 2, True, policy)


def test_flash_five_points_missing_frames_and_cooldown():
    detector = FlashDetector(30)
    values = [detector.sample(color, i * 0.25) for i, color in enumerate(["红", "白", "红", "白", "红"])]
    assert values == [False] * 4 + [True]
    assert not detector.sample("白", 1.25)
    assert not detector.sample(None, 1.5)
    assert detector.changes == 0
    detector.sample("白", 2)
    detector.sample("红", 3)
    assert detector.changes == 0


@pytest.mark.parametrize(
    "rgb,result",
    [
        ((255, 0, 0), "红"),
        ((255, 150, 0), "橙"),
        ((255, 255, 255), "白"),
        ((0, 0, 0), "无"),
        ((128, 128, 128), "无"),
    ],
)
def test_color(rgb, result):
    assert classify(*rgb) == result
    assert dominant([rgb]) == result
    assert dominant([(255, 255, 255), (255, 0, 0)]) == "红"


def test_roi_reverse_drag_clamp_and_physical_pixels():
    roi = normalize_roi(200, 100, -20, -10, 400, 200)
    assert roi == (0, 0, 0.5, 0.5)
    assert pixel_box(roi, 800, 400) == (0, 0, 400, 200)
    with pytest.raises(ValueError):
        normalize_roi(0, 0, 15, 30, 100, 100)
