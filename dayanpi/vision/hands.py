"""Finds hands and their 21 joints in one camera frame, for the hand signs.

Two models from OpenCV's model zoo (both Apache 2.0, converted from Google's MediaPipe
Hands), run through plain OpenCV like the others:
- models/palm_detection_mediapipe_2023feb.onnx finds palms in the whole frame, squeezed
  into 192x192. Each palm comes with 7 points: the wrist, the bases of the fingers, the thumb.
- models/handpose_estimation_mediapipe_2023feb.onnx finds the 21 joints in a 224x224 crop
  around one palm, turned so the fingers point up.

The pre- and post-processing follow the zoo's mp_palmdet.py and mp_handpose.py, except that
the hand crop is one rotated warp instead of two crops and a rotation, like MediaPipe itself.
Joint numbering is MediaPipe's: 0 is the wrist, then 4 per finger from the base out (thumb
1-4, index 5-8, middle 9-12, ring 13-16, pinky 17-20).
"""

import math
from dataclasses import dataclass

import cv2
import numpy as np

from dayanpi.paths import MODELS_DIR
from dayanpi.vision.detector import Box, Letterbox, map_row_to_frame, pick_boxes

PALM_MODEL_PATH = MODELS_DIR / "palm_detection_mediapipe_2023feb.onnx"
HAND_MODEL_PATH = MODELS_DIR / "handpose_estimation_mediapipe_2023feb.onnx"

PALM_INPUT_SIZE = 192
HAND_INPUT_SIZE = 224
PALM_MIN_CONFIDENCE = 0.6  # what the zoo's hand demo uses
HAND_MIN_CONFIDENCE = 0.8  # mp_handpose.py's default
MAX_HANDS = 2
PALM_WRIST = 0
PALM_MIDDLE_BASE = 2
# The hand crop: the turned palm's box, moved toward the fingers by 0.4 of its height and
# grown to a square 3 times its longer side, so the fingertips fit.
HAND_CROP_SHIFT = -0.4
HAND_CROP_SCALE = 3.0
JOINTS = 21


@dataclass
class Palm:
    confidence: float
    box: Box
    points: np.ndarray  # (7, 2) frame pixels


@dataclass
class Hand:
    confidence: float
    joints: np.ndarray  # (21, 3): x and y in frame pixels, z the depth from the wrist on the same scale

    def find_box(self) -> Box:
        low = self.joints[:, :2].min(axis=0)
        high = self.joints[:, :2].max(axis=0)
        box = Box(x1=float(low[0]), y1=float(low[1]), x2=float(high[0]), y2=float(high[1]))
        return box


def build_anchors() -> np.ndarray:
    """The palm model's 2016 anchor centers, as 0-1 fractions of its input.

    Every cell of a 24x24 grid holds 2 anchors, then every cell of a 12x12 grid holds 6, in
    reading order. mp_palmdet.py spells the same numbers out as a 2016-row table.
    """
    centers = []
    for cells, per_cell in ((24, 2), (12, 6)):
        for row in range(cells):
            for column in range(cells):
                centers.extend([((column + 0.5) / cells, (row + 0.5) / cells)] * per_cell)
    anchors = np.array(centers, dtype=np.float32)
    return anchors


def fit_square(image: np.ndarray, size: int) -> Letterbox:
    """Shrinks the frame into a size x size square, padded with black on the short side."""
    height, width = image.shape[:2]
    scale = size / max(height, width)
    resized = cv2.resize(image, (round(width * scale), round(height * scale)))
    pad_left = (size - resized.shape[1]) // 2
    pad_top = (size - resized.shape[0]) // 2
    padded = cv2.copyMakeBorder(
        resized,
        pad_top,
        size - resized.shape[0] - pad_top,
        pad_left,
        size - resized.shape[1] - pad_left,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )
    letterbox = Letterbox(image=padded, scale=scale, pad_left=pad_left, pad_top=pad_top)
    return letterbox


def make_hand_blob(image: np.ndarray) -> np.ndarray:
    """Both hand models take 0-1 floats, RGB, NHWC (not the NCHW the YOLO models take)."""
    blob = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)[np.newaxis].astype(np.float32) / 255
    return blob


def decode_palms(outputs: tuple, letterbox: Letterbox, anchors: np.ndarray) -> list[Palm]:
    """outputs is the palm model's (1, 2016, 18) rows and (1, 2016, 1) scores.

    Each row is a box (center offset from its anchor, then width and height) and the 7 points
    as offsets from the anchor, all in input pixels. The scores are logits.
    """
    rows = outputs[0][0]
    scores = 1 / (1 + np.exp(-outputs[1][0, :, 0].astype(np.float64)))
    keep = scores >= PALM_MIN_CONFIDENCE
    anchor_pixels = anchors[keep] * PALM_INPUT_SIZE
    boxes = np.c_[rows[keep, :2] + anchor_pixels, rows[keep, 2:4]]
    points = rows[keep, 4:].reshape(-1, 7, 2) + anchor_pixels[:, np.newaxis, :]
    offset = np.array([letterbox.pad_left, letterbox.pad_top])
    palms = [
        Palm(
            confidence=float(scores[keep][index]),
            box=map_row_to_frame(boxes[index], letterbox),
            points=(points[index] - offset) / letterbox.scale,
        )
        for index in pick_boxes(boxes, scores[keep])[:MAX_HANDS]
    ]
    return palms


def find_hand_crop(palm: Palm) -> np.ndarray:
    """The 2x3 warp from the frame into the hand model's input, fingers pointing up."""
    wrist = palm.points[PALM_WRIST]
    middle = palm.points[PALM_MIDDLE_BASE]
    angle = 90 - math.degrees(math.atan2(wrist[1] - middle[1], middle[0] - wrist[0]))
    turn = cv2.getRotationMatrix2D((0, 0), angle, 1.0)[:, :2]
    turned = palm.points @ turn.T
    low = turned.min(axis=0)
    high = turned.max(axis=0)
    turned_center = (low + high) / 2 + [0, HAND_CROP_SHIFT * (high - low)[1]]
    center = turned_center @ turn  # turned back: the inverse of a rotation is its transpose
    side = HAND_CROP_SCALE * (high - low).max()
    warp = cv2.getRotationMatrix2D((float(center[0]), float(center[1])), angle, HAND_INPUT_SIZE / side)
    warp[:, 2] += HAND_INPUT_SIZE / 2 - center
    return warp


def decode_hand(outputs: tuple, warp: np.ndarray) -> Hand | None:
    """outputs is the hand model's joints (1, 63), confidence, handedness and world joints.

    The joints are x, y, z in crop pixels; they go back through the inverse of the crop's warp.
    """
    confidence = float(outputs[1][0, 0])
    hand = None
    if confidence >= HAND_MIN_CONFIDENCE:
        joints = outputs[0][0].reshape(JOINTS, 3).astype(np.float64)
        back = cv2.invertAffineTransform(warp)
        frame_joints = np.c_[joints[:, :2] @ back[:, :2].T + back[:, 2], joints[:, 2] * math.hypot(*back[:, 0])]
        hand = Hand(confidence=confidence, joints=frame_joints)
    return hand


class HandScanner:
    def __init__(self) -> None:
        self._palm_net = cv2.dnn.readNetFromONNX(str(PALM_MODEL_PATH))
        self._hand_net = cv2.dnn.readNetFromONNX(str(HAND_MODEL_PATH))
        self._anchors = build_anchors()

    def find_palms(self, image: np.ndarray) -> list[Palm]:
        letterbox = fit_square(image, PALM_INPUT_SIZE)
        self._palm_net.setInput(make_hand_blob(letterbox.image))
        outputs = self._palm_net.forward(self._palm_net.getUnconnectedOutLayersNames())
        palms = decode_palms(outputs, letterbox, self._anchors)
        return palms

    def read_hand(self, image: np.ndarray, palm: Palm) -> Hand | None:
        warp = find_hand_crop(palm)
        crop = cv2.warpAffine(image, warp, (HAND_INPUT_SIZE, HAND_INPUT_SIZE))
        self._hand_net.setInput(make_hand_blob(crop))
        hand = decode_hand(self._hand_net.forward(self._hand_net.getUnconnectedOutLayersNames()), warp)
        return hand

    def scan(self, image: np.ndarray) -> list[Hand]:
        hands = [hand for palm in self.find_palms(image) if (hand := self.read_hand(image, palm)) is not None]
        return hands
