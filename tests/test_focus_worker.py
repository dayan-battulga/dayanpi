import logging
import time

import cv2
import numpy as np

import detector
import focus_worker
from detector import Box, Detection, FrameReading
from focus import FocusTracker
from focus_worker import FocusWorker

NOON = 1_800_000_000.0


def fake_jpeg() -> bytes:
    encoded = cv2.imencode(".jpg", np.full((480, 640, 3), 90, np.uint8))[1].tobytes()
    return encoded


class FakeStream:
    def __init__(self, jpeg: bytes | None) -> None:
        self.jpeg = jpeg

    def latest_frame(self) -> bytes | None:
        return self.jpeg


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


def test_build_scanner_is_none_without_model_files(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(detector, "OBJECT_MODEL_PATH", tmp_path / "missing.onnx")
    with caplog.at_level(logging.WARNING):
        assert focus_worker.build_scanner() is None
    assert "missing.onnx" in caplog.text
