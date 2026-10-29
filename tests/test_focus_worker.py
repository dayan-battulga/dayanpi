import logging
import time

import cv2
import numpy as np
import pytest

from dayanpi.vision import detector
from dayanpi.focus import worker as focus_worker
from dayanpi.vision.detector import Box, Detection, FrameReading
from dayanpi.focus.tracker import FocusTracker
from dayanpi.focus.worker import FocusWorker

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

    def frame_after(self, last_id: int, timeout: float):
        result = None
        if self.jpeg is not None:
            if not self.frozen:
                self.frame_id += 1
            if self.frame_id > last_id:
                result = (self.jpeg, self.frame_id)
        return result


class FakeScanner:
    def __init__(self, phone: float = 0.0, fail: bool = False) -> None:
        self.phone = phone
        self.fail = fail
        self.scans = 0

    def scan(self, image: np.ndarray) -> FrameReading:
        self.scans += 1
        if self.fail:
            raise RuntimeError("model exploded")
        box = Box(100, 100, 300, 400)
        phones = [Detection("phone", self.phone, box)] if self.phone else []
        reading = FrameReading([Detection("person", 0.9, box)], phones, [], 120.0)
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
    assert (overlay.frame_width, overlay.frame_height, overlay.at) == (640, 480, NOON + 1)
    assert [box.kind for box in overlay.boxes] == ["person", "phone"]
    person = overlay.boxes[0]
    assert (person.x, person.y, person.width, person.height) == pytest.approx((100 / 640, 100 / 480, 200 / 640, 300 / 480), abs=1e-4)


def test_boxes_stay_from_the_last_good_check_when_the_camera_freezes():
    tracker = FocusTracker(started_at=NOON)
    stream = FakeStream(fake_jpeg())
    worker = FocusWorker(stream, FakeScanner(), tracker)
    worker.run_once(NOON + 1)
    stream.frozen = True
    worker.run_once(NOON + 2)
    assert worker.last_overlay.at == NOON + 1


def test_scanner_errors_are_logged_and_survived(caplog):
    tracker = FocusTracker(started_at=NOON)
    worker = FocusWorker(FakeStream(fake_jpeg()), FakeScanner(fail=True), tracker)
    with caplog.at_level(logging.ERROR):
        for second in range(1, 4):
            update = worker.run_once(NOON + second)
    assert update.state == "unknown"
    assert worker.failures == 3
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


def raised_pose(left_up: bool, right_up: bool):
    from dayanpi.vision.pose import Keypoint, PoseDetection

    points = [Keypoint(x=300.0, y=300.0, confidence=0.9) for _ in range(17)]
    points[5] = Keypoint(x=260.0, y=200.0, confidence=0.9)  # left shoulder
    points[6] = Keypoint(x=340.0, y=200.0, confidence=0.9)  # right shoulder
    points[9] = Keypoint(x=250.0, y=100.0 if left_up else 300.0, confidence=0.9)  # left wrist
    points[10] = Keypoint(x=350.0, y=100.0 if right_up else 300.0, confidence=0.9)  # right wrist
    detection = PoseDetection(confidence=0.9, box=Box(200, 100, 400, 450), keypoints=points)
    return detection


class PoseScanner(FakeScanner):
    def __init__(self, right_up: bool) -> None:
        super().__init__()
        self.right_up = right_up

    def scan(self, image: np.ndarray) -> FrameReading:
        reading = super().scan(image)
        reading.poses = [raised_pose(left_up=False, right_up=self.right_up)]
        return reading


def test_a_held_gesture_reaches_the_hook_once():
    tracker = FocusTracker(started_at=NOON)
    fired = []
    worker = FocusWorker(FakeStream(fake_jpeg()), PoseScanner(right_up=True), tracker, on_gesture=lambda name, now: fired.append((name, now)))
    for second in range(1, 5):
        worker.run_once(NOON + second)
    assert fired == [("next_page", NOON + 2)]
    assert worker.last_gesture == "next_page"


def test_hands_down_means_no_gesture():
    tracker = FocusTracker(started_at=NOON)
    fired = []
    worker = FocusWorker(FakeStream(fake_jpeg()), PoseScanner(right_up=False), tracker, on_gesture=lambda name, now: fired.append(name))
    for second in range(1, 5):
        worker.run_once(NOON + second)
    assert fired == []


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


def test_build_scanner_uses_the_pose_model_when_present(monkeypatch, tmp_path, caplog):
    from dayanpi.vision import pose as pose_module

    built = []
    monkeypatch.setattr(pose_module, "POSE_MODEL_PATH", tmp_path / "pose.onnx")
    monkeypatch.setattr(pose_module, "PoseDeskScanner", lambda: built.append("pose") or "pose-scanner")
    monkeypatch.setattr(focus_worker, "DeskScanner", lambda: built.append("plain") or "plain-scanner")
    monkeypatch.setattr(detector, "OBJECT_MODEL_PATH", tmp_path / "yolo.onnx")
    monkeypatch.setattr(detector, "FACE_MODEL_PATH", tmp_path / "face.onnx")
    (tmp_path / "yolo.onnx").write_bytes(b"x")
    (tmp_path / "face.onnx").write_bytes(b"x")
    assert focus_worker.build_scanner() == "plain-scanner"
    (tmp_path / "pose.onnx").write_bytes(b"x")
    assert focus_worker.build_scanner() == "pose-scanner"
    assert built == ["plain", "pose"]


def test_build_scanner_is_none_without_model_files(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(detector, "OBJECT_MODEL_PATH", tmp_path / "missing.onnx")
    with caplog.at_level(logging.WARNING):
        assert focus_worker.build_scanner() is None
    assert "missing.onnx" in caplog.text
