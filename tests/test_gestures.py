from dataclasses import replace

import pytest

from dayanpi.vision import gestures
from dayanpi.vision.detector import Box
from dayanpi.vision.gestures import GestureTracker, read_gesture
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

