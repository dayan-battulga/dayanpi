import cv2
import numpy as np
import pytest

from dayanpi.vision import hands
from dayanpi.vision.detector import Box, Letterbox
from dayanpi.vision.hands import HAND_INPUT_SIZE, Palm, build_anchors, decode_hand, decode_palms, find_hand_crop, fit_square, is_near_hand

# The Pi camera's 768x432 shrinks to 192x108 for the palm model, with 42 px of black above.
PI_LETTERBOX = Letterbox(image=None, scale=0.25, pad_left=0, pad_top=42)
UPRIGHT_PALM = np.array(
    [(300, 300), (270, 220), (290, 215), (310, 220), (330, 228), (262, 285), (245, 262)],
    dtype=np.float64,
)  # wrist, index, middle, ring and pinky bases, two thumb points; fingers point up


def turn_points(points: np.ndarray, degrees: float, center: tuple[float, float]) -> np.ndarray:
    rotation = cv2.getRotationMatrix2D(center, degrees, 1.0)
    turned = points @ rotation[:, :2].T + rotation[:, 2]
    return turned


def make_palm(points: np.ndarray) -> Palm:
    low, high = points.min(axis=0), points.max(axis=0)
    palm = Palm(confidence=0.9, box=Box(x1=low[0], y1=low[1], x2=high[0], y2=high[1]), points=points)
    return palm


def test_the_anchors_are_two_grids_in_reading_order():
    anchors = build_anchors()
    assert anchors.shape == (2016, 2)
    assert anchors[:3] == pytest.approx(np.array([[1 / 48, 1 / 48], [1 / 48, 1 / 48], [3 / 48, 1 / 48]]))
    assert anchors[1152:1158] == pytest.approx(np.full((6, 2), 1 / 24)), "the 12x12 grid starts at 24*24*2"
    assert anchors[-1] == pytest.approx(np.array([23 / 24, 23 / 24]))


def test_a_16_9_frame_is_padded_top_and_bottom():
    letterbox = fit_square(np.zeros((432, 768, 3), np.uint8), 192)
    assert letterbox.image.shape == (192, 192, 3)
    assert (letterbox.scale, letterbox.pad_left, letterbox.pad_top) == (PI_LETTERBOX.scale, 0, 42)


def test_a_palm_comes_back_in_frame_pixels_and_overlaps_are_dropped():
    rows = np.zeros((1, 2016, 18), np.float32)
    scores = np.full((1, 2016, 1), -10.0, np.float32)
    strong = (10 * 24 + 12) * 2  # 24x24 grid, row 10, column 12: center (100, 84) in the 192x192 input
    rows[0, strong, 2:4] = (40, 40)
    rows[0, strong, 4 + 2 * hands.PALM_MIDDLE_BASE + 1] = -10  # the middle finger's base sits 10 px above the anchor
    scores[0, strong, 0] = 5.0
    rows[0, strong + 1] = rows[0, strong]
    scores[0, strong + 1, 0] = 3.0  # same cell, same box, weaker: non-max suppression drops it

    palms = decode_palms((rows, scores), PI_LETTERBOX, build_anchors())

    assert len(palms) == 1
    box = palms[0].box
    assert [box.x1, box.y1, box.x2, box.y2] == pytest.approx([320, 88, 480, 248])
    assert palms[0].points[hands.PALM_WRIST].tolist() == pytest.approx([400, 168])
    assert palms[0].points[hands.PALM_MIDDLE_BASE].tolist() == pytest.approx([400, 128])
    assert palms[0].confidence == pytest.approx(1 / (1 + np.exp(-5.0)))


@pytest.mark.parametrize("degrees", [0, 90, -90, 150])
def test_the_hand_crop_turns_the_fingers_up(degrees):
    palm = make_palm(turn_points(UPRIGHT_PALM, degrees, center=(300, 300)))
    warp = find_hand_crop(palm)
    in_crop = palm.points @ warp[:, :2].T + warp[:, 2]
    wrist, middle = in_crop[hands.PALM_WRIST], in_crop[hands.PALM_MIDDLE_BASE]
    assert middle[0] == pytest.approx(wrist[0], abs=1e-6)
    assert middle[1] < wrist[1]
    assert (in_crop >= 0).all() and (in_crop <= HAND_INPUT_SIZE).all(), "the whole palm fits in the crop"


def test_hand_joints_go_back_to_frame_pixels():
    palm = make_palm(turn_points(UPRIGHT_PALM, 60, center=(300, 300)))
    warp = find_hand_crop(palm)
    frame_joints = np.random.default_rng(1).uniform(200, 400, size=(21, 2))
    crop_joints = frame_joints @ warp[:, :2].T + warp[:, 2]
    model_joints = np.c_[crop_joints, np.full(21, 10.0)].reshape(1, 63).astype(np.float32)
    outputs = (model_joints, np.array([[0.95]]), np.array([[0.5]]), np.zeros((1, 63)))

    hand = decode_hand(outputs, warp)

    assert hand.confidence == pytest.approx(0.95)
    assert hand.joints[:, :2] == pytest.approx(frame_joints, abs=1e-3)
    scale_back = 1 / np.hypot(*warp[:, 0])
    assert hand.joints[:, 2] == pytest.approx(10.0 * scale_back)
    assert decode_hand((model_joints, np.array([[0.5]]), np.array([[0.5]]), np.zeros((1, 63))), warp) is None


@pytest.mark.skipif(
    not (hands.PALM_MODEL_PATH.exists() and hands.HAND_MODEL_PATH.exists()),
    reason="hand model files not in models/",
)
@pytest.mark.parametrize("shape", [(480, 640, 3), (432, 768, 3)])
def test_real_hand_models_find_nothing_in_a_blank_frame(shape):
    assert hands.HandScanner().scan(np.full(shape, 128, np.uint8)) == []


def test_a_phone_counts_up_to_a_quarter_of_a_hand_away():
    hand = Box(100, 100, 200, 180)  # longer side 100 px, so the margin is 25 px
    assert is_near_hand(Box(150, 150, 190, 210), hand), "overlapping"
    assert is_near_hand(Box(224, 120, 260, 160), hand), "24 px to the right"
    assert not is_near_hand(Box(226, 120, 260, 160), hand), "26 px to the right"
    assert not is_near_hand(Box(120, 206, 160, 240), hand), "26 px below"
