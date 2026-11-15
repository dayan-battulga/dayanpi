import numpy as np
import pytest

from dayanpi.vision import detector
from dayanpi.vision.detector import (
    Box,
    DeskScanner,
    Detection,
    Letterbox,
    decode_objects,
    find_zoom_region,
    fit_to_input,
    read_face,
    shift_box,
)

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


def test_decode_drops_food_drinks_and_phone_lookalikes():
    remote_class_id = 65
    output = make_output(
        [
            {"box": [100, 100, 40, 40], "scores": {41: 0.7}},
            {"box": [300, 300, 60, 40], "scores": {54: 0.5}},
            {"box": [500, 300, 20, 40], "scores": {remote_class_id: 0.6, detector.PHONE_CLASS_ID: 0.4}},
        ]
    )
    assert decode_objects(output, PLAIN_LETTERBOX) == []


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


def test_zoom_region_adds_margin_and_stays_in_frame():
    region = find_zoom_region(Box(x1=300, y1=150, x2=500, y2=450), frame_width=640, frame_height=480)
    assert region == Box(x1=270, y1=135, x2=530, y2=480)
    edge = find_zoom_region(Box(x1=0, y1=0, x2=640, y2=480), frame_width=640, frame_height=480)
    assert edge == Box(x1=0, y1=0, x2=640, y2=480)


def test_shift_box_moves_crop_boxes_back_onto_the_frame():
    assert shift_box(Box(x1=10, y1=20, x2=30, y2=40), 100, 50) == Box(x1=110, y1=70, x2=130, y2=90)


class FakeObjectDetector:
    """First call is the full frame, every later call is the zoomed crop."""

    def __init__(self, full_frame: list[Detection], zoomed: list[Detection]) -> None:
        self.full_frame = full_frame
        self.zoomed = zoomed
        self.shapes = []

    def detect(self, image: np.ndarray) -> list[Detection]:
        self.shapes.append(image.shape)
        found = self.full_frame if len(self.shapes) == 1 else self.zoomed
        return found


class FakeFaceDetector:
    def detect(self, image: np.ndarray) -> list:
        return []


def test_scanner_takes_phones_from_the_zoomed_crop_only():
    person = Detection("person", 0.9, Box(x1=300, y1=150, x2=500, y2=450))
    far_phone = Detection("phone", 0.4, Box(x1=10, y1=10, x2=30, y2=40))
    crop_phone = Detection("phone", 0.7, Box(x1=20, y1=200, x2=60, y2=260))
    objects = FakeObjectDetector(full_frame=[person, far_phone], zoomed=[crop_phone])

    reading = DeskScanner(objects, FakeFaceDetector()).scan(np.zeros((480, 640, 3), np.uint8))

    assert objects.shapes == [(480, 640, 3), (345, 260, 3)]
    assert reading.people == [person]
    assert [phone.confidence for phone in reading.phones] == [pytest.approx(0.7)]
    assert reading.phones[0].box == Box(x1=290, y1=335, x2=330, y2=395)


def test_scanner_keeps_only_phones_from_the_zoomed_crop():
    person = Detection("person", 0.9, Box(x1=300, y1=150, x2=500, y2=450))
    zoomed = [
        Detection("phone", 0.6, Box(x1=20, y1=200, x2=60, y2=260)),
        Detection("person", 0.8, Box(x1=0, y1=0, x2=200, y2=300)),
    ]
    objects = FakeObjectDetector(full_frame=[person], zoomed=zoomed)

    reading = DeskScanner(objects, FakeFaceDetector()).scan(np.zeros((480, 640, 3), np.uint8))

    assert [d.label for d in reading.phones] == ["phone"]
    assert reading.people == [person]


def test_scanner_skips_the_zoom_without_a_clear_person():
    unsure_person = Detection("person", 0.4, Box(x1=300, y1=150, x2=500, y2=450))
    objects = FakeObjectDetector(full_frame=[unsure_person], zoomed=[])

    reading = DeskScanner(objects, FakeFaceDetector()).scan(np.zeros((480, 640, 3), np.uint8))

    assert len(objects.shapes) == 1
    assert reading.phones == []


class ColorPatchNet:
    """Stands in for the YOLO net: white pixels are a person and pure red ones a phone, boxed in model-input pixels."""

    def setInput(self, blob: np.ndarray) -> None:
        self.blob = blob

    def forward(self) -> np.ndarray:
        red, green, blue = self.blob[0]  # make_blob hands over RGB
        masks = {
            detector.PERSON_CLASS_ID: (red > 0.9) & (green > 0.9) & (blue > 0.9),
            detector.PHONE_CLASS_ID: (red > 0.9) & (green < 0.1) & (blue < 0.1),
        }
        anchors = []
        for class_id, mask in masks.items():
            rows, columns = np.nonzero(mask)
            if len(rows) > 0:
                left, right, top, bottom = columns.min(), columns.max() + 1, rows.min(), rows.max() + 1
                center_box = ((left + right) / 2, (top + bottom) / 2, right - left, bottom - top)
                anchors.append({"box": center_box, "scores": {class_id: 0.9}})
        output = make_output(anchors)
        return output


def test_a_16_9_frame_gets_its_boxes_back_where_they_were_drawn(monkeypatch):
    # The Pi camera's 768x432 reaches the model shrunk to 640x360, with 60 px of padding above and below.
    monkeypatch.setattr(detector.cv2.dnn, "readNetFromONNX", lambda path: ColorPatchNet())
    frame = np.zeros((432, 768, 3), np.uint8)
    frame[60:400, 420:760] = (255, 255, 255)
    frame[300:340, 690:740] = (0, 0, 255)  # BGR red, out past where a 4:3 crop would have cut the frame off

    reading = DeskScanner(face_detector=FakeFaceDetector()).scan(frame)

    assert len(reading.people) == 1
    assert len(reading.phones) == 1
    person, phone = reading.people[0].box, reading.phones[0].box
    assert [person.x1, person.y1, person.x2, person.y2] == pytest.approx([420, 60, 760, 400], abs=2)
    assert [phone.x1, phone.y1, phone.x2, phone.y2] == pytest.approx([690, 300, 740, 340], abs=2)


@pytest.mark.skipif(
    not (detector.OBJECT_MODEL_PATH.exists() and detector.FACE_MODEL_PATH.exists()),
    reason="model files not in models/",
)
@pytest.mark.parametrize("shape", [(480, 640, 3), (432, 768, 3)])
def test_real_models_find_nothing_in_a_blank_frame(shape):
    reading = DeskScanner().scan(np.full(shape, 128, np.uint8))
    assert reading.people == []
    assert reading.phones == []
    assert reading.faces == []
    assert reading.elapsed_ms > 0
