import logging
import time

import cv2
import numpy as np
import pytest

from dayanpi.vision import detector
from dayanpi.focus import worker as focus_worker
from dayanpi.vision.detector import Box, Detection, FaceReading, FrameReading, Point
from dayanpi.focus.tracker import FocusTracker
from dayanpi.focus.worker import FocusWorker
from dayanpi.vision.hands import Hand

NOON = 1_800_000_000.0


def fake_jpeg() -> bytes:
    encoded = cv2.imencode(".jpg", np.full((480, 640, 3), 90, np.uint8))[1].tobytes()
    return encoded


class FakeStream:
    """Hands out a new frame id on every call, like a live camera; frozen=True repeats the same id."""

    def __init__(self, jpeg: bytes | None, frozen: bool = False) -> None:
        self.jpeg = jpeg
        self.frozen = frozen
        self.frame_id = 0
        self.asked: list[int] = []

    def frame_after(self, last_id: int, timeout: float):
        self.asked.append(last_id)
        result = None
        if self.jpeg is not None:
            if not self.frozen:
                self.frame_id += 1
            if self.frame_id > last_id:
                result = (self.jpeg, self.frame_id)
        return result


class FakeScanner:
    def __init__(self, phone: float = 0.0, fail: bool = False, mouse: float = 0.0) -> None:
        self.phone = phone
        self.mouse = mouse
        self.fail = fail
        self.scans = 0

    def scan(self, image: np.ndarray) -> FrameReading:
        self.scans += 1
        if self.fail:
            raise RuntimeError("model exploded")
        box = Box(100, 100, 300, 400)
        phones = [Detection("phone", self.phone, box)] if self.phone else []
        mice = [Detection("mouse", self.mouse, box)] if self.mouse else []
        reading = FrameReading([Detection("person", 0.9, box)], phones, [], 120.0, mice=mice)
        return reading


def test_run_once_feeds_the_tracker_and_the_hook():
    tracker = FocusTracker(started_at=NOON)
    seen = []
    worker = FocusWorker(FakeStream(fake_jpeg()), FakeScanner(), tracker, on_update=lambda update, now: seen.append((update.state, now)))
    worker.run_once(NOON + 1)
    update = worker.run_once(NOON + 2)
    assert update.state == "working"
    assert seen[-1] == ("working", NOON + 2)
    assert worker.checks == 2
    assert tracker.status(NOON + 2)["camera_ok"] is True


@pytest.mark.parametrize("mouse, state", [(0.9, "working"), (0.7, "phone")])
def test_a_phone_a_mouse_outscores_in_the_same_place_never_reaches_the_tracker(mouse, state):
    tracker = FocusTracker(started_at=NOON)
    worker = FocusWorker(FakeStream(fake_jpeg()), FakeScanner(phone=0.8, mouse=mouse), tracker)
    for second in range(1, 8):
        update = worker.run_once(NOON + second)
    assert update.state == state


def test_no_frame_counts_as_no_reading():
    tracker = FocusTracker(started_at=NOON)
    scanner = FakeScanner()
    worker = FocusWorker(FakeStream(None), scanner, tracker)
    worker.run_once(NOON + 1)
    assert scanner.scans == 0
    assert tracker.status(NOON + 1)["camera_ok"] is False
    assert worker.last_overlay is None


def test_each_check_leaves_boxes_for_the_feed():
    tracker = FocusTracker(started_at=NOON)
    worker = FocusWorker(FakeStream(fake_jpeg()), FakeScanner(phone=0.6), tracker)
    worker.run_once(NOON + 1)
    overlay = worker.last_overlay
    assert (overlay["frame_width"], overlay["frame_height"], overlay["at"]) == (640, 480, NOON + 1)
    assert [box["kind"] for box in overlay["boxes"]] == ["person", "phone"]
    person = overlay["boxes"][0]
    assert (person["x"], person["y"], person["width"], person["height"]) == pytest.approx((100 / 640, 100 / 480, 200 / 640, 300 / 480), abs=1e-4)


def test_boxes_stay_from_the_last_good_check_when_the_camera_freezes():
    tracker = FocusTracker(started_at=NOON)
    stream = FakeStream(fake_jpeg())
    worker = FocusWorker(stream, FakeScanner(), tracker)
    worker.run_once(NOON + 1)
    stream.frozen = True
    worker.run_once(NOON + 2)
    assert worker.last_overlay["at"] == NOON + 1


def test_scanner_errors_are_logged_and_survived(caplog):
    tracker = FocusTracker(started_at=NOON)
    worker = FocusWorker(FakeStream(fake_jpeg()), FakeScanner(fail=True), tracker)
    with caplog.at_level(logging.ERROR):
        for second in range(1, 4):
            update = worker.run_once(NOON + second)
    assert update.state == "unknown"
    assert worker.front.failures == 3
    assert caplog.text.count("focus check failed") == 1


def test_hook_errors_do_not_stop_the_worker(caplog):
    tracker = FocusTracker(started_at=NOON)

    def bad_hook(update, now):
        raise ValueError("boom")

    worker = FocusWorker(FakeStream(fake_jpeg()), FakeScanner(), tracker, on_update=bad_hook)
    with caplog.at_level(logging.ERROR):
        worker.run_once(NOON + 1)
    assert worker.checks == 1
    assert "focus update hook failed" in caplog.text


def test_start_and_stop_run_the_loop():
    tracker = FocusTracker(started_at=NOON)
    clock = iter(range(1, 10_000))
    worker = FocusWorker(FakeStream(fake_jpeg()), FakeScanner(), tracker, clock=lambda: NOON + next(clock), interval_s=0.01)
    worker.start()
    assert worker.running
    deadline = time.monotonic() + 2.0
    while worker.checks < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    assert worker.checks >= 3
    assert not worker.running
    assert worker.last_update.state == "working"


def test_a_frozen_camera_stops_counting_after_thirty_seconds():
    tracker = FocusTracker(started_at=NOON)
    stream = FakeStream(fake_jpeg())
    scanner = FakeScanner()
    worker = FocusWorker(stream, scanner, tracker)
    for second in range(1, 4):
        worker.run_once(NOON + second)
    assert worker.last_update.state == "working"
    stream.frozen = True  # the webcam hangs and keeps serving the same JPEG
    for second in range(4, 40):
        worker.run_once(NOON + second)
    assert scanner.scans == 3, "a stale frame must not be re-scanned"
    assert worker.last_update.state == "unknown"
    assert tracker.status(NOON + 40)["camera_ok"] is False


def test_a_broken_tick_does_not_kill_the_loop(caplog):
    import logging

    tracker = FocusTracker(started_at=NOON)
    worker = FocusWorker(FakeStream(fake_jpeg()), FakeScanner(), tracker, interval_s=0.01)
    worker.run_once = lambda now: (_ for _ in ()).throw(RuntimeError("boom"))
    with caplog.at_level(logging.ERROR):
        worker.start()
        deadline = time.monotonic() + 1.0
        while worker.tick_failures < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        worker.stop()
    assert worker.tick_failures >= 3
    assert caplog.text.count("tick failed") == 1


def test_wait_for_clock_returns_when_the_sync_file_appears(tmp_path):
    synced = tmp_path / "run" / "systemd" / "timesync" / "synchronized"
    synced.parent.mkdir(parents=True)
    assert focus_worker.wait_for_clock(synced, timeout_s=0.2, poll_s=0.01) is False
    synced.write_text("")
    assert focus_worker.wait_for_clock(synced, timeout_s=0.2, poll_s=0.01) is True


def test_wait_for_clock_skips_machines_without_timesyncd(tmp_path):
    started = time.monotonic()
    assert focus_worker.wait_for_clock(tmp_path / "nope" / "systemd" / "timesync" / "synchronized", timeout_s=5.0, poll_s=0.01) is False
    assert time.monotonic() - started < 1.0


def test_build_scanner_loads_the_plain_scanner(monkeypatch, tmp_path):
    monkeypatch.setattr(focus_worker, "DeskScanner", lambda: "plain-scanner")
    monkeypatch.setattr(detector, "OBJECT_MODEL_PATH", tmp_path / "yolo.onnx")
    monkeypatch.setattr(detector, "FACE_MODEL_PATH", tmp_path / "face.onnx")
    (tmp_path / "yolo.onnx").write_bytes(b"x")
    (tmp_path / "face.onnx").write_bytes(b"x")
    assert focus_worker.build_scanner() == "plain-scanner"


def test_build_scanner_is_none_without_model_files(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(detector, "OBJECT_MODEL_PATH", tmp_path / "missing.onnx")
    with caplog.at_level(logging.WARNING):
        assert focus_worker.build_scanner() is None
    assert "missing.onnx" in caplog.text


# ----- both cameras -----

FRONT_BOX = Box(100, 100, 300, 400)
SIDE_BOX = Box(32, 24, 160, 120)
FRONT_BRIGHTNESS = 90  # what fake_jpeg() makes
SIDE_BRIGHTNESS = 200


def side_jpeg() -> bytes:
    """Half the size and much brighter, so the scanner and the overlays can tell it from the front."""
    encoded = cv2.imencode(".jpg", np.full((240, 320, 3), SIDE_BRIGHTNESS, np.uint8))[1].tobytes()
    return encoded


def find_camera(image: np.ndarray) -> str:
    camera = "side" if image.mean() > (FRONT_BRIGHTNESS + SIDE_BRIGHTNESS) / 2 else "front"
    return camera


def make_view(box: Box, phone: float = 0.0, faces: tuple = ()) -> FrameReading:
    phones = [Detection("phone", phone, box)] if phone else []
    view = FrameReading([Detection("person", 0.9, box)], phones, list(faces), 100.0)
    return view


class TwoCameraScanner:
    """Tells the cameras apart by frame brightness and hands back what each one "sees"."""

    def __init__(self, front: FrameReading | None = None, side: FrameReading | None = None, failing: str | None = None) -> None:
        self.views = {"front": front or make_view(FRONT_BOX), "side": side or make_view(SIDE_BOX)}
        self.failing = failing
        self.scans = {"front": 0, "side": 0}

    def scan(self, image: np.ndarray) -> FrameReading:
        camera = find_camera(image)
        self.scans[camera] += 1
        if camera == self.failing:
            raise RuntimeError(f"{camera} model exploded")
        view = self.views[camera]
        return view


def test_one_camera_has_no_side_anything():
    tracker = FocusTracker(started_at=NOON)
    worker = FocusWorker(FakeStream(fake_jpeg()), FakeScanner(), tracker)
    worker.run_once(NOON + 1)
    assert worker.side is None
    assert worker.last_side_overlay is None
    assert tracker.status(NOON + 1)["last_check"]["side_person"] is None


def test_a_phone_only_the_side_camera_sees_counts_as_on_phone():
    tracker = FocusTracker(started_at=NOON)
    scanner = TwoCameraScanner(side=make_view(SIDE_BOX, phone=0.6))
    worker = FocusWorker(FakeStream(fake_jpeg()), scanner, tracker, side_stream=FakeStream(side_jpeg()))
    for second in range(1, 4):
        update = worker.run_once(NOON + second)
    assert update.state == "phone"
    assert scanner.scans == {"front": 3, "side": 3}
    check = tracker.status(NOON + 3)["last_check"]
    assert (check["phone"], check["side_phone"], check["side_person"]) == (0.6, 0.6, 0.9)


def test_each_camera_is_asked_for_frames_after_its_own_last_id():
    front = FakeStream(fake_jpeg())
    side = FakeStream(side_jpeg())
    side.frame_id = 100
    worker = FocusWorker(front, TwoCameraScanner(), FocusTracker(started_at=NOON), side_stream=side)
    for second in range(1, 4):
        worker.run_once(NOON + second)
    assert front.asked == [-1, 1, 2]
    assert side.asked == [-1, 101, 102]


def test_each_overlay_holds_only_its_own_cameras_boxes_at_its_own_frame_size():
    scanner = TwoCameraScanner(side=make_view(SIDE_BOX, phone=0.6))
    worker = FocusWorker(FakeStream(fake_jpeg()), scanner, FocusTracker(started_at=NOON), side_stream=FakeStream(side_jpeg()))
    worker.run_once(NOON + 1)
    front_overlay = worker.last_overlay
    side_overlay = worker.last_side_overlay
    assert [box["kind"] for box in front_overlay["boxes"]] == ["person"]
    assert [box["kind"] for box in side_overlay["boxes"]] == ["person", "phone"]
    assert (front_overlay["frame_width"], front_overlay["frame_height"]) == (640, 480)
    assert (side_overlay["frame_width"], side_overlay["frame_height"]) == (320, 240)
    assert front_overlay["boxes"][0]["x"] == pytest.approx(100 / 640, abs=1e-4)
    assert side_overlay["boxes"][0]["x"] == pytest.approx(32 / 320, abs=1e-4)


def test_a_frozen_side_camera_counts_as_no_frame_for_that_camera():
    tracker = FocusTracker(started_at=NOON)
    side = FakeStream(side_jpeg())
    scanner = TwoCameraScanner()
    worker = FocusWorker(FakeStream(fake_jpeg()), scanner, tracker, side_stream=side)
    for second in range(1, 4):
        worker.run_once(NOON + second)
    assert tracker.status(NOON + 3)["last_check"]["side_person"] == 0.9
    side.frozen = True  # the side camera hangs and keeps serving the same frame
    for second in range(4, 40):
        worker.run_once(NOON + second)
    assert scanner.scans == {"front": 39, "side": 3}, "a stale side frame must not be re-scanned"
    assert worker.last_side_overlay["at"] == NOON + 3
    assert worker.last_overlay["at"] == NOON + 39
    assert worker.last_update.state == "working"
    assert tracker.status(NOON + 39)["last_check"]["side_person"] is None


def test_a_frozen_front_camera_keeps_tracking_from_the_side_without_faces():
    tracker = FocusTracker(started_at=NOON)
    front = FakeStream(fake_jpeg())
    face = FaceReading(0.9, FRONT_BOX, [Point(200, 200)] * 5, turn=0.1, tilt=0.4)
    scanner = TwoCameraScanner(front=make_view(FRONT_BOX, faces=(face,)))
    worker = FocusWorker(front, scanner, tracker, side_stream=FakeStream(side_jpeg()))
    for second in range(1, 4):
        worker.run_once(NOON + second)
    assert tracker.status(NOON + 3)["last_check"]["turn"] == 0.1
    front.frozen = True
    for second in range(4, 40):
        worker.run_once(NOON + second)
    status = tracker.status(NOON + 39)
    assert scanner.scans == {"front": 3, "side": 39}
    assert worker.last_update.state == "working"
    assert status["camera_ok"] is True
    assert status["last_check"]["turn"] is None
    assert worker.last_overlay["at"] == NOON + 3
    assert worker.last_side_overlay["at"] == NOON + 39


def test_both_cameras_frozen_goes_unknown_after_thirty_seconds():
    tracker = FocusTracker(started_at=NOON)
    front = FakeStream(fake_jpeg())
    side = FakeStream(side_jpeg())
    scanner = TwoCameraScanner()
    worker = FocusWorker(front, scanner, tracker, side_stream=side)
    for second in range(1, 4):
        worker.run_once(NOON + second)
    assert worker.last_update.state == "working"
    front.frozen = True
    side.frozen = True
    for second in range(4, 40):
        worker.run_once(NOON + second)
    assert scanner.scans == {"front": 3, "side": 3}
    assert worker.last_update.state == "unknown"
    assert tracker.status(NOON + 40)["camera_ok"] is False


@pytest.mark.parametrize(("failing", "healthy"), [("side", "front"), ("front", "side")])
def test_one_camera_failing_leaves_the_other_working_and_the_log_quiet(caplog, failing, healthy):
    scanner = TwoCameraScanner(failing=failing)
    worker = FocusWorker(FakeStream(fake_jpeg()), scanner, FocusTracker(started_at=NOON), side_stream=FakeStream(side_jpeg()))
    with caplog.at_level(logging.ERROR):
        for second in range(1, 5):
            update = worker.run_once(NOON + second)
    assert update.state == "working"
    assert getattr(worker, failing).failures == 4
    assert getattr(worker, healthy).failures == 0
    assert caplog.text.count("focus check failed") == 1
    assert f"on the {failing} camera" in caplog.text


# ----- hands: the signs and the phone-in-hand check -----

FRONT_PHONE = Box(200, 300, 240, 360)


def make_peace_hand() -> Hand:
    """Only the middle joints and tips matter: index and middle reach past theirs, ring and pinky curl back."""
    joints = np.zeros((21, 3))
    for middle_joint, tip, tip_y in ((6, 8, -175), (10, 12, -175), (14, 16, -70), (18, 20, -70)):
        joints[middle_joint, 1] = -120
        joints[tip, 1] = tip_y
    joints[:, :2] += (320, 300)
    hand = Hand(confidence=0.95, joints=joints)
    return hand


def make_hand_over(box: Box) -> Hand:
    """A hand whose box is exactly box, making no sign: the wrist and the thumb's base sit on two corners, the rest in the middle."""
    joints = np.zeros((21, 3))
    joints[:, :2] = ((box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2)
    joints[0, :2] = (box.x1, box.y1)
    joints[1, :2] = (box.x2, box.y2)
    hand = Hand(confidence=0.95, joints=joints)
    return hand


def make_phone_view(person: Box, phone: Box) -> FrameReading:
    view = FrameReading([Detection("person", 0.9, person)], [Detection("phone", 0.8, phone)], [], 100.0)
    return view


class FakeHandScanner:
    """Hands back each camera's own hands, telling the cameras apart like TwoCameraScanner does."""

    def __init__(self, front: list[Hand] = (), side: list[Hand] = (), fail: bool = False) -> None:
        self.hands = {"front": list(front), "side": list(side)}
        self.fail = fail
        self.scans = {"front": 0, "side": 0}

    def scan(self, image: np.ndarray) -> list[Hand]:
        camera = find_camera(image)
        self.scans[camera] += 1
        if self.fail:
            raise RuntimeError("hand model exploded")
        return self.hands[camera]


def make_hand_worker(scanner, hand_scanner: FakeHandScanner, on_gesture=None) -> FocusWorker:
    worker = FocusWorker(
        FakeStream(fake_jpeg()),
        scanner,
        FocusTracker(started_at=NOON),
        on_gesture=on_gesture,
        side_stream=FakeStream(side_jpeg()),
        hand_scanner=hand_scanner,
    )
    return worker


@pytest.mark.parametrize(("camera", "fired"), [("front", [("peace", NOON + 2)]), ("side", [])])
def test_only_the_front_cameras_hands_make_signs(camera, fired):
    hand_scanner = FakeHandScanner(**{camera: [make_peace_hand()]})
    seen = []
    worker = make_hand_worker(TwoCameraScanner(), hand_scanner, on_gesture=lambda name, now: seen.append((name, now)))
    for second in range(1, 6):
        worker.run_once(NOON + second)
    assert seen == fired
    assert worker.last_gesture == ({"name": "peace", "at": NOON + 2} if fired else None)
    assert hand_scanner.scans == {"front": 5, "side": 5}, "both cameras look for hands, for the phone check"
    hand_boxes = [(box["label"], box["confidence"]) for box in worker.last_overlay["boxes"] if box["kind"] == "hand"]
    assert hand_boxes == ([("peace", 0.95)] if camera == "front" else []), "the front peek boxes a hand making a sign"
    assert all(box["kind"] != "hand" for box in worker.last_side_overlay["boxes"]), "the side can't fire signs, so no sign boxes"


@pytest.mark.parametrize(
    ("hand", "state"),
    [
        (None, "working"),
        (Box(400, 50, 460, 120), "working"),
        (Box(230, 340, 290, 420), "phone"),
        (Box(250, 300, 310, 360), "phone"),
    ],
    ids=["no hand", "hand far away", "holding it", "hand right next to it"],
)
def test_a_phone_only_counts_in_or_near_a_hand(hand, state):
    hands = [] if hand is None else [make_hand_over(hand)]
    worker = make_hand_worker(TwoCameraScanner(front=make_phone_view(FRONT_BOX, FRONT_PHONE)), FakeHandScanner(front=hands))
    for second in range(1, 7):
        update = worker.run_once(NOON + second)
    assert update.state == state
    phone_boxes = [box for box in worker.last_overlay["boxes"] if box["kind"] == "phone"]
    assert len(phone_boxes) == (1 if state == "phone" else 0), "the peek only boxes phones that count"
    assert all(box["kind"] != "hand" for box in worker.last_overlay["boxes"]), "a plain hand gets no box"


@pytest.mark.parametrize(("hand_camera", "state"), [("front", "working"), ("side", "phone")])
def test_each_camera_matches_its_own_phones_with_its_own_hands(hand_camera, state):
    side_phone = Box(40, 40, 70, 80)
    hand_scanner = FakeHandScanner(**{hand_camera: [make_hand_over(side_phone)]})
    worker = make_hand_worker(TwoCameraScanner(side=make_phone_view(SIDE_BOX, side_phone)), hand_scanner)
    for second in range(1, 7):
        update = worker.run_once(NOON + second)
    assert update.state == state


def test_a_broken_hand_model_costs_the_signs_but_not_the_focus_check_or_the_phones(caplog):
    worker = make_hand_worker(TwoCameraScanner(front=make_phone_view(FRONT_BOX, FRONT_PHONE)), FakeHandScanner(fail=True))
    with caplog.at_level(logging.ERROR):
        for second in range(1, 7):
            update = worker.run_once(NOON + second)
    assert update.state == "phone", "with the hand models broken, a phone counts anywhere, like before"
    assert worker.front.failures == 0
    assert caplog.text.count("hand check failed") == 1


def test_a_missing_hand_model_turns_signs_off_with_one_log_line(monkeypatch, tmp_path, caplog):
    from dayanpi.vision import hands

    monkeypatch.setattr(hands, "PALM_MODEL_PATH", tmp_path / "palm.onnx")
    monkeypatch.setattr(hands, "HAND_MODEL_PATH", tmp_path / "hand.onnx")
    monkeypatch.setattr(hands, "HandScanner", lambda: "hand-scanner")
    (tmp_path / "palm.onnx").write_bytes(b"x")
    with caplog.at_level(logging.INFO, logger="dayanpi.focus.worker"):
        assert focus_worker.build_hand_scanner() is None
    assert [record.getMessage() for record in caplog.records] == ["no hand models (hand.onnx): hand signs are off and phones count anywhere in the picture"]
    (tmp_path / "hand.onnx").write_bytes(b"x")
    assert focus_worker.build_hand_scanner() == "hand-scanner"
