"""Turns the two cameras' readings into the one reading the FocusTracker works from."""

from dayanpi.vision.detector import FrameReading


def merge_readings(front: FrameReading | None, side: FrameReading | None) -> FrameReading | None:
    """People, phones, food and drinks from both cameras; faces and poses from the front only.

    Face turn and tilt and the gestures assume the straight-on view. With no side reading,
    front comes back untouched, so one camera behaves as if this function weren't here.

    The merged boxes mix two cameras' coordinates, so only their confidences mean anything.
    Never draw them: the overlays are built from each camera's own reading.
    """
    merged = front
    if side is not None:
        base = front if front is not None else FrameReading(people=[], phones=[], faces=[], elapsed_ms=0.0)
        merged = FrameReading(
            people=base.people + side.people,
            phones=base.phones + side.phones,
            faces=base.faces,
            elapsed_ms=base.elapsed_ms + side.elapsed_ms,
            food=base.food + side.food,
            drinks=base.drinks + side.drinks,
            poses=base.poses,
            side=side,
        )
    return merged
