"""Finds people's body points (shoulders, wrists and so on) in one camera frame.

models/yolo11n-pose_480x640.onnx is Ultralytics' YOLO11 nano pose model, exported at the
camera's 640x480 size and run through plain OpenCV, same as detector.py. Each hit is a person
box plus 17 COCO keypoints. Left and right are the person's own sides, so with the camera
facing you, your right wrist shows up on the left half of the image.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from dayanpi.vision.detector import (
    BOX_VALUES,
    LABELS,
    MIN_CONFIDENCE,
    MODELS_DIR,
    PERSON_CLASS_ID,
    Box,
    DeskScanner,
    Detection,
    FrameReading,
    Letterbox,
    Point,
    fit_to_input,
    make_blob,
    map_row_to_frame,
    map_to_frame,
    pick_boxes,
)

POSE_MODEL_PATH = MODELS_DIR / "yolo11n-pose_480x640.onnx"

KEYPOINT_NAMES = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)
LEFT_SHOULDER = KEYPOINT_NAMES.index("left_shoulder")
RIGHT_SHOULDER = KEYPOINT_NAMES.index("right_shoulder")
LEFT_WRIST = KEYPOINT_NAMES.index("left_wrist")
RIGHT_WRIST = KEYPOINT_NAMES.index("right_wrist")

KEYPOINT_VALUES = 3
SCORE_ROW = BOX_VALUES
KEYPOINTS_START = SCORE_ROW + 1
OUTPUT_ROWS = KEYPOINTS_START + len(KEYPOINT_NAMES) * KEYPOINT_VALUES


@dataclass
class Keypoint(Point):
    confidence: float


@dataclass
class PoseDetection:
    confidence: float
    box: Box
    keypoints: list[Keypoint]


def map_keypoint(values: np.ndarray, letterbox: Letterbox) -> Keypoint:
    """values is one keypoint's x, y and confidence from the model.

    A point maps back onto the frame like a box with no size.
    """
    x, y, confidence = (float(value) for value in values)
    spot = map_to_frame(x, y, 0.0, 0.0, letterbox)
    keypoint = Keypoint(x=spot.x1, y=spot.y1, confidence=confidence)
    return keypoint


def decode_poses(output: np.ndarray, letterbox: Letterbox) -> list[PoseDetection]:
    """output is the raw YOLO pose tensor, shape (1, 56, anchors).

    Each anchor is a box (cx, cy, w, h in input pixels), the person score, then 17 keypoints
    as x, y, confidence. The export already squashed the keypoint confidences to 0-1.
    """
    if output.shape[1] != OUTPUT_ROWS:
        raise ValueError(
            f"Expected a YOLO pose output with {OUTPUT_ROWS} rows, got shape {output.shape}. "
            "Re-export the pose model with the command in docs/focus-tracker.md."
        )

    predictions = output[0].T
    keep = predictions[:, SCORE_ROW] >= MIN_CONFIDENCE
    boxes = predictions[keep, :BOX_VALUES]
    scores = predictions[keep, SCORE_ROW]
    keypoint_rows = predictions[keep, KEYPOINTS_START:].reshape(-1, len(KEYPOINT_NAMES), KEYPOINT_VALUES)

    poses = []
    for index in pick_boxes(boxes, scores):
        poses.append(
            PoseDetection(
                confidence=float(scores[index]),
                box=map_row_to_frame(boxes[index], letterbox),
                keypoints=[map_keypoint(values, letterbox) for values in keypoint_rows[index]],
            )
        )

    poses.sort(key=lambda found: found.confidence, reverse=True)
    return poses


def make_person_detection(pose: PoseDetection) -> Detection:
    """So the pose pass can stand in for the object model's full-frame person pass."""
    person = Detection(label=LABELS[PERSON_CLASS_ID], confidence=pose.confidence, box=pose.box)
    return person


class PoseDetector:
    def __init__(self, model_path: Path = POSE_MODEL_PATH) -> None:
        self._net = cv2.dnn.readNetFromONNX(str(model_path))

    def detect(self, image: np.ndarray) -> list[PoseDetection]:
        letterbox = fit_to_input(image)
        self._net.setInput(make_blob(letterbox))
        poses = decode_poses(self._net.forward(), letterbox)
        return poses


class PoseDeskScanner(DeskScanner):
    """A DeskScanner whose full-frame pass is the pose model, so people come with keypoints.

    The zoomed pass (phones, food, drinks) and the face pass are unchanged.
    """

    def __init__(self) -> None:
        super().__init__()
        self._poses = PoseDetector()
        self._last_poses: list[PoseDetection] = []

    def find_people(self, image: np.ndarray) -> list[Detection]:
        self._last_poses = self._poses.detect(image)
        people = [make_person_detection(pose) for pose in self._last_poses]
        return people

    def scan(self, image: np.ndarray) -> FrameReading:
        reading = super().scan(image)
        reading.poses = self._last_poses
        return reading


def pick_main_pose(reading: FrameReading) -> PoseDetection | None:
    main_pose = max(reading.poses, key=lambda pose: pose.confidence, default=None)
    return main_pose
