import logging
import sys
import time
import types
from contextlib import contextmanager

import numpy as np
import pytest

import camera
from camera import CameraStream, PiCameraStream
from detector import decode_jpeg

PI_CAMERA_INFO = {
    "Model": "imx708_wide",
    "Location": 2,
    "Rotation": 180,
    "Id": "/base/axi/pcie@120000/rp1/i2c@88000/imx708@1a",
    "Num": 0,
}
USB_CAMERA_INFO = {
    "Model": "HD USB Camera",
    "Location": 2,
    "Rotation": 0,
    "Id": "/base/axi/pcie@120000/rp1/usb@200000-1:1.0-32e4:9230",
    "Num": 1,
}
# Same modes and crops as `rpicam-hello --list-cameras` shows for the Camera Module 3.
IMX708_MODES = [
    {"format": "SRGGB10_CSI2P", "bit_depth": 10, "size": (1536, 864), "crop_limits": (768, 432, 3072, 1728)},
    {"format": "SRGGB10_CSI2P", "bit_depth": 10, "size": (2304, 1296), "crop_limits": (0, 0, 4608, 2592)},
    {"format": "SRGGB10_CSI2P", "bit_depth": 10, "size": (4608, 2592), "crop_limits": (0, 0, 4608, 2592)},
]
AUTOFOCUS_CONTROLS = {"AfMode": (0, 2, 0), "FrameDurationLimits": (8333, 1000000, 33333)}
AF_CONTINUOUS = "AfModeContinuous"
BLUE = (255, 0, 0)  # B, G, R: the order RGB888 frames come in
FAKE_FRAME_INTERVAL_S = 0.005
FRAME_TIMEOUT_S = 2.0
USB_WEBCAM_BY_ID = "/dev/v4l/by-id/usb-HD_USB_Camera_HD_USB_Camera-video-index0"


class FakeCameraSystem:
    """What the fake picamera2 sees (plugged-in cameras, failures to act out), plus every camera the app opened."""

    def __init__(self) -> None:
        self.camera_infos = [PI_CAMERA_INFO]
        self.sensor_modes = IMX708_MODES
        self.camera_controls = AUTOFOCUS_CONTROLS
        self.listing_error: Exception | None = None
        self.listing_calls = 0
        self.failed_configures = 0
        self.failed_captures = 0
        self.opened: list[FakePicamera2] = []


class FakePicamera2:
    """Just enough of picamera2.Picamera2 for PiCameraStream. Hands out solid blue BGR frames."""

    system: FakeCameraSystem

    def __init__(self, camera_num: int = 0) -> None:
        self.camera_num = camera_num
        self.sensor_modes = self.system.sensor_modes
        self.camera_controls = self.system.camera_controls
        self.configuration: dict | None = None
        self.controls_set: list[dict] = []
        self.capture_wait: float | None = None
        self.started = False
        self.closed = False
        self.system.opened.append(self)

    @classmethod
    def global_camera_info(cls) -> list[dict]:
        cls.system.listing_calls += 1
        if cls.system.listing_error is not None:
            raise cls.system.listing_error
        camera_infos = list(cls.system.camera_infos)
        return camera_infos

    def create_video_configuration(self, main: dict, sensor: dict, controls: dict) -> dict:
        configuration = {"main": main, "sensor": sensor, "controls": controls}
        return configuration

    def configure(self, configuration: dict) -> None:
        if self.system.failed_configures > 0:
            self.system.failed_configures -= 1
            raise RuntimeError("Failed to configure camera")
        self.configuration = configuration

    def start(self) -> None:
        self.started = True

    def set_controls(self, controls: dict) -> None:
        self.controls_set.append(controls)

    def capture_array(self, name: str = "main", wait: float | None = None) -> np.ndarray:
        if not self.started:
            raise RuntimeError("Camera is not running")
        if self.system.failed_captures > 0:
            self.system.failed_captures -= 1
            raise TimeoutError("no frame from the camera")
        self.capture_wait = wait
        time.sleep(FAKE_FRAME_INTERVAL_S)
        width, height = self.configuration[name]["size"]
        frame = np.full((height, width, 3), BLUE, dtype=np.uint8)
        return frame

    def close(self) -> None:
        self.started = False
        self.closed = True


def raise_numpy_mismatch(name: str) -> None:
    # What `from picamera2 import Picamera2` does when pip's numpy doesn't match apt's simplejpeg.
    if name == "Picamera2":
        raise ValueError("numpy.dtype size changed, may indicate binary incompatibility")
    raise AttributeError(name)


@pytest.fixture(autouse=True)
def quick_retries_and_no_camera_settings(monkeypatch):
    monkeypatch.setattr(camera, "RECONNECT_SLEEP_S", 0.01)
    monkeypatch.delenv(camera.CAMERA_SETTING_ENV, raising=False)
    monkeypatch.delenv(camera.USB_DEVICE_ENV, raising=False)


@pytest.fixture
def cameras(monkeypatch) -> FakeCameraSystem:
    system = FakeCameraSystem()
    picamera2_module = types.ModuleType("picamera2")
    picamera2_module.Picamera2 = type("Picamera2", (FakePicamera2,), {"system": system})
    libcamera_module = types.ModuleType("libcamera")
    libcamera_module.controls = types.SimpleNamespace(AfModeEnum=types.SimpleNamespace(Continuous=AF_CONTINUOUS))
    monkeypatch.setitem(sys.modules, "picamera2", picamera2_module)
    monkeypatch.setitem(sys.modules, "libcamera", libcamera_module)
    return system


@pytest.fixture
def no_picamera2(monkeypatch):
    # Same failure as a Pi without python3-picamera2, or a venv that can't see apt packages.
    monkeypatch.setitem(sys.modules, "picamera2", None)


@contextmanager
def run_stream(stream: CameraStream):
    stream.start()
    try:
        yield stream
    finally:
        stream.stop()


def test_pi_stream_serves_640x480_jpegs_in_the_right_colors(cameras):
    with run_stream(PiCameraStream()) as stream:
        result = stream.frame_after(-1, timeout=FRAME_TIMEOUT_S)
        assert stream.latest_frame() is not None
    assert result is not None
    jpeg, frame_id = result
    assert frame_id >= 1
    assert jpeg[:2] == b"\xff\xd8"
    image = decode_jpeg(jpeg)
    assert image.shape == (480, 640, 3)
    assert np.abs(image[240, 320].astype(int) - BLUE).max() <= 3


def test_pi_stream_asks_for_rgb888_at_15fps_with_autofocus_and_the_full_view(cameras):
    with run_stream(PiCameraStream()) as stream:
        assert stream.frame_after(-1, timeout=FRAME_TIMEOUT_S) is not None
    opened = cameras.opened[0]
    assert opened.configuration == {
        "main": {"size": (640, 480), "format": "RGB888"},
        "sensor": {"output_size": (2304, 1296), "bit_depth": 10},
        "controls": {"FrameDurationLimits": (66667, 66667)},
    }
    assert opened.controls_set == [{"AfMode": AF_CONTINUOUS}]
    assert opened.capture_wait == camera.PICAMERA_CAPTURE_TIMEOUT_S


def test_camera_without_autofocus_still_streams(cameras):
    cameras.camera_controls = {"FrameDurationLimits": (8333, 1000000, 33333)}
    with run_stream(PiCameraStream()) as stream:
        assert stream.frame_after(-1, timeout=FRAME_TIMEOUT_S) is not None
    assert cameras.opened[0].controls_set == []


def test_full_view_mode_skips_the_cropped_fast_mode():
    assert camera.pick_full_view_mode(IMX708_MODES)["size"] == (2304, 1296)
    assert camera.pick_full_view_mode([]) is None


def test_full_view_can_be_turned_off(cameras, monkeypatch):
    monkeypatch.setattr(camera, "PICAMERA_FULL_VIEW", False)
    with run_stream(PiCameraStream()) as stream:
        assert stream.frame_after(-1, timeout=FRAME_TIMEOUT_S) is not None
    assert cameras.opened[0].configuration["sensor"] == {}


def test_stop_ends_the_capture_thread_and_closes_the_camera(cameras):
    stream = PiCameraStream()
    stream.start()
    capture_thread = stream._thread
    assert capture_thread.is_alive()
    stream.stop()
    assert not capture_thread.is_alive()
    assert stream._thread is None
    assert cameras.opened[0].closed


def test_frame_after_waits_for_newer_frames_and_times_out_when_none_come(cameras):
    with run_stream(PiCameraStream()) as stream:
        first = stream.frame_after(-1, timeout=FRAME_TIMEOUT_S)
        second = stream.frame_after(first[1], timeout=FRAME_TIMEOUT_S)
        assert second[1] > first[1]
    newest = stream.frame_after(first[1], timeout=0.05)
    assert newest[1] >= second[1]
    assert stream.frame_after(newest[1], timeout=0.05) is None


def test_stream_without_picamera2_warns_keeps_retrying_and_recovers(cameras, monkeypatch, caplog):
    working_picamera2 = sys.modules["picamera2"]
    monkeypatch.setitem(sys.modules, "picamera2", None)
    with run_stream(PiCameraStream()) as stream:
        assert stream._thread.is_alive()
        assert "camera unavailable at startup" in caplog.text
        assert "picamera2" in caplog.text
        monkeypatch.setitem(sys.modules, "picamera2", working_picamera2)
        assert stream.frame_after(-1, timeout=FRAME_TIMEOUT_S) is not None


def test_stream_without_a_pi_camera_warns_keeps_retrying_and_recovers(cameras, caplog):
    cameras.camera_infos = [USB_CAMERA_INFO]
    with run_stream(PiCameraStream()) as stream:
        assert stream._thread.is_alive()
        assert "no Pi camera #0" in caplog.text
        assert cameras.opened == []
        cameras.camera_infos = [PI_CAMERA_INFO, USB_CAMERA_INFO]
        assert stream.frame_after(-1, timeout=FRAME_TIMEOUT_S) is not None


def test_failed_setup_closes_the_camera_before_retrying(cameras, caplog):
    cameras.failed_configures = 1
    with run_stream(PiCameraStream()) as stream:
        assert stream.frame_after(-1, timeout=FRAME_TIMEOUT_S) is not None
    first_try, second_try = cameras.opened[:2]
    assert first_try.closed
    assert first_try.configuration is None
    assert second_try.configuration is not None
    assert "camera unavailable at startup" in caplog.text


def test_capture_errors_reopen_the_camera(cameras, caplog):
    cameras.failed_captures = 1
    with run_stream(PiCameraStream()) as stream:
        assert stream.frame_after(-1, timeout=FRAME_TIMEOUT_S) is not None
    assert "Pi camera capture failed" in caplog.text
    assert len(cameras.opened) == 2
    assert cameras.opened[0].closed


def test_opens_the_pi_camera_when_libcamera_lists_a_usb_webcam_first(cameras):
    cameras.camera_infos = [USB_CAMERA_INFO, PI_CAMERA_INFO]
    with run_stream(PiCameraStream()) as stream:
        assert stream.frame_after(-1, timeout=FRAME_TIMEOUT_S) is not None
    assert cameras.opened[0].camera_num == 1


@pytest.mark.parametrize("setting", [None, "", "auto", " AUTO "])
def test_auto_picks_the_pi_camera_when_one_is_plugged_in(cameras, monkeypatch, caplog, setting):
    if setting is not None:
        monkeypatch.setenv(camera.CAMERA_SETTING_ENV, setting)
    caplog.set_level(logging.INFO, logger=camera.logger.name)
    stream = camera.create_stream()
    assert isinstance(stream, PiCameraStream)
    assert "found imx708_wide" in caplog.text
    assert cameras.opened == []


def test_auto_ignores_usb_webcams_that_libcamera_lists(cameras):
    cameras.camera_infos = [USB_CAMERA_INFO]
    stream = camera.create_stream()
    assert type(stream) is CameraStream
    assert stream._device == "/dev/video0"


def test_auto_without_picamera2_uses_the_usb_webcam(no_picamera2, caplog):
    caplog.set_level(logging.INFO, logger=camera.logger.name)
    stream = camera.create_stream()
    assert type(stream) is CameraStream
    assert stream._device == "/dev/video0"
    assert "can't import picamera2" in caplog.text


@pytest.mark.parametrize("failure", ["libcamera", "numpy"])
def test_auto_with_a_broken_picamera2_warns_and_uses_the_usb_webcam(cameras, monkeypatch, caplog, failure):
    if failure == "libcamera":
        cameras.listing_error = RuntimeError("libcamera fell over")
    else:
        broken_picamera2 = types.ModuleType("picamera2")
        broken_picamera2.__getattr__ = raise_numpy_mismatch
        monkeypatch.setitem(sys.modules, "picamera2", broken_picamera2)
    stream = camera.create_stream()
    assert type(stream) is CameraStream
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "picamera2 is installed but failed" in warnings[0]


def test_usb_setting_never_asks_picamera2(cameras, monkeypatch):
    monkeypatch.setenv(camera.CAMERA_SETTING_ENV, "usb")
    stream = camera.create_stream()
    assert type(stream) is CameraStream
    assert stream._device == "/dev/video0"
    assert cameras.listing_calls == 0


@pytest.mark.parametrize("setting", ["picamera", " PiCamera "])
def test_picamera_setting_forces_the_pi_camera_even_without_picamera2(no_picamera2, monkeypatch, setting):
    monkeypatch.setenv(camera.CAMERA_SETTING_ENV, setting)
    stream = camera.create_stream()
    assert isinstance(stream, PiCameraStream)


@pytest.mark.parametrize("setting", ["usb", "auto"])
def test_usb_device_override(no_picamera2, monkeypatch, setting):
    monkeypatch.setenv(camera.CAMERA_SETTING_ENV, setting)
    monkeypatch.setenv(camera.USB_DEVICE_ENV, USB_WEBCAM_BY_ID)
    stream = camera.create_stream()
    assert type(stream) is CameraStream
    assert stream._device == USB_WEBCAM_BY_ID


def test_unknown_setting_warns_and_acts_like_auto(cameras, monkeypatch, caplog):
    monkeypatch.setenv(camera.CAMERA_SETTING_ENV, "webcam")
    stream = camera.create_stream()
    assert isinstance(stream, PiCameraStream)
    assert "isn't one of auto, usb, picamera" in caplog.text
