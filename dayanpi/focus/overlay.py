"""What the latest focus check found, as boxes the dashboard draws over the camera feed.

Only numbers leave the Pi: a kind, a label, a confidence and a box measured in 0-1
fractions of the frame, so the page can lay them over the video at any size. The boxes
use the same cutoffs as the focus rules, so a box on screen means the tracker counted it.
Nothing here is logged.
"""

from dataclasses import dataclass

from dayanpi.focus.tracker import PERSON_MIN, PHONE_MIN
from dayanpi.vision.detector import Detection, FrameReading
from dayanpi.vision.gestures import read_sign
from dayanpi.vision.hands import HAND_MIN_CONFIDENCE

MAX_BOXES_PER_KIND = 3


@dataclass
class FrameSize:
    width: int
    height: int


def clamp_fraction(value: float) -> float:
    clamped = min(max(value, 0.0), 1.0)
    return clamped


def place_box(kind: str, detection: Detection, size: FrameSize) -> dict:
    """kind is person or phone; x, y, width and height are fractions of the frame."""
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


def place_pose(poses: list, size: FrameSize) -> list[list[float]] | None:
    """The main person's 17 keypoints as [x, y, confidence], x and y in 0-1 fractions of the frame,
    or None when nobody clears the person cutoff (a weak box's keypoints are noise)."""
    main = max(poses, key=lambda pose: pose.confidence, default=None)
    points = None
    if main is not None and main.confidence >= PERSON_MIN:
        points = [
            [round(clamp_fraction(point.x / size.width), 4), round(clamp_fraction(point.y / size.height), 4), round(point.confidence, 2)]
            for point in main.keypoints
        ]
    return points


def build_overlay(reading: FrameReading, size: FrameSize, at: float, with_pose: bool = False) -> dict:
    """The strongest few boxes of each kind that clear the focus rules' cutoffs.

    A hand only gets a box while it makes a sign, labeled with the sign. with_pose (the pose
    model is loaded) adds "pose", the main person's keypoints or None; without it there's no
    "pose" at all, which is how the page knows to hide its Show pose button.
    """
    hands = [
        Detection(label=sign, confidence=hand.confidence, box=hand.find_box())
        for hand in reading.hands
        if (sign := read_sign([hand])) is not None
    ]
    groups = (
        ("person", reading.people, PERSON_MIN),
        ("phone", reading.phones, PHONE_MIN),
        ("hand", hands, HAND_MIN_CONFIDENCE),
    )
    boxes = []
    for kind, detections, cutoff in groups:
        counted = [detection for detection in detections if detection.confidence >= cutoff]
        strongest = sorted(counted, key=lambda detection: detection.confidence, reverse=True)[:MAX_BOXES_PER_KIND]
        boxes.extend(place_box(kind, detection, size) for detection in strongest)
    overlay = {"at": round(at, 3), "frame_width": size.width, "frame_height": size.height, "boxes": boxes}
    if with_pose:
        overlay["pose"] = place_pose(reading.poses, size)
    return overlay
