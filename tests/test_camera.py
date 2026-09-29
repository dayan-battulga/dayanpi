import camera
from camera import CameraStream


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
