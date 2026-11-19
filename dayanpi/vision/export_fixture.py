"""Writes what the Pi's vision code makes of some made-up inputs to web/src/lib/vision/python-fixture.json.

The browser's port (web/src/lib/vision/) runs the same inputs in its tests and has to come out the same, so the
two can't drift apart. Run it after changing anything in vision/, then `npm test` in web/:

    .venv/bin/python -m dayanpi.vision.export_fixture

tests/test_vision_fixture.py fails while the file is out of date.
"""

import json
import math
from pathlib import Path

import cv2
import numpy as np

from dayanpi.vision import detector, gestures, hands
from dayanpi.vision.detector import Box, Detection

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "vision" / "python-fixture.json"
SEED = 7
# Every section but these is plain arithmetic. These two are OpenCV's pixel code, which rounds a level or two
# differently from one OpenCV version to the next.
PIXEL_SECTIONS = ("resize", "warp")

# (width, height). 1280x5 and 384x5 land on an exact .5 when shrunk, where Python's round() goes to even.
FRAME_SIZES = [(640, 480), (768, 432), (1280, 720), (301, 217), (1000, 999), (90, 400), (333, 250), (1280, 5), (384, 5)]
RESIZE_TARGETS = [(11, 9), (4, 3), (8, 6), (3, 10), (16, 12), (5, 2)]
PERSON = detector.PERSON_CLASS_ID
PHONE = detector.PHONE_CLASS_ID
MOUSE = detector.MOUSE_CLASS_ID
# Made-up YOLO anchors: (cx, cy, w, h, {class: score}). The rest of the anchors are noise under the cutoff.
YOLO_ANCHORS = [
    (320, 240, 200, 300, {PERSON: 0.9}),
    (330, 250, 190, 290, {PERSON: 0.8}),  # mostly the first box: gone
    (386, 240, 200, 300, {PERSON: 0.75}),  # IoU 0.504 with the first: gone
    (388, 240, 200, 300, {PERSON: 0.7}),  # IoU 0.493: stays
    (600, 50, 30, 30, {PERSON: 0.15}),  # exactly the cutoff: NMSBoxes wants more than it
    (600, 150, 30, 30, {PERSON: 0.1499}),
    (40, 60, 20, 20, {PERSON: 0.6}),  # two equal scores far apart: both stay, in anchor order
    (40, 300, 20, 20, {PERSON: 0.6}),
    (500, 400, 40, 80, {PHONE: 0.6}),
    (504, 404, 40, 80, {PHONE: 0.55}),  # on top of that phone: gone
    (100, 400, 40, 30, {MOUSE: 0.7, PHONE: 0.65}),  # more mouse than phone: a mouse, not a phone
    (104, 402, 36, 28, {PHONE: 0.5}),  # a phone of its own under that mouse: the mouse veto drops it
    (320, 240, 60, 90, {PHONE: 0.3}),  # inside the person: NMS is per class, so it stays
    (320, 20, 50, 50, {PERSON: 0.4}),  # in the letterbox's padding: lands above the frame
]
YOLO_NOISE_ANCHORS = 19
ZOOM_CASES = [
    ((100.5, 50.2, 400.7, 470.9), 640, 480),
    ((-20.0, -5.0, 300.0, 200.0), 640, 480),
    ((500.0, 300.0, 700.0, 520.0), 640, 480),
    ((0.0, 0.0, 768.0, 432.0), 768, 432),
    ((10.99, 20.01, 11.5, 30.0), 640, 480),
]
# Made-up palm rows: (anchor index, score logit). Each gets a random box and points around its anchor.
PALM_ANCHORS = [
    (300, 3.0),
    (301, 2.0),  # the same cell's second anchor, nearly the same box: gone
    (1500, 1.0),
    (900, 0.2),  # 0.55, under the cutoff
    (1000, 0.5),  # kept by the cutoff and NMS, cut by MAX_HANDS
    (2015, math.log(0.6 / 0.4)),  # right at the cutoff
]
# Two more palms by hand: fingers pointing left, and down.
EXTRA_PALM_POINTS = [
    [[300, 200], [260, 180], [250, 200], [252, 214], [256, 226], [290, 230], [276, 220]],
    [[100, 50], [90, 90], [100, 95], [110, 92], [118, 88], [80, 60], [85, 75]],
]
# (phone box, its score, mouse box, its score), each pair far from the others.
MOUSE_VETO_CASES = [
    ((100, 100, 140, 180), 0.6, (105, 110, 145, 185), 0.7),  # the mouse scored higher on top of it: gone
    ((300, 100, 340, 180), 0.6, (305, 110, 345, 185), 0.55),  # a weaker mouse: stays
    ((500, 100, 540, 180), 0.6, (10, 400, 50, 440), 0.9),  # a stronger mouse somewhere else: stays
    ((100, 300, 120, 340), 0.62, (80, 280, 200, 400), 0.62),  # a tie, IoU 0.06 but its center inside: gone
    ((300, 300, 340, 340), 0.6, (321, 300, 361, 340), 0.8),  # IoU 0.311, center just outside: gone
    ((500, 300, 540, 340), 0.6, (522, 300, 562, 340), 0.8),  # IoU 0.290, center outside: stays
    ((200.5, 200.25, 230.75, 250.5), 0.66, (205.125, 199.5, 240.0, 248.875), 0.66),  # fractions, center inside
]
HAND_CONFIDENCES = [0.93, 0.8, 0.79]
NEAR_PHONES = [(150, 100, 170, 120), (161, 100, 180, 120), (160, 100, 180, 120), (60, 200, 79, 230), (400, 400, 420, 440), (285, 35, 300, 60)]
SIGN_STEPS_RANDOM = 40
SIGN_SEQUENCES = [
    [("peace", 0.0), ("peace", 0.5), ("peace", 1.0), ("peace", 2.0)],
    [("peace", 0.0), (None, 0.6), ("peace", 1.1)],
    [("peace", 0.0), (None, 0.5), (None, 1.0), ("peace", 1.5), ("peace", 2.4), ("peace", 2.5)],
    [("peace", 0.0), ("peace", 1.0), (None, 2.0), ("peace", 3.0), ("peace", 4.5), (None, 5.0), (None, 6.0), ("peace", 7.0), ("peace", 8.0)],
]


def write_float32(values) -> list[float]:
    """float32 values as their shortest decimals: Float32Array reads them back to the same bits, and the JSON stays small."""
    written = [float(str(value)) for value in np.asarray(values, dtype=np.float32).ravel()]
    return written


def describe_box(box: Box) -> dict:
    described = {"x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2}
    return described


def describe_detection(detection: Detection) -> dict:
    described = {"label": detection.label, "confidence": detection.confidence, "box": describe_box(detection.box)}
    return described


def describe_letterboxes() -> list[dict]:
    cases = []
    for width, height in FRAME_SIZES:
        image = np.zeros((height, width, 3), np.uint8)
        full = detector.fit_to_input(image)
        square = hands.fit_square(image, hands.PALM_INPUT_SIZE)
        cases.append(
            {
                "width": width,
                "height": height,
                "input": {"scale": full.scale, "pad_left": full.pad_left, "pad_top": full.pad_top},
                "palm": {"scale": square.scale, "pad_left": square.pad_left, "pad_top": square.pad_top},
            }
        )
    return cases


def describe_resizes(rng: np.random.Generator) -> dict:
    source = rng.integers(0, 256, (6, 8, 3), dtype=np.uint8)
    resized = [
        {"width": width, "height": height, "data": cv2.resize(source, (width, height)).ravel().tolist()}
        for width, height in RESIZE_TARGETS
    ]
    section = {"source": {"width": 8, "height": 6, "data": source.ravel().tolist()}, "results": resized}
    return section


def describe_warp() -> dict:
    rows, columns = np.mgrid[0:16, 0:20]
    channels = [128 + 100 * np.sin(columns / 3) * np.cos(rows / 4), 128 + 90 * np.cos(columns / 5), 60 + 3 * rows + 4 * columns]
    source = np.stack(channels, axis=-1).round().clip(0, 255).astype(np.uint8)
    warp = cv2.getRotationMatrix2D((9.3, 7.1), 33.0, 1.4)
    warp[:, 2] += [-2.0, 1.5]
    warped = cv2.warpAffine(source, warp, (14, 12))
    section = {
        "source": {"width": 20, "height": 16, "data": source.ravel().tolist()},
        "warp": warp.tolist(),
        "result": {"width": 14, "height": 12, "data": warped.ravel().tolist()},
    }
    return section


def describe_objects(rng: np.random.Generator) -> dict:
    count = len(YOLO_ANCHORS) + YOLO_NOISE_ANCHORS
    output = rng.uniform(0, 0.1, (detector.BOX_VALUES + 80, count)).astype(np.float32)
    output[:2] = rng.uniform(0, 640, (2, count))
    output[2:4] = rng.uniform(5, 120, (2, count))
    for index, (cx, cy, width, height, scores) in enumerate(YOLO_ANCHORS):
        output[:4, index] = [cx, cy, width, height]
        for class_id, score in scores.items():
            output[detector.BOX_VALUES + class_id, index] = score
    letterbox = detector.fit_to_input(np.zeros((432, 768, 3), np.uint8))
    detections = detector.decode_objects(output[np.newaxis], letterbox)
    section = {
        "output": write_float32(output),
        "letterbox": {"scale": letterbox.scale, "pad_left": letterbox.pad_left, "pad_top": letterbox.pad_top},
        "detections": [describe_detection(found) for found in detections],
    }
    return section


def describe_zooms() -> list[dict]:
    cases = [
        {
            "person": describe_box(Box(*person)),
            "width": width,
            "height": height,
            "region": describe_box(detector.find_zoom_region(Box(*person), width, height)),
        }
        for person, width, height in ZOOM_CASES
    ]
    return cases


def describe_palms(rng: np.random.Generator) -> dict:
    anchors = hands.build_anchors()
    rows = np.zeros((len(anchors), 18), np.float32)
    logits = np.full(len(anchors), -10.0, np.float32)
    for index, logit in PALM_ANCHORS:
        rows[index, :2] = rng.uniform(-3, 3, 2)
        rows[index, 2:4] = rng.uniform(25, 45, 2)
        rows[index, 4:] = rng.uniform(-30, 30, 14)
        logits[index] = logit
    # The same cell's two anchors share most of their box, so NMS has something to drop.
    rows[301, :4] = rows[300, :4] + [1, 0, -2, 1]
    letterbox = hands.fit_square(np.zeros((480, 640, 3), np.uint8), hands.PALM_INPUT_SIZE)
    palms = hands.decode_palms((rows[np.newaxis], logits[np.newaxis, :, np.newaxis]), letterbox, anchors)
    section = {
        "anchor_count": len(anchors),
        "anchor_samples": {str(index): anchors[index].tolist() for index in (0, 1, 2, 47, 48, 1151, 1152, 1157, 1158, 2015)},
        "specials": [{"index": index, "logit": write_float32([logits[index]])[0], "row": write_float32(rows[index])} for index, _ in PALM_ANCHORS],
        "letterbox": {"scale": letterbox.scale, "pad_left": letterbox.pad_left, "pad_top": letterbox.pad_top},
        "palms": [{"confidence": palm.confidence, "box": describe_box(palm.box), "points": palm.points.tolist()} for palm in palms],
    }
    return section


def describe_hands(rng: np.random.Generator, palm_points: list[list[list[float]]]) -> dict:
    palms = [hands.Palm(confidence=1.0, box=Box(0, 0, 0, 0), points=np.array(points, dtype=np.float64)) for points in palm_points + EXTRA_PALM_POINTS]
    crops = [{"points": palm.points.tolist(), "warp": hands.find_hand_crop(palm).tolist()} for palm in palms]
    joints = rng.uniform(0, 224, 63).astype(np.float32)
    warp = hands.find_hand_crop(palms[0])
    decoded = []
    for confidence in HAND_CONFIDENCES:
        hand = hands.decode_hand((joints[np.newaxis], np.array([[confidence]], np.float32)), warp)
        decoded.append(
            {
                "confidence": write_float32([confidence])[0],
                "hand": None if hand is None else {"confidence": hand.confidence, "joints": hand.joints.tolist()},
            }
        )
    section = {"crops": crops, "joints": write_float32(joints), "warp": warp.tolist(), "decoded": decoded}
    return section


def build_hand(low: tuple, high: tuple) -> hands.Hand:
    """A hand whose joints span low..high: the box is all find_phones_in_hand reads."""
    joints = np.zeros((hands.JOINTS, 3))
    joints[:, :2] = low
    joints[1, :2] = high
    joints[2, :2] = ((low[0] + high[0]) / 2, (low[1] + high[1]) / 2)
    hand = hands.Hand(confidence=0.9, joints=joints)
    return hand


def describe_phones_in_hand() -> dict:
    held_by = [build_hand((100, 100), (140, 180)), build_hand((250, 40), (270, 50))]
    phones = [Detection(label="phone", confidence=0.5 + index / 100, box=Box(*box)) for index, box in enumerate(NEAR_PHONES)]
    held = hands.find_phones_in_hand(phones, held_by)
    section = {
        "hands": [hand.joints.tolist() for hand in held_by],
        "phones": [describe_detection(phone) for phone in phones],
        "held": [describe_detection(phone) for phone in held],
    }
    return section


def describe_mouse_veto() -> dict:
    phones = [Detection(label="phone", confidence=score, box=Box(*box)) for box, score, _, _ in MOUSE_VETO_CASES]
    mice = [Detection(label="mouse", confidence=score, box=Box(*box)) for _, _, box, score in MOUSE_VETO_CASES]
    section = {
        "phones": [describe_detection(phone) for phone in phones],
        "mice": [describe_detection(mouse) for mouse in mice],
        "overlaps": [detector.measure_overlap(phone.box, mouse.box) for phone, mouse in zip(phones, mice, strict=True)],
        "kept": [describe_detection(phone) for phone in detector.drop_mouse_phones(phones, mice)],
    }
    return section


def build_finger_hand(open_fingers: set[str], spread: float, turn_degrees: float = 0.0, depth: float = 0.0) -> np.ndarray:
    """A hand drawn by hand: wrist at the bottom, each finger straight up when open and curled back when closed."""
    joints = np.zeros((hands.JOINTS, 3))
    joints[1:5] = [[-20, -10, 0], [-30, -20, 0], [-36, -30, 0], [-40, -38, 0]]
    bases = {"index": (5, -15), "middle": (9, -5), "ring": (13, 5), "pinky": (17, 15)}
    for finger, (base, x) in bases.items():
        lean = {"index": -spread, "middle": spread}.get(finger, 0.0)
        if finger in open_fingers:
            joints[base : base + 4] = [[x, -40, 0], [x + lean / 2, -60, 0], [x + lean * 0.75, -70, 0], [x + lean, -80, 0]]
        else:
            joints[base : base + 4] = [[x, -40, 0], [x, -55, 0], [x, -45, 0], [x, -35, 0]]
    angle = math.radians(turn_degrees)
    turn = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    joints[:, :2] = joints[:, :2] @ turn.T + [300, 200]
    joints[:, 2] = depth * np.sin(np.arange(hands.JOINTS))
    return joints


def describe_shapes(rng: np.random.Generator) -> dict:
    drawn = [
        build_finger_hand({"index", "middle"}, spread=12),  # peace
        build_finger_hand({"index", "middle"}, spread=0),  # two fingers side by side
        build_finger_hand(set(), spread=0),  # fist
        build_finger_hand({"index", "middle", "ring", "pinky"}, spread=12),  # open hand
        build_finger_hand({"index"}, spread=12),
        build_finger_hand({"index", "middle"}, spread=12, turn_degrees=90, depth=8),  # peace, sideways
    ]
    random_hands = [rng.uniform(-100, 100, (hands.JOINTS, 3)) for _ in range(30)]
    cases = [
        {
            "joints": joints.tolist(),
            "shape": gestures.read_hand_shape(joints),
            "sign": gestures.read_sign([hands.Hand(confidence=0.9, joints=joints)]),
        }
        for joints in drawn + random_hands
    ]
    together = [hands.Hand(confidence=0.9, joints=joints) for joints in (drawn[2], drawn[0])]
    section = {"cases": cases, "fist_then_peace_sign": gestures.read_sign(together), "no_hands_sign": gestures.read_sign([])}
    return section


def describe_holds(rng: np.random.Generator) -> list[dict]:
    sequences = list(SIGN_SEQUENCES)
    for _ in range(5):
        times = np.cumsum(rng.uniform(0.3, 1.4, SIGN_STEPS_RANDOM))
        picks = rng.random(SIGN_STEPS_RANDOM) < 0.6
        sequences.append([("peace" if pick else None, round(float(now), 3)) for pick, now in zip(picks, times)])
    cases = []
    for steps in sequences:
        tracker = gestures.GestureTracker()
        fired = [tracker.hold(gesture, now) for gesture, now in steps]
        cases.append({"steps": [{"gesture": gesture, "now": now} for gesture, now in steps], "fired": fired})
    return cases


def build_fixture() -> dict:
    """Plain JSON values only, so a fresh build compares equal to the saved file."""
    rng = np.random.default_rng(SEED)
    palms = describe_palms(rng)
    fixture = {
        "letterboxes": describe_letterboxes(),
        "resize": describe_resizes(rng),
        "warp": describe_warp(),
        "objects": describe_objects(rng),
        "zooms": describe_zooms(),
        "palms": palms,
        "hands": describe_hands(rng, [palm["points"] for palm in palms["palms"]]),
        "phones_in_hand": describe_phones_in_hand(),
        "mouse_veto": describe_mouse_veto(),
        "shapes": describe_shapes(rng),
        "holds": describe_holds(rng),
    }
    plain = json.loads(json.dumps(fixture))
    return plain


def main() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(build_fixture(), separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
