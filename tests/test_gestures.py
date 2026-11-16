from dataclasses import replace

import numpy as np
import pytest

from dayanpi.vision import gestures
from dayanpi.vision.detector import Box
from dayanpi.vision.gestures import GestureTracker, read_gesture, read_open_fingers, read_sign
from dayanpi.vision.hands import Hand
from dayanpi.vision.pose import KEYPOINT_NAMES, LEFT_SHOULDER, LEFT_WRIST, RIGHT_SHOULDER, RIGHT_WRIST, Keypoint, PoseDetection

CHECK_INTERVAL_S = 0.5
SHOULDER_Y = 300.0
SHOULDER_WIDTH = 160.0
# Facing the camera, the person's right shoulder is on the image's left.
RIGHT_SHOULDER_X = 240.0
LEFT_SHOULDER_X = RIGHT_SHOULDER_X + SHOULDER_WIDTH
RAISED_Y = 180.0
LOWERED_Y = 420.0


def make_pose(left_up: bool = False, right_up: bool = False, person_confidence: float = 0.9) -> PoseDetection:
    keypoints = [Keypoint(x=0.0, y=0.0, confidence=0.0) for _ in KEYPOINT_NAMES]
    keypoints[RIGHT_SHOULDER] = Keypoint(x=RIGHT_SHOULDER_X, y=SHOULDER_Y, confidence=0.9)
    keypoints[LEFT_SHOULDER] = Keypoint(x=LEFT_SHOULDER_X, y=SHOULDER_Y, confidence=0.9)
    keypoints[RIGHT_WRIST] = Keypoint(x=RIGHT_SHOULDER_X, y=RAISED_Y if right_up else LOWERED_Y, confidence=0.9)
    keypoints[LEFT_WRIST] = Keypoint(x=LEFT_SHOULDER_X, y=RAISED_Y if left_up else LOWERED_Y, confidence=0.9)
    pose = PoseDetection(confidence=person_confidence, box=Box(x1=150, y1=100, x2=490, y2=480), keypoints=keypoints)
    return pose


def change_keypoint(pose: PoseDetection, index: int, **changes: float) -> PoseDetection:
    keypoints = list(pose.keypoints)
    keypoints[index] = replace(keypoints[index], **changes)
    changed = replace(pose, keypoints=keypoints)
    return changed


def run_checks(poses: list[PoseDetection | None]) -> list[str | None]:
    """Feeds a fresh tracker one pose per check, CHECK_INTERVAL_S apart from t=0, and lists what fired."""
    tracker = GestureTracker()
    fired = [tracker.update(pose, index * CHECK_INTERVAL_S) for index, pose in enumerate(poses)]
    return fired


RIGHT_UP = make_pose(right_up=True)
LEFT_UP = make_pose(left_up=True)
BOTH_UP = make_pose(left_up=True, right_up=True)
HANDS_DOWN = make_pose()


def test_right_hand_held_a_second_flips_to_the_next_page():
    assert run_checks([RIGHT_UP] * 3) == [None, None, "next_page"]


def test_left_hand_held_a_second_goes_back_a_page():
    assert run_checks([LEFT_UP] * 3) == [None, None, "previous_page"]


def test_both_hands_held_two_seconds_toggle_the_block():
    assert run_checks([BOTH_UP] * 5) == [None, None, None, None, "toggle_block"]


def test_a_gesture_fires_once_its_hold_time_has_passed_and_not_before():
    tracker = GestureTracker()
    fired = [tracker.update(RIGHT_UP, now) for now in (100.0, 100.4, 100.99, 101.0)]
    assert fired == [None, None, None, "next_page"]


def test_each_hold_fires_only_once():
    assert run_checks([RIGHT_UP] * 10).count("next_page") == 1


def test_hands_must_come_down_before_the_same_gesture_fires_again():
    fired = run_checks([RIGHT_UP] * 3 + [HANDS_DOWN] * 2 + [RIGHT_UP] * 3)
    assert fired == [None, None, "next_page", None, None, None, None, "next_page"]


def test_one_hands_down_check_is_not_a_release():
    fired = run_checks([RIGHT_UP] * 3 + [HANDS_DOWN] + [RIGHT_UP] * 6)
    assert fired.count("next_page") == 1


def test_nothing_else_fires_until_the_hands_come_down():
    fired = run_checks([RIGHT_UP] * 3 + [BOTH_UP] * 6 + [HANDS_DOWN] * 2 + [BOTH_UP] * 5)
    assert [gesture for gesture in fired if gesture] == ["next_page", "toggle_block"]
    assert fired[-1] == "toggle_block"


def test_raising_the_second_hand_cancels_a_pending_page_flip():
    fired = run_checks([RIGHT_UP] * 2 + [BOTH_UP] * 5)
    assert fired == [None, None, None, None, None, None, "toggle_block"]


def test_one_odd_check_does_not_break_a_both_hands_hold():
    fired = run_checks([BOTH_UP, BOTH_UP, RIGHT_UP, BOTH_UP, BOTH_UP])
    assert fired == [None, None, None, None, "toggle_block"]


def test_dropping_one_hand_for_good_turns_a_pending_toggle_into_a_page_flip():
    fired = run_checks([BOTH_UP] * 2 + [RIGHT_UP] * 4)
    assert fired == [None, None, None, None, None, "next_page"]


def test_one_missed_check_mid_hold_is_tolerated():
    no_shoulders = change_keypoint(RIGHT_UP, LEFT_SHOULDER, confidence=0.0)
    assert run_checks([RIGHT_UP, None, RIGHT_UP]) == [None, None, "next_page"]
    assert run_checks([RIGHT_UP, no_shoulders, RIGHT_UP]) == [None, None, "next_page"]


def test_two_missed_checks_in_a_row_restart_the_hold():
    fired = run_checks([RIGHT_UP, None, None, RIGHT_UP, RIGHT_UP, RIGHT_UP])
    assert fired == [None, None, None, None, None, "next_page"]


def test_misses_only_add_up_when_back_to_back():
    flicker_after_firing = [RIGHT_UP] * 3 + [HANDS_DOWN, RIGHT_UP] * 3 + [RIGHT_UP] * 2
    assert run_checks([BOTH_UP, None, BOTH_UP, None, BOTH_UP]) == [None, None, None, None, "toggle_block"]
    assert run_checks(flicker_after_firing).count("next_page") == 1


def test_low_confidence_wrists_count_as_down():
    blurry_right = change_keypoint(RIGHT_UP, RIGHT_WRIST, confidence=0.4)
    blurry_left = change_keypoint(BOTH_UP, LEFT_WRIST, confidence=0.4)
    assert run_checks([blurry_right] * 4) == [None] * 4
    assert run_checks([blurry_left] * 3) == [None, None, "next_page"]


@pytest.mark.parametrize("shoulder", [LEFT_SHOULDER, RIGHT_SHOULDER])
def test_no_gesture_without_both_shoulders(shoulder):
    hidden_shoulder = change_keypoint(BOTH_UP, shoulder, confidence=0.3)
    assert read_gesture(hidden_shoulder) is None
    assert run_checks([hidden_shoulder] * 6) == [None] * 6


def test_no_gesture_from_a_weak_person_or_nobody():
    assert read_gesture(make_pose(right_up=True, person_confidence=0.3)) is None
    assert read_gesture(None) is None


def test_a_wrist_must_clear_the_shoulder_by_the_margin():
    margin = gestures.RAISE_MARGIN * SHOULDER_WIDTH
    just_over = change_keypoint(HANDS_DOWN, RIGHT_WRIST, y=SHOULDER_Y - margin - 1)
    just_under = change_keypoint(HANDS_DOWN, RIGHT_WRIST, y=SHOULDER_Y - margin + 1)
    assert read_gesture(just_over) == "next_page"
    assert read_gesture(just_under) is None



# ----- hand signs -----

SIGN_CHECK_S = 1.0  # the worker checks about once a second
FINGER_X = {"index": -24.0, "middle": -8.0, "ring": 8.0, "pinky": 24.0}
FINGER_BASES = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}


def make_hand(open_fingers: set[str], degrees: float = 0.0, scale: float = 1.0, thumb_out: bool = True) -> Hand:
    """A hand-made hand, wrist at the origin, fingers pointing up (image y grows downward).

    An open finger runs straight out; a closed one curls back so its tip lands below its
    middle joint. Then the whole hand is turned, scaled and moved, since the rule should
    only care about distances.
    """
    joints = np.zeros((21, 3))
    thumb = [(-30, -20), (-50, -40), (-65, -55), (-80, -70)] if thumb_out else [(-25, -25), (-30, -50), (-15, -70), (0, -75)]
    joints[1:5, :2] = thumb
    for finger, base in FINGER_BASES.items():
        x = FINGER_X[finger]
        tip_side = [(x, -150), (x, -175)] if finger in open_fingers else [(x, -100), (x, -70)]
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
    assert read_open_fingers(make_hand({"index", "ring"}).joints) == {"index": True, "middle": False, "ring": True, "pinky": False}


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
