"""Runs the detector on the live camera about once a second and feeds the FocusTracker.

It reads frames from the app's CameraStream (the one opener of the camera), so it never
fights the video feed for the device. Everything the detector finds goes into the
tracker; the app's hook gets each FocusUpdate for the speaker and the sign.
"""

import logging
import threading
import time
from collections.abc import Callable

import detector
from detector import DeskScanner, FrameReading, decode_jpeg
from focus import FocusTracker, FocusUpdate

logger = logging.getLogger(__name__)

CHECK_INTERVAL_S = 1.0
STOP_JOIN_TIMEOUT_S = 3.0
ERROR_LOG_EVERY = 30  # consecutive failures between log lines, so a dead camera doesn't flood the journal

UpdateHook = Callable[[FocusUpdate, float], None]


def build_scanner() -> DeskScanner | None:
    """Loads the models, or returns None (focus disabled) when the files aren't there."""
    scanner = None
    missing = [path.name for path in (detector.OBJECT_MODEL_PATH, detector.FACE_MODEL_PATH) if not path.exists()]
    if missing:
        logger.warning("focus tracker disabled: missing model files %s", ", ".join(missing))
    else:
        try:
            scanner = DeskScanner()
        except Exception:
            logger.exception("focus tracker disabled: the models failed to load")
    return scanner


class FocusWorker:
    def __init__(
        self,
        stream,
        scanner,
        tracker: FocusTracker,
        clock: Callable[[], float] = time.time,
        on_update: UpdateHook | None = None,
        interval_s: float = CHECK_INTERVAL_S,
    ) -> None:
        self._stream = stream
        self._scanner = scanner
        self._tracker = tracker
        self._clock = clock
        self._on_update = on_update
        self._interval_s = interval_s
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.checks = 0
        self.failures = 0
        self.last_update: FocusUpdate | None = None

    @property
    def running(self) -> bool:
        alive = self._thread is not None and self._thread.is_alive()
        return alive

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="focus-worker", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=STOP_JOIN_TIMEOUT_S)
            self._thread = None

    def read_frame(self) -> FrameReading | None:
        """One detector pass on the latest frame, or None when there's no frame to read."""
        reading = None
        jpeg = self._stream.latest_frame()
        image = None if jpeg is None else decode_jpeg(jpeg)
        if image is not None:
            reading = self._scanner.scan(image)
        return reading

    def run_once(self, now: float) -> FocusUpdate:
        reading = None
        try:
            reading = self.read_frame()
            self.failures = 0
        except Exception:
            self.failures += 1
            if self.failures == 1 or self.failures % ERROR_LOG_EVERY == 0:
                logger.exception("focus check failed (%s in a row)", self.failures)
        update = self._tracker.update(reading, now)
        self.checks += 1
        self.last_update = update
        if self._on_update is not None:
            try:
                self._on_update(update, now)
            except Exception:
                logger.exception("focus update hook failed")
        return update

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self.run_once(self._clock())
            spent = time.monotonic() - started
            self._stop.wait(max(0.0, self._interval_s - spent))
