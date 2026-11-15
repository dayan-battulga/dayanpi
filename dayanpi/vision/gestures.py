"""Turns arm positions from the pose model into gestures for the LED sign.

They're holds, not swipes: the detector only checks about once a second, which is
too slow to catch a swipe.

- next_page: right wrist up, left hand down, held 1 s.
- previous_page: left wrist up, right hand down, held 1 s.
- toggle_block: both wrists up, held 2 s. Starts or stops a work block.

"Up" means the wrist is above its own shoulder by at least RAISE_MARGIN shoulder widths.
Right and left are the person's own sides, not the image's.
"""

import math
from dataclasses import dataclass

from dayanpi.vision.pose import LEFT_SHOULDER, LEFT_WRIST, RIGHT_SHOULDER, RIGHT_WRIST, Keypoint, PoseDetection

NEXT_PAGE = "next_page"
PREVIOUS_PAGE = "previous_page"
TOGGLE_BLOCK = "toggle_block"

HOLD_SECONDS = {NEXT_PAGE: 1.0, PREVIOUS_PAGE: 1.0, TOGGLE_BLOCK: 2.0}
RAISE_MARGIN = 0.3
MIN_KEYPOINT_CONFIDENCE = 0.5
# YOLO only learns keypoint confidence on boxes that match a real person, so on a weak box it's noise.
MIN_PERSON_CONFIDENCE = 0.5
ALLOWED_MISSES = 1


@dataclass
class GestureHold:
    name: str
    started_at: float
    has_fired: bool = False
    misses: int = 0


def is_visible(keypoint: Keypoint) -> bool:
    visible = keypoint.confidence >= MIN_KEYPOINT_CONFIDENCE
    return visible


def is_raised(wrist: Keypoint, shoulder: Keypoint, margin: float) -> bool:
    """Image y grows downward, so a raised wrist has a smaller y than its shoulder."""
    raised = is_visible(wrist) and shoulder.y - wrist.y >= margin
    return raised


def read_gesture(pose: PoseDetection | None) -> str | None:
    """The gesture one check shows, or None for hands down, nobody there, or no clear shoulders.

    A wrist the model isn't sure about counts as down.
    """
    gesture = None
    if pose is not None and pose.confidence >= MIN_PERSON_CONFIDENCE:
        left_shoulder = pose.keypoints[LEFT_SHOULDER]
        right_shoulder = pose.keypoints[RIGHT_SHOULDER]
        if is_visible(left_shoulder) and is_visible(right_shoulder):
            shoulder_width = math.hypot(left_shoulder.x - right_shoulder.x, left_shoulder.y - right_shoulder.y)
            margin = RAISE_MARGIN * shoulder_width
            left_up = is_raised(pose.keypoints[LEFT_WRIST], left_shoulder, margin)
            right_up = is_raised(pose.keypoints[RIGHT_WRIST], right_shoulder, margin)
            if left_up and right_up:
                gesture = TOGGLE_BLOCK
            elif right_up:
                gesture = NEXT_PAGE
            elif left_up:
                gesture = PREVIOUS_PAGE
    return gesture


class GestureTracker:
    """Feed it one pose per check (the main person, or None) and it says when a gesture fires.

    - A hold starts on the first check that shows a gesture. It fires on the first check that
      still shows it once HOLD_SECONDS have passed since then, and each hold fires only once.
    - A hold survives one check that doesn't show it (no pose, shoulders not clear, a wrist
      that dropped out for a frame), and the clock keeps running through it. A second miss in a
      row ends the hold, and whatever that second check shows starts the next one.
    - Raising the second hand ends a one-hand hold that hasn't fired yet, right away, and
      starts the both-hands hold.
    - Once anything fires, nothing else can until the hands come down: two hands-down checks
      in a row, since one could be a glitch. Hands that stay up, in any shape, keep it waiting.
    """

    def __init__(self) -> None:
        self._hold: GestureHold | None = None

    def update(self, pose: PoseDetection | None, now: float) -> str | None:
        """Returns the gesture's name on the check where it fires, otherwise None.

        now is the caller's clock in seconds, like time.monotonic().
        """
        gesture = read_gesture(pose)
        hold = self._hold
        fired_gesture = None
        if hold is None:
            self._start_hold(gesture, now)
        elif gesture == hold.name:
            hold.misses = 0
            if not hold.has_fired and now - hold.started_at >= HOLD_SECONDS[hold.name]:
                hold.has_fired = True
                fired_gesture = hold.name
        elif gesture == TOGGLE_BLOCK and not hold.has_fired:
            self._start_hold(gesture, now)
        else:
            self._count_miss(gesture, now)
        return fired_gesture

    def _start_hold(self, gesture: str | None, now: float) -> None:
        self._hold = None if gesture is None else GestureHold(name=gesture, started_at=now)

    def _count_miss(self, gesture: str | None, now: float) -> None:
        hold = self._hold
        if hold.has_fired and gesture is not None:
            hold.misses = 0
        else:
            hold.misses += 1
        if hold.misses > ALLOWED_MISSES:
            self._start_hold(gesture, now)
