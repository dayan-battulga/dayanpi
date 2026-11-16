import numpy as np
import pytest

from dayanpi.vision import gestures
from dayanpi.vision.gestures import GestureTracker, read_hand_shape, read_sign
from dayanpi.vision.hands import Hand

SIGN_CHECK_S = 1.0  # the worker checks about once a second
FINGER_X = {"index": -24.0, "middle": -8.0, "ring": 8.0, "pinky": 24.0}
FINGER_BASES = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}


def make_hand(
    open_fingers: set[str], degrees: float = 0.0, scale: float = 1.0, thumb_out: bool = True, fanned: bool = True
) -> Hand:
    """A hand-made hand, wrist at the origin, fingers pointing up (image y grows downward).

    An open finger runs out, its tip fanned away from the hand's middle (or straight up when
    not fanned); a closed one curls back so its tip lands below its middle joint. Then the
    whole hand is turned, scaled and moved, since the rule should only care about distances.
    """
    joints = np.zeros((21, 3))
    thumb = [(-30, -20), (-50, -40), (-65, -55), (-80, -70)] if thumb_out else [(-25, -25), (-30, -50), (-15, -70), (0, -75)]
    joints[1:5, :2] = thumb
    for finger, base in FINGER_BASES.items():
        x = FINGER_X[finger]
        tip_x = x * 2.5 if fanned else x
        tip_side = [(x, -150), (tip_x, -175)] if finger in open_fingers else [(x, -100), (x, -70)]
        joints[base : base + 4, :2] = [(x, -80), (x, -120), *tip_side]
    turn = np.radians(degrees)
    rotation = np.array([[np.cos(turn), -np.sin(turn)], [np.sin(turn), np.cos(turn)]])
    joints[:, :2] = joints[:, :2] @ rotation.T * scale + (320, 300)
    joints[:, 2] *= scale
    hand = Hand(confidence=0.95, joints=joints)
    return hand


PEACE_HAND = make_hand({"index", "middle"})
OPEN_HAND = make_hand({"index", "middle", "ring", "pinky"})


def run_sign_checks(shown: list[list[Hand]]) -> list[str | None]:
    """One check a second from t=0, each with the hands that check saw."""
    tracker = GestureTracker()
    fired = [tracker.hold(read_sign(hands), index * SIGN_CHECK_S) for index, hands in enumerate(shown)]
    return fired


def test_a_finger_is_open_when_its_tip_is_farther_from_the_wrist_than_its_middle_joint():
    shape = read_hand_shape(make_hand({"index", "ring"}).joints)
    assert {"index": True, "middle": False, "ring": True, "pinky": False}.items() <= shape.items()


def test_peace_needs_a_v_not_two_fingers_side_by_side():
    assert read_sign([make_hand({"index", "middle"}, fanned=False)]) is None, "like a hand on a mouse"
    assert read_hand_shape(PEACE_HAND.joints)["v"]


@pytest.mark.parametrize("degrees", [0, 35, 90, -60, 180])
@pytest.mark.parametrize("scale", [0.4, 1.0, 2.5])
def test_peace_reads_the_same_turned_and_at_any_size(degrees, scale):
    assert read_sign([make_hand({"index", "middle"}, degrees, scale)]) == "peace"


@pytest.mark.parametrize("thumb_out", [True, False])
def test_peace_ignores_the_thumb(thumb_out):
    assert read_sign([make_hand({"index", "middle"}, thumb_out=thumb_out)]) == "peace"


@pytest.mark.parametrize(
    "open_fingers",
    [set(), {"index"}, {"middle"}, {"index", "middle", "ring"}, {"index", "middle", "ring", "pinky"}, {"index", "pinky"}, {"index", "ring"}],
    ids=["fist", "pointing", "middle", "three", "open hand", "rock", "index and ring"],
)
def test_other_hand_shapes_are_not_peace(open_fingers):
    assert read_sign([make_hand(open_fingers)]) is None


def test_any_hand_can_make_the_sign():
    assert read_sign([OPEN_HAND, PEACE_HAND]) == "peace"
    assert read_sign([]) is None


def test_every_sign_has_a_hold_time():
    assert set(gestures.HAND_SIGNS) <= set(gestures.HOLD_SECONDS)


def test_peace_held_a_second_fires_once():
    assert run_sign_checks([[PEACE_HAND]] * 6) == [None, "peace", None, None, None, None]


def test_one_missed_check_does_not_break_a_sign():
    assert run_sign_checks([[PEACE_HAND], [], [PEACE_HAND]]) == [None, None, "peace"]
    assert run_sign_checks([[PEACE_HAND], [OPEN_HAND], [PEACE_HAND]]) == [None, None, "peace"]


def test_two_missed_checks_restart_the_hold():
    assert run_sign_checks([[PEACE_HAND], [], [], [PEACE_HAND], [PEACE_HAND]]) == [None, None, None, None, "peace"]


def test_the_hand_has_to_drop_before_peace_fires_again():
    one_drop = [[PEACE_HAND]] * 3 + [[]] + [[PEACE_HAND]] * 3
    assert run_sign_checks(one_drop).count("peace") == 1, "one empty check could be a glitch"
    dropped = [[PEACE_HAND]] * 3 + [[], [OPEN_HAND]] + [[PEACE_HAND]] * 2
    assert run_sign_checks(dropped) == [None, "peace", None, None, None, None, "peace"]


def test_a_sign_fires_once_its_hold_time_has_passed_and_not_before():
    tracker = GestureTracker()
    fired = [tracker.hold("peace", now) for now in (100.0, 100.4, 100.99, 101.0)]
    assert fired == [None, None, None, "peace"]


def test_a_sign_flickering_after_it_fired_is_not_a_release():
    flicker = [[PEACE_HAND]] * 2 + [[], [PEACE_HAND]] * 3
    assert run_sign_checks(flicker).count("peace") == 1
