"""Turns hand shapes from the hand model into hand signs.

They're holds, not quick flicks: the detector only checks about once a second, which is
too slow to catch a flick.

- peace: a hand with the index and middle fingers open in a V and the ring and pinky closed, held 1 s.
"""

from dataclasses import dataclass

import numpy as np

from dayanpi.vision.hands import Hand

PEACE = "peace"

HOLD_SECONDS = {PEACE: 1.0}

WRIST_JOINT = 0
# Each finger's tip and middle joint, in the hand model's numbering. The thumb isn't read:
# peace ignores it and no other sign needs it yet.
FINGER_JOINTS = {"index": (8, 6), "middle": (12, 10), "ring": (16, 14), "pinky": (20, 18)}
INDEX_KNUCKLE = 5
MIDDLE_KNUCKLE = 9
# "v": the index and middle tips are at least this many times as far apart as their knuckles.
# Two fingers side by side (on a mouse, resting on a cheek) come out around 1.
V_SPREAD = 1.8
# One finger rule per sign: True = open, False = closed, a finger left out doesn't matter.
# A new sign is a line here, a hold time above, and a line in app.SIGN_ACTIONS.
HAND_SIGNS = {PEACE: {"index": True, "middle": True, "ring": False, "pinky": False, "v": True}}
ALLOWED_MISSES = 1


@dataclass
class GestureHold:
    name: str
    started_at: float
    has_fired: bool = False
    misses: int = 0


def read_hand_shape(joints: np.ndarray) -> dict[str, bool]:
    """Each finger, open when its tip is farther from the wrist than its middle joint, plus "v" (see V_SPREAD).

    joints is one Hand's (21, 3). Distances, not directions, so a tilted hand reads the same.
    """
    wrist = joints[WRIST_JOINT]
    shape = {
        finger: bool(np.linalg.norm(joints[tip] - wrist) > np.linalg.norm(joints[middle] - wrist))
        for finger, (tip, middle) in FINGER_JOINTS.items()
    }
    # x and y only: the depth is the model's noisiest number, and noise there could open a V.
    tip_gap = np.linalg.norm(joints[FINGER_JOINTS["index"][0], :2] - joints[FINGER_JOINTS["middle"][0], :2])
    knuckle_gap = np.linalg.norm(joints[INDEX_KNUCKLE, :2] - joints[MIDDLE_KNUCKLE, :2])
    shape["v"] = bool(tip_gap >= V_SPREAD * knuckle_gap)
    return shape


def read_sign(hands: list[Hand]) -> str | None:
    """The first sign any hand makes, or None. A hand makes a sign when every part of its rule matches."""
    sign = next(
        (name for hand in hands for name, rule in HAND_SIGNS.items() if rule.items() <= read_hand_shape(hand.joints).items()),
        None,
    )
    return sign


class GestureTracker:
    """Feed it the sign each check shows (read_sign(), or None) and it says when one fires.

    - A hold starts on the first check that shows a sign. It fires on the first check that
      still shows it once HOLD_SECONDS have passed since then, and each hold fires only once.
    - A hold survives one check that doesn't show it (no hand, a hand the model lost for a
      frame), and the clock keeps running through it. A second miss in a row ends the hold,
      and whatever that second check shows starts the next one.
    - Once a sign fires, nothing else can until the hands come down: two checks in a row
      without a sign, since one could be a glitch. A hand still making a sign keeps it waiting.
    """

    def __init__(self) -> None:
        self._hold: GestureHold | None = None

    def hold(self, gesture: str | None, now: float) -> str | None:
        """Returns the sign's name on the check where it fires, otherwise None.

        now is the caller's clock in seconds, like time.monotonic().
        """
        hold = self._hold
        fired_gesture = None
        if hold is None:
            self._start_hold(gesture, now)
        elif gesture == hold.name:
            hold.misses = 0
            if not hold.has_fired and now - hold.started_at >= HOLD_SECONDS[hold.name]:
                hold.has_fired = True
                fired_gesture = hold.name
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
