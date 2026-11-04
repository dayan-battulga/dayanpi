from dayanpi.focus.merge import merge_readings
from dayanpi.vision.detector import Box, Detection, FaceReading, FrameReading, Point

BOX = Box(10, 10, 50, 50)
FRONT_FACE = FaceReading(0.9, BOX, [Point(20, 20)] * 5, turn=0.1, tilt=0.4)
SIDE_FACE = FaceReading(0.8, BOX, [Point(30, 30)] * 5, turn=0.9, tilt=0.7)
FRONT_POSE = "front pose"
SIDE_POSE = "side pose"


def make_reading(camera: str, face: FaceReading, pose: str, elapsed_ms: float) -> FrameReading:
    reading = FrameReading(
        people=[Detection(f"{camera} person", 0.9, BOX)],
        phones=[Detection(f"{camera} phone", 0.6, BOX)],
        faces=[face],
        elapsed_ms=elapsed_ms,
        food=[Detection(f"{camera} food", 0.5, BOX)],
        drinks=[Detection(f"{camera} drink", 0.4, BOX)],
        poses=[pose],
    )
    return reading


def read_labels(detections: list[Detection]) -> list[str]:
    labels = [detection.label for detection in detections]
    return labels


def test_both_cameras_share_people_phones_food_and_drinks_but_only_the_front_has_faces_and_poses():
    front = make_reading("front", FRONT_FACE, FRONT_POSE, 200.0)
    side = make_reading("side", SIDE_FACE, SIDE_POSE, 180.0)
    merged = merge_readings(front, side)
    assert read_labels(merged.people) == ["front person", "side person"]
    assert read_labels(merged.phones) == ["front phone", "side phone"]
    assert read_labels(merged.food) == ["front food", "side food"]
    assert read_labels(merged.drinks) == ["front drink", "side drink"]
    assert merged.faces == [FRONT_FACE]
    assert merged.poses == [FRONT_POSE]
    assert merged.elapsed_ms == 380.0
    assert merged.side is side


def test_merging_leaves_both_readings_alone():
    front = make_reading("front", FRONT_FACE, FRONT_POSE, 200.0)
    side = make_reading("side", SIDE_FACE, SIDE_POSE, 180.0)
    merge_readings(front, side)
    assert read_labels(front.people) == ["front person"]
    assert read_labels(side.people) == ["side person"]
    assert front.side is None


def test_only_the_front_camera_returns_its_reading_untouched():
    front = make_reading("front", FRONT_FACE, FRONT_POSE, 200.0)
    assert merge_readings(front, None) is front


def test_only_the_side_camera_gives_its_finds_with_no_faces_or_poses():
    side = make_reading("side", SIDE_FACE, SIDE_POSE, 180.0)
    merged = merge_readings(None, side)
    assert read_labels(merged.people) == ["side person"]
    assert read_labels(merged.phones) == ["side phone"]
    assert read_labels(merged.food) == ["side food"]
    assert read_labels(merged.drinks) == ["side drink"]
    assert merged.faces == []
    assert merged.poses == []
    assert merged.elapsed_ms == 180.0
    assert merged.side is side


def test_neither_camera_means_no_reading():
    assert merge_readings(None, None) is None
