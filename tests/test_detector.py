import numpy as np
import pytest

import detector
from detector import Box, DeskScanner, Letterbox, decode_objects, fit_to_input, read_face

CLASS_COUNT = 80
PLAIN_LETTERBOX = Letterbox(image=np.zeros((480, 640, 3), np.uint8), scale=1.0, pad_left=0, pad_top=0)


def make_output(anchors: list[dict]) -> np.ndarray:
    """Builds a fake YOLO tensor, shape (1, 4 + 80, anchors)."""
    output = np.zeros((1, 4 + CLASS_COUNT, len(anchors)), dtype=np.float32)
    for column, anchor in enumerate(anchors):
        output[0, :4, column] = anchor["box"]
        for class_id, score in anchor["scores"].items():
            output[0, 4 + class_id, column] = score
    return output


def test_fit_to_input_leaves_camera_sized_frames_alone():
    frame = np.full((480, 640, 3), 7, np.uint8)
    letterbox = fit_to_input(frame)
    assert letterbox.image.shape == (480, 640, 3)
    assert letterbox.scale == 1.0
    assert (letterbox.pad_left, letterbox.pad_top) == (0, 0)
    assert np.array_equal(letterbox.image, frame)


def test_fit_to_input_shrinks_and_pads_wide_frames():
    letterbox = fit_to_input(np.zeros((720, 1280, 3), np.uint8))
    assert letterbox.image.shape == (480, 640, 3)
    assert letterbox.scale == pytest.approx(0.5)
    assert (letterbox.pad_left, letterbox.pad_top) == (0, 60)
    assert letterbox.image[0, 0, 0] == detector.PAD_VALUE


def test_decode_keeps_people_and_phones_only():
    output = make_output(
        [
            {"box": [320, 240, 100, 200], "scores": {detector.PERSON_CLASS_ID: 0.9}},
            {"box": [100, 100, 20, 40], "scores": {detector.PHONE_CLASS_ID: 0.6}},
            {"box": [500, 300, 80, 80], "scores": {5: 0.95}},
        ]
    )
    detections = decode_objects(output, PLAIN_LETTERBOX)
    assert [d.label for d in detections] == ["person", "phone"]
    assert detections[0].box == Box(x1=270, y1=140, x2=370, y2=340)
    assert detections[1].confidence == pytest.approx(0.6)


def test_decode_maps_boxes_back_through_padding():
    letterbox = Letterbox(image=PLAIN_LETTERBOX.image, scale=0.5, pad_left=0, pad_top=60)
    output = make_output([{"box": [320, 240, 100, 200], "scores": {detector.PERSON_CLASS_ID: 0.9}}])
    box = decode_objects(output, letterbox)[0].box
    assert box == Box(x1=540, y1=160, x2=740, y2=560)


def test_decode_drops_weak_hits_and_merges_duplicates():
    output = make_output(
        [
            {"box": [320, 240, 100, 200], "scores": {detector.PERSON_CLASS_ID: 0.9}},
            {"box": [322, 242, 100, 200], "scores": {detector.PERSON_CLASS_ID: 0.8}},
            {"box": [100, 100, 20, 40], "scores": {detector.PHONE_CLASS_ID: 0.1}},
        ]
    )
    detections = decode_objects(output, PLAIN_LETTERBOX)
    assert len(detections) == 1
    assert detections[0].confidence == pytest.approx(0.9)


def test_decode_counts_each_box_for_its_best_class_only():
    output = make_output(
        [{"box": [320, 240, 100, 200], "scores": {detector.PERSON_CLASS_ID: 0.8, detector.PHONE_CLASS_ID: 0.3}}]
    )
    assert [d.label for d in decode_objects(output, PLAIN_LETTERBOX)] == ["person"]


def yunet_row(nose_x: float, nose_y: float) -> np.ndarray:
    # x, y, w, h, right eye, left eye, nose, right mouth, left mouth, score
    return np.array(
        [80, 70, 80, 100, 100, 100, 140, 100, nose_x, nose_y, 105, 140, 135, 140, 0.92],
        dtype=np.float32,
    )


def test_read_face_facing_the_camera():
    face = read_face(yunet_row(nose_x=120, nose_y=120))
    assert face.turn == pytest.approx(0.0)
    assert face.tilt == pytest.approx(0.5)
    assert face.box == Box(x1=80, y1=70, x2=160, y2=170)
    assert face.confidence == pytest.approx(0.92)


def test_read_face_turned_and_tilted():
    face = read_face(yunet_row(nose_x=130, nose_y=132))
    assert face.turn == pytest.approx(0.25)
    assert face.tilt == pytest.approx(0.8)


@pytest.mark.skipif(
    not (detector.OBJECT_MODEL_PATH.exists() and detector.FACE_MODEL_PATH.exists()),
    reason="model files not in models/",
)
def test_real_models_find_nothing_in_a_blank_frame():
    reading = DeskScanner().scan(np.full((480, 640, 3), 128, np.uint8))
    assert reading.people == []
    assert reading.phones == []
    assert reading.faces == []
    assert reading.elapsed_ms > 0
