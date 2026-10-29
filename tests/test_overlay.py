import pytest

from dayanpi.focus.overlay import MAX_BOXES_PER_KIND, FrameSize, build_overlay
from dayanpi.vision.detector import Box, Detection, FrameReading

SIZE = FrameSize(width=640, height=480)


def make_reading(people=(), phones=(), food=(), drinks=()) -> FrameReading:
    reading = FrameReading(people=list(people), phones=list(phones), faces=[], elapsed_ms=200.0, food=list(food), drinks=list(drinks))
    return reading


def test_boxes_are_fractions_of_the_frame():
    reading = make_reading(people=[Detection("person", 0.91, Box(64, 48, 320, 432))])
    overlay = build_overlay(reading, SIZE, at=1000.0)
    box = overlay["boxes"][0]
    assert (box["kind"], box["label"], box["confidence"]) == ("person", "person", 0.91)
    assert (box["x"], box["y"], box["width"], box["height"]) == pytest.approx((0.1, 0.1, 0.4, 0.8))
    assert (overlay["frame_width"], overlay["frame_height"], overlay["at"]) == (640, 480, 1000.0)


def test_boxes_that_spill_off_the_frame_are_clamped():
    reading = make_reading(phones=[Detection("phone", 0.6, Box(-20, 400, 700, 520))])
    box = build_overlay(reading, SIZE, at=0.0)["boxes"][0]
    assert (box["x"], box["width"]) == (0.0, 1.0)
    assert box["y"] + box["height"] == pytest.approx(1.0)


def test_only_what_the_focus_rules_count_gets_a_box():
    reading = make_reading(
        people=[Detection("person", 0.4, Box(0, 0, 10, 10))],
        phones=[Detection("phone", 0.2, Box(0, 0, 10, 10)), Detection("phone", 0.3, Box(0, 0, 10, 10))],
        food=[Detection("apple", 0.35, Box(0, 0, 10, 10))],
        drinks=[Detection("cup", 0.29, Box(0, 0, 10, 10))],
    )
    boxes = build_overlay(reading, SIZE, at=0.0)["boxes"]
    assert [(box["kind"], box["label"]) for box in boxes] == [("phone", "phone"), ("food", "apple")]


def test_each_kind_keeps_its_strongest_few():
    people = [Detection("person", confidence, Box(0, 0, 10, 10)) for confidence in (0.6, 0.95, 0.7, 0.8, 0.55)]
    boxes = build_overlay(make_reading(people=people), SIZE, at=0.0)["boxes"]
    assert len(boxes) == MAX_BOXES_PER_KIND
    assert [box["confidence"] for box in boxes] == [0.95, 0.8, 0.7]


def test_an_empty_desk_has_no_boxes():
    overlay = build_overlay(make_reading(), SIZE, at=5.0)
    assert overlay["boxes"] == []
    assert overlay["frame_width"] == 640
