"""Finds people, phones and faces in one camera frame.

Two small ONNX models run through plain OpenCV, so the Pi needs nothing new:
- models/yolo11n_480x640.onnx: YOLO11 nano trained on COCO, exported at the
  camera's own 640x480 size. COCO already has "person" and "cell phone".
- models/face_detection_yunet_2023mar.onnx: OpenCV's YuNet face detector. It
  gives 5 face points (eyes, nose tip, mouth corners), which is enough for a
  rough "facing the screen vs. looking down or away".
"""

import math
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MODELS_DIR = Path(__file__).resolve().parent / "models"
OBJECT_MODEL_PATH = MODELS_DIR / "yolo11n_480x640.onnx"
FACE_MODEL_PATH = MODELS_DIR / "face_detection_yunet_2023mar.onnx"

INPUT_WIDTH = 640
INPUT_HEIGHT = 480
PAD_VALUE = 114

PERSON_CLASS_ID = 0
PHONE_CLASS_ID = 67
LABELS = {PERSON_CLASS_ID: "person", PHONE_CLASS_ID: "phone"}
BOX_VALUES = 4

MIN_CONFIDENCE = 0.15
NMS_IOU = 0.5
FACE_MIN_CONFIDENCE = 0.6


@dataclass
class Point:
    x: float
    y: float


@dataclass
class Box:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class Detection:
    label: str
    confidence: float
    box: Box


@dataclass
class FaceReading:
    """turn: nose offset from the eye midpoint, in eye-widths (about 0 = facing the camera).
    tilt: nose height between the eye line (0) and the mouth line (1).
    """

    confidence: float
    box: Box
    landmarks: list[Point]
    turn: float
    tilt: float


@dataclass
class FrameReading:
    people: list[Detection]
    phones: list[Detection]
    faces: list[FaceReading]
    elapsed_ms: float


@dataclass
class Letterbox:
    """The model input plus what it takes to map boxes back onto the original frame."""

    image: np.ndarray
    scale: float
    pad_left: int
    pad_top: int


def decode_jpeg(jpeg: bytes) -> np.ndarray | None:
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    return image


def fit_to_input(image: np.ndarray, width: int = INPUT_WIDTH, height: int = INPUT_HEIGHT) -> Letterbox:
    source_height, source_width = image.shape[:2]
    scale = min(width / source_width, height / source_height)
    resized_width = round(source_width * scale)
    resized_height = round(source_height * scale)

    resized = image
    if (resized_width, resized_height) != (source_width, source_height):
        resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

    # Same rounding as Ultralytics, so boxes line up with what the model was trained on.
    pad_x = (width - resized_width) / 2
    pad_y = (height - resized_height) / 2
    pad_left = int(round(pad_x - 0.1))
    pad_right = int(round(pad_x + 0.1))
    pad_top = int(round(pad_y - 0.1))
    pad_bottom = int(round(pad_y + 0.1))
    padded = cv2.copyMakeBorder(
        resized,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=(PAD_VALUE, PAD_VALUE, PAD_VALUE),
    )
    letterbox = Letterbox(image=padded, scale=scale, pad_left=pad_left, pad_top=pad_top)
    return letterbox


def map_to_frame(center_x: float, center_y: float, box_width: float, box_height: float, letterbox: Letterbox) -> Box:
    frame_box = Box(
        x1=(center_x - box_width / 2 - letterbox.pad_left) / letterbox.scale,
        y1=(center_y - box_height / 2 - letterbox.pad_top) / letterbox.scale,
        x2=(center_x + box_width / 2 - letterbox.pad_left) / letterbox.scale,
        y2=(center_y + box_height / 2 - letterbox.pad_top) / letterbox.scale,
    )
    return frame_box


def decode_objects(output: np.ndarray, letterbox: Letterbox) -> list[Detection]:
    """output is the raw YOLO tensor, shape (1, 4 + classes, anchors).

    Each anchor counts only for its single best class, like Ultralytics does, so a
    box that's mostly "person" doesn't also show up as a weak "phone".
    """
    predictions = output[0].T
    class_scores = predictions[:, BOX_VALUES:]
    best_class = class_scores.argmax(axis=1)
    best_score = class_scores.max(axis=1)

    detections = []
    for class_id, label in LABELS.items():
        keep = (best_class == class_id) & (best_score >= MIN_CONFIDENCE)
        boxes = predictions[keep, :BOX_VALUES]
        scores = best_score[keep]
        top_left_boxes = [
            [float(cx - w / 2), float(cy - h / 2), float(w), float(h)]
            for cx, cy, w, h in boxes
        ]
        kept = cv2.dnn.NMSBoxes(top_left_boxes, scores.tolist(), MIN_CONFIDENCE, NMS_IOU)
        for index in np.array(kept, dtype=int).flatten():
            cx, cy, w, h = boxes[index]
            detections.append(
                Detection(
                    label=label,
                    confidence=float(scores[index]),
                    box=map_to_frame(float(cx), float(cy), float(w), float(h), letterbox),
                )
            )

    detections.sort(key=lambda detection: detection.confidence, reverse=True)
    return detections


def midpoint(first: Point, second: Point) -> Point:
    middle = Point(x=(first.x + second.x) / 2, y=(first.y + second.y) / 2)
    return middle


def read_face(row: np.ndarray) -> FaceReading:
    """row is one YuNet result: x, y, w, h, then 5 (x, y) points, then the score.

    The points are right eye, left eye, nose tip, right mouth corner, left mouth
    corner, where right/left are the person's own sides.
    """
    x, y, width, height = (float(value) for value in row[:4])
    landmarks = [Point(x=float(row[4 + 2 * i]), y=float(row[5 + 2 * i])) for i in range(5)]
    right_eye, left_eye, nose, right_mouth, left_mouth = landmarks

    eye_middle = midpoint(right_eye, left_eye)
    mouth_middle = midpoint(right_mouth, left_mouth)
    eye_distance = math.hypot(left_eye.x - right_eye.x, left_eye.y - right_eye.y)
    eye_to_mouth = mouth_middle.y - eye_middle.y

    turn = (nose.x - eye_middle.x) / eye_distance if eye_distance > 0 else 0.0
    tilt = (nose.y - eye_middle.y) / eye_to_mouth if eye_to_mouth > 0 else 0.0

    face = FaceReading(
        confidence=float(row[14]),
        box=Box(x1=x, y1=y, x2=x + width, y2=y + height),
        landmarks=landmarks,
        turn=turn,
        tilt=tilt,
    )
    return face


class ObjectDetector:
    def __init__(self, model_path: Path = OBJECT_MODEL_PATH) -> None:
        self._net = cv2.dnn.readNetFromONNX(str(model_path))

    def detect(self, image: np.ndarray) -> list[Detection]:
        letterbox = fit_to_input(image)
        blob = cv2.dnn.blobFromImage(
            letterbox.image,
            scalefactor=1 / 255,
            size=(INPUT_WIDTH, INPUT_HEIGHT),
            swapRB=True,
            crop=False,
        )
        self._net.setInput(blob)
        detections = decode_objects(self._net.forward(), letterbox)
        return detections


class FaceDetector:
    def __init__(self, model_path: Path = FACE_MODEL_PATH) -> None:
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path),
            "",
            (INPUT_WIDTH, INPUT_HEIGHT),
            FACE_MIN_CONFIDENCE,
        )

    def detect(self, image: np.ndarray) -> list[FaceReading]:
        height, width = image.shape[:2]
        self._detector.setInputSize((width, height))
        raw_faces = self._detector.detect(image)[1]
        faces = [] if raw_faces is None else [read_face(row) for row in raw_faces]
        return faces


class DeskScanner:
    """One object detector plus one face detector, run together on a frame."""

    def __init__(
        self,
        object_detector: ObjectDetector | None = None,
        face_detector: FaceDetector | None = None,
    ) -> None:
        self._objects = object_detector or ObjectDetector()
        self._faces = face_detector or FaceDetector()

    def scan(self, image: np.ndarray) -> FrameReading:
        started = time.perf_counter()
        detections = self._objects.detect(image)
        faces = self._faces.detect(image)
        reading = FrameReading(
            people=[detection for detection in detections if detection.label == "person"],
            phones=[detection for detection in detections if detection.label == "phone"],
            faces=faces,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
        return reading
