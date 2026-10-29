from pathlib import Path

import numpy as np
import pytest

import pose
from detector import PAD_VALUE, Box, Detection, fit_to_input
from pose import (
    KEYPOINT_NAMES,
    LEFT_WRIST,
    RIGHT_WRIST,
    PoseDetection,
    PoseDetector,
    decode_poses,
    make_person_detection,
)

OUTPUT_ROWS = 4 + 1 + 17 * 3
PLAIN_LETTERBOX = fit_to_input(np.zeros((480, 640, 3), np.uint8))
PERSON_BOX = [320, 240, 100, 200]


def make_keypoints(offset: float = 0.0) -> np.ndarray:
    """17 rows of x, y, confidence in input pixels. Keypoint i sits at (100 + 10i, 50 + 5i), plus offset."""
    index = np.arange(len(KEYPOINT_NAMES), dtype=np.float32)
    keypoints = np.stack([100 + 10 * index + offset, 50 + 5 * index + offset, np.full_like(index, 0.9)], axis=1)
    return keypoints


def make_output(anchors: list[dict]) -> np.ndarray:
    """Builds a fake YOLO pose tensor, shape (1, 56, anchors), keypoints stored as x, y, confidence in turn."""
    output = np.zeros((1, OUTPUT_ROWS, len(anchors)), dtype=np.float32)
    for column, anchor in enumerate(anchors):
        output[0, :4, column] = anchor["box"]
        output[0, 4, column] = anchor["score"]
        output[0, 5:, column] = anchor.get("keypoints", make_keypoints()).ravel()
    return output


def list_keypoint_values(found: PoseDetection) -> np.ndarray:
    values = np.array([[keypoint.x, keypoint.y, keypoint.confidence] for keypoint in found.keypoints])
    return values


def test_decode_reads_the_box_score_and_all_keypoints_in_order():
    output = make_output([{"box": PERSON_BOX, "score": 0.9}])
    poses = decode_poses(output, PLAIN_LETTERBOX)
    assert len(poses) == 1
    assert poses[0].confidence == pytest.approx(0.9)
    assert poses[0].box == Box(x1=270, y1=140, x2=370, y2=340)
    np.testing.assert_allclose(list_keypoint_values(poses[0]), make_keypoints())
    right_wrist = poses[0].keypoints[RIGHT_WRIST]
    assert (right_wrist.x, right_wrist.y) == (200, 100)


@pytest.mark.parametrize(
    ("frame_shape", "expected_box", "expected_wrist"),
    [
        ((720, 1280, 3), Box(x1=540, y1=160, x2=740, y2=560), (380, 70)),
        ((960, 640, 3), Box(x1=220, y1=280, x2=420, y2=680), (60, 190)),
    ],
)
def test_decode_maps_boxes_and_keypoints_back_through_scale_and_padding(frame_shape, expected_box, expected_wrist):
    letterbox = fit_to_input(np.zeros(frame_shape, np.uint8))
    found = decode_poses(make_output([{"box": PERSON_BOX, "score": 0.9}]), letterbox)[0]
    left_wrist = found.keypoints[LEFT_WRIST]
    assert found.box == expected_box
    assert (left_wrist.x, left_wrist.y) == expected_wrist
    assert left_wrist.confidence == pytest.approx(0.9)


def test_decode_drops_weak_hits_and_merges_duplicates():
    output = make_output(
        [
            {"box": PERSON_BOX, "score": 0.8, "keypoints": make_keypoints(offset=7)},
            {"box": [322, 242, 100, 200], "score": 0.9},
            {"box": [100, 100, 40, 80], "score": 0.1},
        ]
    )
    poses = decode_poses(output, PLAIN_LETTERBOX)
    assert len(poses) == 1
    assert poses[0].confidence == pytest.approx(0.9)
    np.testing.assert_allclose(list_keypoint_values(poses[0]), make_keypoints())


def test_decode_keeps_separate_people_strongest_first():
    output = make_output(
        [
            {"box": [150, 240, 100, 200], "score": 0.6},
            {"box": [450, 240, 100, 200], "score": 0.95},
        ]
    )
    poses = decode_poses(output, PLAIN_LETTERBOX)
    assert [found.confidence for found in poses] == pytest.approx([0.95, 0.6])


def test_decode_finds_nobody_when_every_score_is_low():
    assert decode_poses(make_output([{"box": PERSON_BOX, "score": 0.05}]), PLAIN_LETTERBOX) == []


def test_decode_refuses_output_from_the_wrong_model():
    object_model_output = np.zeros((1, 84, 6300), np.float32)
    with pytest.raises(ValueError, match="56 rows"):
        decode_poses(object_model_output, PLAIN_LETTERBOX)


def test_make_person_detection_keeps_the_score_and_box():
    found = PoseDetection(confidence=0.8, box=Box(x1=1, y1=2, x2=3, y2=4), keypoints=[])
    assert make_person_detection(found) == Detection(label="person", confidence=0.8, box=Box(x1=1, y1=2, x2=3, y2=4))


class FakeNet:
    """Stands in for cv2.dnn.Net, so it keeps OpenCV's method names."""

    def __init__(self, output: np.ndarray) -> None:
        self.output = output
        self.blobs = []

    def setInput(self, blob: np.ndarray) -> None:
        self.blobs.append(blob)

    def forward(self) -> np.ndarray:
        return self.output


def test_detector_letterboxes_like_the_object_detector_and_maps_poses_back(monkeypatch):
    net = FakeNet(make_output([{"box": PERSON_BOX, "score": 0.9}]))
    monkeypatch.setattr(pose.cv2.dnn, "readNetFromONNX", lambda path: net)
    red_frame = np.zeros((720, 1280, 3), np.uint8)
    red_frame[:, :, 2] = 255

    poses = PoseDetector(Path("fake.onnx")).detect(red_frame)

    blob = net.blobs[0]
    assert blob.shape == (1, 3, 480, 640)
    np.testing.assert_allclose(blob[0, :, 240, 320], [1.0, 0.0, 0.0])
    assert blob[0, 0, 0, 0] == pytest.approx(PAD_VALUE / 255)
    assert poses[0].box == Box(x1=540, y1=160, x2=740, y2=560)


@pytest.mark.skipif(not pose.POSE_MODEL_PATH.exists(), reason="pose model not in models/")
def test_real_pose_model_finds_nobody_in_a_blank_frame():
    assert PoseDetector().detect(np.full((480, 640, 3), 128, np.uint8)) == []
