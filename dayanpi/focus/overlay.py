"""What the latest focus check found, as boxes the dashboard draws over the camera feed.

Only numbers leave the Pi: a kind, a label, a confidence and a box measured in 0-1
fractions of the frame, so the page can lay them over the video at any size. The boxes
use the same cutoffs as the focus rules, so a box on screen means the tracker counted it.
Nothing here is logged.
"""

from dataclasses import dataclass

from dayanpi.focus.tracker import FOOD_MIN, PERSON_MIN, PHONE_MIN
from dayanpi.vision.detector import Detection, FrameReading

MAX_BOXES_PER_KIND = 3


@dataclass
class FrameSize:
    width: int
    height: int


def clamp_fraction(value: float) -> float:
    clamped = min(max(value, 0.0), 1.0)
    return clamped


def place_box(kind: str, detection: Detection, size: FrameSize) -> dict:
    """kind is person, phone, food or drink; x, y, width and height are fractions of the frame."""
    left = clamp_fraction(detection.box.x1 / size.width)
    top = clamp_fraction(detection.box.y1 / size.height)
    right = clamp_fraction(detection.box.x2 / size.width)
    bottom = clamp_fraction(detection.box.y2 / size.height)
    placed = {
        "kind": kind,
        "label": detection.label,
        "confidence": round(detection.confidence, 2),
        "x": round(left, 4),
        "y": round(top, 4),
        "width": round(right - left, 4),
        "height": round(bottom - top, 4),
    }
    return placed


def build_overlay(reading: FrameReading, size: FrameSize, at: float) -> dict:
    """The strongest few boxes of each kind that clear the focus rules' cutoffs."""
    groups = (
        ("person", reading.people, PERSON_MIN),
        ("phone", reading.phones, PHONE_MIN),
        ("food", reading.food, FOOD_MIN),
        ("drink", reading.drinks, FOOD_MIN),
    )
    boxes = []
    for kind, detections, cutoff in groups:
        counted = [detection for detection in detections if detection.confidence >= cutoff]
        strongest = sorted(counted, key=lambda detection: detection.confidence, reverse=True)[:MAX_BOXES_PER_KIND]
        boxes.extend(place_box(kind, detection, size) for detection in strongest)
    overlay = {"at": round(at, 3), "frame_width": size.width, "frame_height": size.height, "boxes": boxes}
    return overlay
