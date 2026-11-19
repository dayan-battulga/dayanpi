import time
import types

import pytest

from dayanpi.hardware import camera
from dayanpi.hardware.camera import CameraStream


class FakeFrame:
    def tobytes(self) -> bytes:
        return b"jpeg-bytes"


class FakeCapture:
    def read(self):
        return True, FakeFrame()

    def release(self) -> None:
        pass


def test_start_survives_missing_camera(monkeypatch, caplog):
    monkeypatch.setattr(camera, "RECONNECT_SLEEP_S", 0.01)
    stream = CameraStream("/dev/does-not-exist")
    stream.start()
    try:
        assert stream._thread.is_alive()
        assert "camera unavailable at startup" in caplog.text
    finally:
        stream.stop()


def test_capture_loop_recovers_when_camera_appears(monkeypatch):
    monkeypatch.setattr(camera, "RECONNECT_SLEEP_S", 0.01)
    open_attempts = []

    def open_capture_late(self):
        open_attempts.append(1)
        if len(open_attempts) < 3:
            raise OSError("not plugged in yet")
        return FakeCapture()

    monkeypatch.setattr(CameraStream, "_open_capture", open_capture_late)
    stream = CameraStream(frame_skip=1)
    stream.start()
    try:
        result = stream.frame_after(-1, timeout=2.0)
        assert result is not None
        assert result[0] == b"jpeg-bytes"
        assert len(open_attempts) >= 3
    finally:
        stream.stop()


def test_a_camera_that_dropped_out_keeps_its_last_frame_but_it_ages(monkeypatch):
    monkeypatch.setattr(camera, "RECONNECT_SLEEP_S", 0.05)
    reads = []

    class DyingCapture:
        def read(self):
            reads.append(1)
            return (True, FakeFrame()) if len(reads) <= 2 else (False, None)

        def release(self) -> None:
            pass

    monkeypatch.setattr(CameraStream, "_open_capture", lambda self: DyingCapture())
    stream = CameraStream(frame_skip=1)
    assert stream.frame_age_s() is None, "no frame yet"
    stream.start()
    try:
        assert stream.frame_after(-1, timeout=2.0) is not None
        time.sleep(0.3)
        assert stream.latest_frame() == b"jpeg-bytes" and stream.frame_age_s() >= 0.2
    finally:
        stream.stop()


class FailingCapture:
    def read(self):
        return False, None

    def release(self) -> None:
        pass


def test_read_failures_name_the_camera(monkeypatch, caplog):
    monkeypatch.setattr(camera, "RECONNECT_SLEEP_S", 0.001)
    monkeypatch.setattr(CameraStream, "_open_capture", lambda self: FailingCapture())
    stream = CameraStream("/dev/v4l/by-id/usb-front-video-index0", frame_skip=1)
    stream.start()
    try:
        deadline = time.monotonic() + 2.0
        while "camera read failing" not in caplog.text and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        stream.stop()
    assert "camera read failing on /dev/v4l/by-id/usb-front-video-index0" in caplog.text


def test_a_stream_on_the_fallback_finds_a_webcam_plugged_in_later(monkeypatch, tmp_path):
    monkeypatch.delenv(camera.USB_DEVICE_ENV, raising=False)
    monkeypatch.setattr(camera, "USB_BY_ID_PATTERN", str(tmp_path / "*-video-index0"))
    tried = []

    def closed_capture(device, backend):
        tried.append(device)
        return types.SimpleNamespace(isOpened=lambda: False)

    monkeypatch.setattr(camera.cv2, "VideoCapture", closed_capture)
    stream = CameraStream(camera.find_usb_device())
    with pytest.raises(OSError):
        stream._open_capture()

    webcam = tmp_path / "usb-USB_Live_camera-video-index0"
    webcam.touch()
    with pytest.raises(OSError):
        stream._open_capture()

    webcam.unlink()  # unplugged again: it keeps waiting at this name, not at the Pi camera's /dev/video0
    with pytest.raises(OSError):
        stream._open_capture()
    assert tried == [camera.DEVICE_PATH, str(webcam), str(webcam)]
