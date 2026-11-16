"""Finds people, phones and faces in one camera frame.

Two small ONNX models run through plain OpenCV, so the Pi needs nothing new:
- models/yolo26n_480x640.onnx: YOLO26 nano trained on COCO, exported at the
  webcam's 640x480. Other sizes, like the Pi camera's 16:9 768x432, get shrunk
  and padded to fit (fit_to_input). COCO already has "person" and "cell phone".
- models/face_detection_yunet_2023mar.onnx: OpenCV's YuNet face detector. It
  gives 5 face points (eyes, nose tip, mouth corners), which is enough for a
  rough "facing the screen vs. looking down or away".

Phones are found in a second, zoomed-in pass: crop around the person, run YOLO
again on the crop. At desk distance the phone is too small for the full-frame
pass. Measured with YOLO11n on real desk frames, the full-frame pass scored
0.00-0.37 on a phone in hand, the zoomed pass 0.26-0.72 on the same frames and
0.00 on every frame of real work. YOLO26n hasn't been measured on the desk yet.
"""

import math
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from dayanpi.paths import MODELS_DIR

OBJECT_MODEL_PATH = MODELS_DIR / "yolo26n_480x640.onnx"
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

ZOOM_PERSON_MIN = 0.5
ZOOM_MARGIN_SIDES = 0.15
ZOOM_MARGIN_TOP = 0.05
ZOOM_MARGIN_BOTTOM = 0.10


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
    poses: list = field(default_factory=list)  # pose.PoseDetection, only when the pose model runs
    hands: list = field(default_factory=list)  # hands.Hand, when the hand models run
    side: "FrameReading | None" = None  # the side camera's own reading, when this one was merged from two


@dataclass
class Letterbox:
    """The model input plus what it takes to map boxes back onto the original frame."""

    image: np.ndarray
    scale: float
    pad_left: int
    pad_top: int


def find_best_confidence(detections: list[Detection]) -> float:
    best = max((detection.confidence for detection in detections), default=0.0)
    return best


def decode_jpeg(jpeg: bytes) -> np.ndarray | None:
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    return image


def fit_to_input(image: np.ndarray) -> Letterbox:
    source_height, source_width = image.shape[:2]
    scale = min(INPUT_WIDTH / source_width, INPUT_HEIGHT / source_height)
    resized_width = round(source_width * scale)
    resized_height = round(source_height * scale)

    resized = image
    if (resized_width, resized_height) != (source_width, source_height):
        resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

    # Same rounding as Ultralytics, so boxes line up with what the model was trained on.
    pad_x = (INPUT_WIDTH - resized_width) / 2
    pad_y = (INPUT_HEIGHT - resized_height) / 2
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


def make_blob(letterbox: Letterbox) -> np.ndarray:
    """The model input: 0-1 floats, RGB, NCHW. Shared by every YOLO model here."""
    blob = cv2.dnn.blobFromImage(
        letterbox.image,
        scalefactor=1 / 255,
        size=(INPUT_WIDTH, INPUT_HEIGHT),
        swapRB=True,
        crop=False,
    )
    return blob


def pick_boxes(boxes: np.ndarray, scores: np.ndarray) -> list[int]:
    """Non-max suppression over center-format boxes. Returns the kept row indices, strongest first."""
    top_left_boxes = [
        [float(cx - w / 2), float(cy - h / 2), float(w), float(h)]
        for cx, cy, w, h in boxes
    ]
    kept = cv2.dnn.NMSBoxes(top_left_boxes, scores.tolist(), MIN_CONFIDENCE, NMS_IOU)
    indices = [int(index) for index in np.array(kept, dtype=int).flatten()]
    return indices


def map_row_to_frame(box_row: np.ndarray, letterbox: Letterbox) -> Box:
    cx, cy, w, h = box_row
    frame_box = map_to_frame(float(cx), float(cy), float(w), float(h), letterbox)
    return frame_box


def decode_objects(output: np.ndarray, letterbox: Letterbox) -> list[Detection]:
    """output is the raw YOLO tensor, shape (1, 4 + classes, anchors).

    Each anchor counts only for its single best class out of all 80, like Ultralytics
    does, so a box that's mostly "person" doesn't also show up as a weak "phone".
    Keep the argmax over all 80, not just person and phone: that's what stops a mouse
    or a TV remote from counting as a phone.
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
        for index in pick_boxes(boxes, scores):
            detections.append(
                Detection(
                    label=label,
                    confidence=float(scores[index]),
                    box=map_row_to_frame(boxes[index], letterbox),
                )
            )

    detections.sort(key=lambda detection: detection.confidence, reverse=True)
    return detections


def find_zoom_region(person: Box, frame_width: int, frame_height: int) -> Box:
    """The person's box plus some margin (hands and lap stick out of it), in whole pixels."""
    width = person.x2 - person.x1
    height = person.y2 - person.y1
    region = Box(
        x1=float(max(0, int(person.x1 - ZOOM_MARGIN_SIDES * width))),
        y1=float(max(0, int(person.y1 - ZOOM_MARGIN_TOP * height))),
        x2=float(min(frame_width, int(person.x2 + ZOOM_MARGIN_SIDES * width))),
        y2=float(min(frame_height, int(person.y2 + ZOOM_MARGIN_BOTTOM * height))),
    )
    return region


def shift_box(box: Box, offset_x: float, offset_y: float) -> Box:
    shifted = Box(x1=box.x1 + offset_x, y1=box.y1 + offset_y, x2=box.x2 + offset_x, y2=box.y2 + offset_y)
    return shifted


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
    def __init__(self) -> None:
        self._net = cv2.dnn.readNetFromONNX(str(OBJECT_MODEL_PATH))

    def detect(self, image: np.ndarray) -> list[Detection]:
        letterbox = fit_to_input(image)
        self._net.setInput(make_blob(letterbox))
        detections = decode_objects(self._net.forward(), letterbox)
        return detections


class FaceDetector:
    def __init__(self) -> None:
        self._detector = cv2.FaceDetectorYN.create(
            str(FACE_MODEL_PATH),
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
    """Full-frame pass for people, zoomed pass for phones, plus faces.

    Phones only come from the zoomed pass, so no person means no zoomed pass.
    """

    has_pose = False  # PoseDeskScanner says True: its readings carry keypoints

    def __init__(
        self,
        object_detector: ObjectDetector | None = None,
        face_detector: FaceDetector | None = None,
    ) -> None:
        self._objects = object_detector or ObjectDetector()
        self._faces = face_detector or FaceDetector()

    def find_people(self, image: np.ndarray) -> list[Detection]:
        people = [detection for detection in self._objects.detect(image) if detection.label == "person"]
        return people

    def find_phones(self, image: np.ndarray, people: list[Detection]) -> list[Detection]:
        phones = []
        main_person = max(people, key=lambda person: person.confidence, default=None)
        if main_person is not None and main_person.confidence >= ZOOM_PERSON_MIN:
            frame_height, frame_width = image.shape[:2]
            region = find_zoom_region(main_person.box, frame_width, frame_height)
            crop = image[int(region.y1):int(region.y2), int(region.x1):int(region.x2)]
            phones = [
                Detection(label=found.label, confidence=found.confidence, box=shift_box(found.box, region.x1, region.y1))
                for found in self._objects.detect(crop)
                if found.label == "phone"
            ]
        return phones

    def scan(self, image: np.ndarray) -> FrameReading:
        started = time.perf_counter()
        people = self.find_people(image)
        phones = self.find_phones(image, people)
        reading = FrameReading(
            people=people,
            phones=phones,
            faces=self._faces.detect(image),
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
        return reading
