import logging
import os
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

# Tunables — change these in one place only.
DEVICE_PATH = "/dev/video0"
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FRAME_SKIP = 2  # keep 1 of every N frames when streaming
RECONNECT_SLEEP_S = 1.0
LOOP_SLEEP_S = 0.01
FAILURE_LOG_THRESHOLD = 3
START_TIMEOUT_S = 2.0
STOP_JOIN_TIMEOUT_S = 2.0

# Pi camera (ribbon cable) through Picamera2.
PICAMERA_INDEX = 0  # which Pi camera if two are plugged in; USB webcams don't count
PICAMERA_FORMAT = "RGB888"  # despite the name, Picamera2's RGB888 is B, G, R in memory: OpenCV's order
PICAMERA_FPS = 15
PICAMERA_JPEG_QUALITY = 80
PICAMERA_FULL_VIEW = True  # read the whole sensor; False lets Picamera2 pick a mode that crops the middle
PICAMERA_CAPTURE_TIMEOUT_S = 1.0  # keep under STOP_JOIN_TIMEOUT_S so stop() can join the capture thread
AUTOFOCUS_CONTROL = "AfMode"
USB_CAMERA_ID_PART = "/usb"  # libcamera lists USB webcams too; Picamera2 spots them by this in their Id

# Which camera create_stream() hands out.
CAMERA_SETTING_ENV = "DAYANPI_CAMERA"
USB_DEVICE_ENV = "DAYANPI_USB_DEVICE"
CAMERA_AUTO = "auto"
CAMERA_USB = "usb"
CAMERA_PICAMERA = "picamera"
CAMERA_SETTINGS = (CAMERA_AUTO, CAMERA_USB, CAMERA_PICAMERA)

logger = logging.getLogger(__name__)


class CameraStream:
    """One opener of /dev/video0; readers take copies of the latest JPEG."""

    def __init__(
        self,
        device: str = DEVICE_PATH,
        width: int = FRAME_WIDTH,
        height: int = FRAME_HEIGHT,
        frame_skip: int = FRAME_SKIP,
    ) -> None:
        self._device = device
        self._width = width
        self._height = height
        self._frame_skip = max(1, frame_skip)

        self._capture: cv2.VideoCapture | None = None
        self._frame: bytes | None = None
        self._frame_id = 0
        # Condition (not Lock): readers wait for notify instead of busy-polling.
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._running = False

    def _open_capture(self) -> cv2.VideoCapture:
        capture = cv2.VideoCapture(self._device, cv2.CAP_V4L2)
        if not capture.isOpened():
            raise OSError(f"failed to open {self._device}")

        # Order matters: format before resolution.
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _reconnect(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

        time.sleep(RECONNECT_SLEEP_S)

        try:
            self._capture = self._open_capture()
            logger.info("camera reopened on %s", self._device)
        except OSError as error:
            logger.warning("camera reopen failed: %s", error)

    def _capture_loop(self) -> None:
        skip_counter = 0
        consecutive_failures = 0

        while self._running:
            if self._capture is None:
                self._reconnect()
                continue

            ok, frame = self._capture.read()
            if not ok or frame is None:
                consecutive_failures += 1
                if consecutive_failures == FAILURE_LOG_THRESHOLD:
                    logger.warning(
                        "camera read failing (%s consecutive); reconnecting",
                        consecutive_failures,
                    )
                elif consecutive_failures > FAILURE_LOG_THRESHOLD and (
                    consecutive_failures % FAILURE_LOG_THRESHOLD == 0
                ):
                    logger.warning(
                        "camera still failing (%s consecutive)",
                        consecutive_failures,
                    )
                self._reconnect()
                continue

            consecutive_failures = 0
            skip_counter += 1
            if skip_counter % self._frame_skip != 0:
                time.sleep(LOOP_SLEEP_S)
                continue

            jpeg = frame.tobytes()
            with self._condition:
                self._frame = jpeg
                self._frame_id += 1
                self._condition.notify_all()

            time.sleep(LOOP_SLEEP_S)

    def start(self) -> None:
        if self._running:
            return

        opened = True
        try:
            self._capture = self._open_capture()
        except OSError as error:
            # _capture stays None; the capture loop keeps reconnecting.
            opened = False
            logger.warning("camera unavailable at startup, will keep retrying: %s", error)

        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="camera-capture",
            daemon=True,
        )
        self._thread.start()

        if opened:
            with self._condition:
                ready = self._condition.wait_for(
                    lambda: self._frame is not None,
                    timeout=START_TIMEOUT_S,
                )
            if not ready:
                logger.warning(
                    "camera started but no frame within %.1fs",
                    START_TIMEOUT_S,
                )

    def stop(self) -> None:
        self._running = False

        if self._thread is not None:
            self._thread.join(timeout=STOP_JOIN_TIMEOUT_S)
            self._thread = None

        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def latest_frame(self) -> bytes | None:
        with self._condition:
            return self._frame

    def frame_after(
        self,
        last_id: int,
        timeout: float,
    ) -> tuple[bytes, int] | None:
        with self._condition:
            ready = self._condition.wait_for(
                lambda: self._frame is not None and self._frame_id > last_id,
                timeout=timeout,
            )
            if not ready or self._frame is None:
                return None
            return self._frame, self._frame_id


@dataclass
class PiCameraInfo:
    """One ribbon-cable camera from Picamera2.global_camera_info()."""

    position: int  # its place in that list, which is what Picamera2(camera_num) takes (not its "Num")
    model: str


@dataclass
class CameraChoice:
    backend: str  # CAMERA_USB or CAMERA_PICAMERA
    reason: str


def list_pi_cameras(picamera2_class: type) -> list[PiCameraInfo]:
    """The ribbon-cable cameras libcamera can see, leaving out the USB webcams it also lists."""
    camera_infos = picamera2_class.global_camera_info()
    pi_cameras = [
        PiCameraInfo(position=position, model=str(info.get("Model", "unknown")))
        for position, info in enumerate(camera_infos)
        if USB_CAMERA_ID_PART not in info.get("Id", "")
    ]
    return pi_cameras


def measure_view(sensor_mode: dict) -> int:
    """How much of the sensor a mode reads: the area of its crop_limits (x, y, width, height)."""
    view_area = sensor_mode["crop_limits"][2] * sensor_mode["crop_limits"][3]
    return view_area


def pick_full_view_mode(sensor_modes: list[dict]) -> dict | None:
    """The smallest sensor mode that still reads the whole sensor.

    Left alone, Picamera2 picks the mode closest to 640x480. On the Camera Module 3
    that's 1536x864, which only reads the middle of the sensor and throws away a big
    chunk of the Wide lens's view.
    """
    widest_view = max((measure_view(mode) for mode in sensor_modes), default=0)
    full_view_modes = [mode for mode in sensor_modes if measure_view(mode) == widest_view]
    full_view_mode = min(full_view_modes, key=lambda mode: mode["size"][0] * mode["size"][1], default=None)
    return full_view_mode


class PiCameraCapture:
    """An open Pi camera that reads like cv2.VideoCapture, so CameraStream's capture loop can drive it.

    read() hands back a JPEG in a numpy buffer, the same thing the USB webcam's MJPEG
    passthrough gives, so /video and the detector don't change.
    """

    def __init__(self, camera_index: int, width: int, height: int, fps: float) -> None:
        from picamera2 import Picamera2

        pi_cameras = list_pi_cameras(Picamera2)
        if camera_index >= len(pi_cameras):
            raise OSError(f"no Pi camera #{camera_index} (libcamera sees {len(pi_cameras)})")

        self._camera = Picamera2(pi_cameras[camera_index].position)
        self._read_failures = 0
        try:
            self._camera.configure(self._create_configuration(width, height, fps))
            self._camera.start()
            self._turn_on_autofocus()
        except Exception:
            # The camera stays claimed until close(), and every retry after that would find it busy.
            self._camera.close()
            raise

    def _create_configuration(self, width: int, height: int, fps: float) -> dict:
        frame_duration_us = round(1_000_000 / fps)
        full_view_mode = pick_full_view_mode(self._camera.sensor_modes) if PICAMERA_FULL_VIEW else None
        sensor = {}
        if full_view_mode is not None:
            sensor = {"output_size": full_view_mode["size"], "bit_depth": full_view_mode["bit_depth"]}
        configuration = self._camera.create_video_configuration(
            main={"size": (width, height), "format": PICAMERA_FORMAT},
            sensor=sensor,
            controls={"FrameDurationLimits": (frame_duration_us, frame_duration_us)},
        )
        return configuration

    def _turn_on_autofocus(self) -> None:
        # Cameras without autofocus don't list AfMode, and setting it anyway raises.
        if AUTOFOCUS_CONTROL in self._camera.camera_controls:
            from libcamera import controls

            self._camera.set_controls({AUTOFOCUS_CONTROL: controls.AfModeEnum.Continuous})

    def read(self) -> tuple[bool, np.ndarray | None]:
        # Same shape as cv2.VideoCapture.read(), because CameraStream's capture loop calls it.
        jpeg = None
        try:
            frame = self._camera.capture_array("main", wait=PICAMERA_CAPTURE_TIMEOUT_S)
            encoded, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, PICAMERA_JPEG_QUALITY])
            jpeg = buffer if encoded else None
            self._read_failures = 0
        except Exception as error:
            # The capture loop already warns and reconnects; this just says why, and not 15 times a second.
            self._read_failures += 1
            if self._read_failures == 1:
                logger.warning("Pi camera capture failed: %r", error)
        read_result = (jpeg is not None, jpeg)
        return read_result

    def release(self) -> None:
        try:
            self._camera.close()
        except Exception as error:
            # CameraStream releases from its capture thread, and an exception there would end the thread.
            logger.warning("closing the Pi camera failed: %r", error)


class PiCameraStream(CameraStream):
    """The Pi camera on the ribbon cable, served exactly like the USB webcam.

    Only opening the camera is different. The capture loop, reconnects, start/stop and
    the frame readers all come from CameraStream.
    """

    def __init__(
        self,
        camera_index: int = PICAMERA_INDEX,
        width: int = FRAME_WIDTH,
        height: int = FRAME_HEIGHT,
        fps: float = PICAMERA_FPS,
    ) -> None:
        # frame_skip=1: the camera itself is slowed down to fps, so skipping frames would halve it again.
        super().__init__(f"Pi camera {camera_index}", width, height, frame_skip=1)
        self._camera_index = camera_index
        self._fps = fps

    def _open_capture(self) -> PiCameraCapture:
        try:
            capture = PiCameraCapture(self._camera_index, self._width, self._height, self._fps)
        except Exception as error:
            # CameraStream only retries on OSError, and picamera2 fails with ImportError, RuntimeError and more.
            raise OSError(f"can't open {self._device}: {type(error).__name__}: {error}") from error
        return capture


def detect_camera() -> CameraChoice:
    """What "auto" means: the Pi camera if picamera2 loads and sees one, otherwise the USB webcam."""
    try:
        from picamera2 import Picamera2

        pi_cameras = list_pi_cameras(Picamera2)
        choice = CameraChoice(CAMERA_USB, "auto, picamera2 sees no Pi camera")
        if len(pi_cameras) > PICAMERA_INDEX:
            choice = CameraChoice(CAMERA_PICAMERA, f"auto, found {pi_cameras[PICAMERA_INDEX].model}")
    except ModuleNotFoundError as error:
        choice = CameraChoice(CAMERA_USB, f"auto, can't import {error.name}")
    except Exception as error:
        # A broken install fails with more than ImportError, e.g. ValueError when pip's numpy doesn't match apt's.
        logger.warning("picamera2 is installed but failed (%r), so using the USB webcam", error)
        choice = CameraChoice(CAMERA_USB, f"auto, picamera2 failed: {error!r}")
    return choice


def create_stream() -> CameraStream:
    """The camera the app should use, picked by DAYANPI_CAMERA: auto (the default), usb or picamera.

    DAYANPI_USB_DEVICE points the webcam somewhere other than /dev/video0. On a Pi 5 with a
    Pi camera plugged in, /dev/video0 can belong to the Pi camera's own hardware, so a
    /dev/v4l/by-id/... path is the safe way to name the webcam.
    """
    setting = os.environ.get(CAMERA_SETTING_ENV, "").strip().lower() or CAMERA_AUTO
    if setting not in CAMERA_SETTINGS:
        logger.warning("%s=%r isn't one of %s, so using auto", CAMERA_SETTING_ENV, setting, ", ".join(CAMERA_SETTINGS))
        setting = CAMERA_AUTO
    choice = detect_camera() if setting == CAMERA_AUTO else CameraChoice(setting, f"{CAMERA_SETTING_ENV}={setting}")

    if choice.backend == CAMERA_PICAMERA:
        stream = PiCameraStream()
        logger.info("camera: Pi camera through picamera2 (%s)", choice.reason)
    else:
        usb_device = os.environ.get(USB_DEVICE_ENV, "").strip() or DEVICE_PATH
        stream = CameraStream(usb_device)
        logger.info("camera: USB webcam at %s (%s)", usb_device, choice.reason)
    return stream


if __name__ == "__main__":
    import json

    import collector

    logging.basicConfig(level=logging.INFO)

    stream = CameraStream()
    sampler = collector.RateSampler("wlan0")
    sampler.sample()  # baseline so rates aren't null

    stream.start()
    last_id = 0

    try:
        for i in range(30):
            result = stream.frame_after(last_id, timeout=2.0)
            if result is None:
                print(f"frame {i}: timeout")
                continue

            jpeg, last_id = result
            print(f"frame {i}: id={last_id} bytes={len(jpeg)}")

            if i % 10 == 0:
                path = f"checkpoint_{i:02d}.jpg"
                with open(path, "wb") as file:
                    file.write(jpeg)
                print(f"  wrote {path}")

            print(json.dumps(collector.snapshot(sampler), indent=2))
    finally:
        stream.stop()
        print("stopped")
