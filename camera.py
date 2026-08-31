import logging
import threading
import time

import cv2

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

        self._capture = self._open_capture()
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="camera-capture",
            daemon=True,
        )
        self._thread.start()

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
