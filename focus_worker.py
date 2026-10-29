"""Runs the detector on the live camera about once a second and feeds the FocusTracker.

It reads frames from the app's camera stream (the one opener of the camera), so it never
fights the video feed for the device. Everything the detector finds goes into the
tracker; the app's hooks get each FocusUpdate (speaker, sign) and each gesture.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path

import detector
import pose
from detector import DeskScanner, FrameReading, decode_jpeg
from focus import FocusTracker, FocusUpdate
from gestures import GestureTracker
from threads import LoopThread

logger = logging.getLogger(__name__)

CHECK_INTERVAL_S = 1.0
FRAME_WAIT_S = 0.2  # a new frame normally lands within this; none means the camera is stuck
ERROR_LOG_EVERY = 30  # consecutive failures between log lines, so a dead camera doesn't flood the journal
# systemd-timesyncd creates this once the clock is set from the network. The Pi has no battery
# clock, so until then "now" can be the time it last shut down.
CLOCK_SYNCED_PATH = Path("/run/systemd/timesync/synchronized")
CLOCK_WAIT_S = 60.0
CLOCK_POLL_S = 1.0

UpdateHook = Callable[[FocusUpdate, float], None]
GestureHook = Callable[[str, float], None]


def build_scanner() -> DeskScanner | None:
    """Loads the models, or returns None (focus disabled) when the files aren't there.

    With the pose model in models/ the full-frame pass is the pose model, which is what
    makes gestures possible; without it, the plain object model runs and gestures are off.
    """
    scanner = None
    missing = [path.name for path in (detector.OBJECT_MODEL_PATH, detector.FACE_MODEL_PATH) if not path.exists()]
    if missing:
        logger.warning("focus tracker disabled: missing model files %s", ", ".join(missing))
    else:
        try:
            if pose.POSE_MODEL_PATH.exists():
                scanner = pose.PoseDeskScanner()
                logger.info("pose model found: gestures are on")
            else:
                scanner = DeskScanner()
                logger.info("no pose model (%s): gestures are off", pose.POSE_MODEL_PATH.name)
        except Exception:
            logger.exception("focus tracker disabled: the models failed to load")
    return scanner


def wait_for_clock(synced_path: Path = CLOCK_SYNCED_PATH, timeout_s: float = CLOCK_WAIT_S, poll_s: float = CLOCK_POLL_S) -> bool:
    """Waits for the network clock sync, up to timeout_s. Returns whether it happened.

    Logging an hour of "focused" because the clock jumped forward at boot would poison the
    data, so the worker holds off. No sync file at all (not Raspberry Pi OS) means don't wait.
    """
    synced = synced_path.exists()
    deadline = time.monotonic() + timeout_s
    while not synced and synced_path.parent.parent.exists() and time.monotonic() < deadline:
        time.sleep(poll_s)
        synced = synced_path.exists()
    return synced


class FocusWorker(LoopThread):
    def __init__(
        self,
        stream,
        scanner,
        tracker: FocusTracker,
        clock: Callable[[], float] = time.time,
        on_update: UpdateHook | None = None,
        interval_s: float = CHECK_INTERVAL_S,
        on_gesture: GestureHook | None = None,
        wait_for_clock_first: bool = False,
    ) -> None:
        super().__init__(name="focus-worker", interval_s=interval_s)
        self._stream = stream
        self._scanner = scanner
        self._tracker = tracker
        self._clock = clock
        self._on_update = on_update
        self._on_gesture = on_gesture
        self._wait_for_clock_first = wait_for_clock_first
        self._last_frame_id = -1
        self.gestures = GestureTracker()
        self.checks = 0
        self.failures = 0
        self.last_update: FocusUpdate | None = None
        self.last_gesture: str | None = None

    def read_frame(self) -> FrameReading | None:
        """One detector pass on a frame newer than the last one, or None when the camera gave nothing new.

        latest_frame() would hand back the same JPEG forever when the camera freezes, and the
        tracker would log hours of "focused" from one stale picture.
        """
        reading = None
        arrived = self._stream.frame_after(self._last_frame_id, timeout=FRAME_WAIT_S)
        if arrived is not None:
            jpeg, self._last_frame_id = arrived
            image = decode_jpeg(jpeg)
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
        self.track_gestures(reading, now)
        return update

    def track_gestures(self, reading: FrameReading | None, now: float) -> None:
        main_pose = None if reading is None else pose.pick_main_pose(reading)
        gesture = self.gestures.update(main_pose, now)
        if gesture is not None:
            self.last_gesture = gesture
            logger.info("gesture: %s", gesture)
            if self._on_gesture is not None:
                try:
                    self._on_gesture(gesture, now)
                except Exception:
                    logger.exception("gesture hook failed")

    def before_loop(self) -> None:
        if self._wait_for_clock_first:
            if wait_for_clock():
                logger.info("clock is synced, focus checks starting")
            else:
                logger.warning("no clock sync after %.0f s, focus checks starting anyway", CLOCK_WAIT_S)

    def tick(self) -> None:
        self.run_once(self._clock())
